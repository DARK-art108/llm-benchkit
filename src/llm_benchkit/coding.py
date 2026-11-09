"""Bounded editing agent with Docker-only execution of generated programs."""

import collections
import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

from .tasks import TASKS

TOOLS = []
for name, description, properties, required in [
    ("read_file", "Read a project file.", {"path": {"type": "string"}}, ["path"]),
    ("write_file", "Replace a complete source file.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    ("search_code", "Find files containing literal text.", {"query": {"type": "string"}}, ["query"]),
    ("run_tests", "Run the project test suite.", {}, []),
]:
    TOOLS.append({"type": "function", "function": {"name": name, "description": description,
                  "parameters": {"type": "object", "properties": properties, "required": required,
                                 "additionalProperties": False}}})

PY_RUNNER = '''import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
suite = unittest.defaultTestLoader.loadTestsFromName("tests")
result = unittest.TextTestRunner(verbosity=1).run(suite)
passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
print("BENCHKIT_RESULT=" + json.dumps({"total": result.testsRun, "passed": passed}), flush=True)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
'''


def safe_path(directory, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("File path must be a nonempty relative POSIX path")
    p = PurePosixPath(name)
    if not p.parts or p.is_absolute() or ".." in p.parts or ":" in name:
        raise ValueError("File path must stay within the fixture")
    target = directory.joinpath(*p.parts)
    if not target.resolve().is_relative_to(directory.resolve()) or target.is_symlink():
        raise ValueError("Symlinks and escaped paths are not allowed")
    return target


def load_tasks(path=None):
    if path:
        tasks = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        tasks = []
        for t, count in zip(TASKS, (8, 12, 7)):
            python = t["language"] == "python"
            tests = {"tests.py" if python else "tests.js": t["tests"]}
            if python:
                tests["_benchkit_runner.py"] = PY_RUNNER
            tasks.append({"id": t["id"], "instructions": t["files"]["README.txt"],
                          "source_files": {k: v for k, v in t["files"].items() if k != "README.txt"},
                          "test_files": tests, "expected_checks": count,
                          "image": "python:3.12-slim" if python else "node:22-slim",
                          "command": ["python", "-I", "-B", "_benchkit_runner.py"] if python else
                                     ["node", "--test", "--test-reporter=tap", "tests.js"],
                          "result_format": "marker" if python else "tap"})
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Tasks must be a nonempty JSON array")
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Each task must be an object")
        for key in ("id", "instructions", "image", "result_format"):
            if not isinstance(task.get(key), str) or not task[key]:
                raise ValueError(f"Task requires nonempty {key}")
        if task["id"] in seen:
            raise ValueError("Task IDs must be unique")
        seen.add(task["id"])
        if task["image"].startswith("-") or task["result_format"] not in ("marker", "tap"):
            raise ValueError("Invalid task image or result_format")
        if type(task.get("expected_checks")) is not int or task["expected_checks"] <= 0:
            raise ValueError("expected_checks must be a positive integer")
        for key in ("source_files", "test_files"):
            files = task.get(key)
            if not isinstance(files, dict) or not files or not all(isinstance(v, str) for v in files.values()):
                raise ValueError(f"{key} must be a nonempty path-to-text object")
            for name in files:
                safe_path(Path.cwd(), name)
                if str(PurePosixPath(name)) != name:
                    raise ValueError("Use canonical relative task paths without ./ or repeated slashes")
        if set(task["source_files"]) & set(task["test_files"]):
            raise ValueError("Source files and test files must not overlap")
        all_paths = [str(PurePosixPath(p)) for p in [*task["source_files"], *task["test_files"]]]
        if len(set(all_paths)) != len(all_paths):
            raise ValueError("Task paths must be unique after normalization")
        for p in all_paths:
            if any(q != p and q.startswith(p + "/") for q in all_paths):
                raise ValueError("A task path cannot also be a directory")
        cmd = task.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
            raise ValueError("command must be an argv array, never a shell string")
    return tasks


class DockerSandbox:
    def preflight(self, tasks):
        try:
            info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True,
                                  capture_output=True, timeout=15)
            if not info.stdout.strip():
                raise RuntimeError("Docker daemon is not responding. Start Docker before running coding tasks")
            for image in sorted({t["image"] for t in tasks}):
                subprocess.run(["docker", "image", "inspect", image], check=True,
                               capture_output=True, timeout=15)
        except FileNotFoundError:
            raise RuntimeError("Coding requires Docker; install/start it and pull the task images") from None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise RuntimeError("Docker is unavailable or a task image is missing. Start Docker and pull the configured images") from None

    def run(self, directory, task, timeout):
        name = "llm-benchkit-" + uuid.uuid4().hex
        mount = str(directory.resolve())
        if "," in mount:
            raise ValueError("Docker bind paths cannot contain commas; choose a different temp directory")
        cmd = ["docker", "run", "--rm", "--pull", "never", "--name", name,
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "64",
               "--memory", "512m", "--cpus", "1", "--user", "65534:65534",
               "--mount", f"type=bind,source={mount},target=/workspace,readonly",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--workdir", "/workspace",
               task["image"], *task["command"]]
        started = time.perf_counter()
        chunks = collections.deque(maxlen=8)
        total = 0
        exceeded = threading.Event()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        def collect():
            nonlocal total
            while True:
                block = proc.stdout.read(4096)
                if not block:
                    break
                chunks.append(block)
                total += len(block)
                if total > 1024 * 1024:
                    exceeded.set()
                    proc.terminate()
                    break

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        timed_out = False
        try:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            if proc.poll() is None:
                proc.kill()
            # Kill the named container, not just the Docker CLI process.
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                pass
            proc.wait(timeout=10)
            reader.join(timeout=5)
            proc.stdout.close()
        output = b"".join(chunks).decode("utf-8", errors="replace")[-24000:]
        infra = proc.returncode in (125, 126, 127)
        checks = 0
        if task["result_format"] == "marker":
            matches = re.findall(r"^BENCHKIT_RESULT=(.+)$", output, re.MULTILINE)
            if matches:
                try:
                    result = json.loads(matches[-1])
                    if result["total"] == task["expected_checks"] and type(result["passed"]) is int:
                        checks = max(0, min(result["passed"], task["expected_checks"]))
                except (ValueError, TypeError, KeyError):
                    pass
        else:
            n = re.search(r"^# tests (\d+)$", output, re.MULTILINE)
            p = re.search(r"^# pass (\d+)$", output, re.MULTILINE)
            if n and p and int(n[1]) == task["expected_checks"]:
                checks = min(int(p[1]), task["expected_checks"])
        passed = proc.returncode == 0 and checks == task["expected_checks"] and not timed_out and not exceeded.is_set()
        return {"status": "error" if infra else "completed", "passed": passed,
                "checks_passed": checks, "checks_total": task["expected_checks"],
                "returncode": proc.returncode, "timed_out": timed_out,
                "output_limit_exceeded": exceeded.is_set(), "output": output,
                "seconds": time.perf_counter() - started}


def coding_task(provider, task, settings, sandbox=None):
    sandbox = sandbox or DockerSandbox()
    started = time.perf_counter()
    transcript = []
    errors = []
    writes = 0
    with tempfile.TemporaryDirectory(prefix="llm-benchkit-") as temp:
        directory = Path(temp)
        directory.chmod(0o755)
        for name, text in {**task["source_files"], **task["test_files"]}.items():
            path = safe_path(directory, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            path.chmod(0o644)
        baseline = sandbox.run(directory, task, settings["test_timeout_seconds"])
        if baseline["status"] == "error" or baseline["timed_out"] or baseline["passed"]:
            return {"id": task["id"], "status": "error", "error": "Invalid fixture baseline or test infrastructure failure",
                    "baseline": baseline, "transcript": transcript}
        files = json.dumps(task["source_files"], ensure_ascii=False)
        messages = [{"role": "system", "content": (
            "You are a coding agent. Use write_file to fix the supplied source files and run_tests to verify. "
            "Tests are read-only. Only listed source files can be edited. Keep explanations brief; output complete files.")},
            {"role": "user", "content": task["instructions"] + "\nSource files: " + files +
             "\nRead-only test paths: " + ", ".join(task["test_files"])}]
        available = {**task["source_files"], **task["test_files"]}
        for _ in range(settings["max_turns"]):
            try:
                message, usage = provider.chat(messages, TOOLS, settings["output_tokens"])
            except Exception as e:
                errors.append(provider.http.redact(str(e)))
                break
            messages.append(message)
            transcript.append({"assistant": message, "usage": usage})
            calls = message.get("tool_calls") or []
            if not calls:
                break
            if len(calls) > 32:
                errors.append("More than 32 tools requested in a single turn")
                break
            passed = False
            for call in calls:
                fn = call.get("function", {}).get("name", "")
                try:
                    args = json.loads(call["function"]["arguments"])
                    if not isinstance(args, dict):
                        raise ValueError("Tool arguments must be an object")
                    if fn in ("read_file", "write_file"):
                        name = args["path"]
                        path = safe_path(directory, name)
                        name = str(PurePosixPath(name))
                        if name not in available:
                            raise ValueError("Unknown file path")
                        if fn == "read_file":
                            out = {"content": path.read_text(encoding="utf-8")}
                        else:
                            if name not in task["source_files"]:
                                raise ValueError("Tests are read-only")
                            content = args["content"]
                            if not isinstance(content, str) or len(content) > 100000:
                                raise ValueError("Source content must be text under 100,000 characters")
                            path.write_text(content, encoding="utf-8")
                            writes += 1
                            out = {"ok": True}
                    elif fn == "search_code":
                        query = args["query"]
                        if not isinstance(query, str):
                            raise ValueError("query must be text")
                        out = {"matches": [name for name in available if query in safe_path(directory, name).read_text(encoding="utf-8")]}
                    elif fn == "run_tests":
                        out = sandbox.run(directory, task, settings["test_timeout_seconds"])
                        passed = out["passed"] and writes > 0
                    else:
                        raise ValueError("Unknown tool")
                except (ValueError, TypeError, KeyError, OSError) as e:
                    out = {"error": str(e)}
                messages.append({"role": "tool", "name": fn, "tool_call_id": call["id"], "content": json.dumps(out)})
                transcript.append({"tool": fn, "result": out})
            if passed:
                break
        final = sandbox.run(directory, task, settings["test_timeout_seconds"])
        edited = {name: safe_path(directory, name).read_text(encoding="utf-8") for name in task["source_files"]}
    return {"id": task["id"], "status": "error" if errors or final["status"] == "error" else "completed",
            "passed": final["passed"] and writes > 0, "checks_passed": final["checks_passed"],
            "checks_total": task["expected_checks"], "writes": writes, "errors": errors,
            "seconds": time.perf_counter() - started, "baseline": baseline, "final": final,
            "edited_files": edited, "transcript": transcript}
