"""Sequential benchmark execution with incremental evidence on failure."""

import datetime as dt
import hashlib
import json
import os
import platform
import uuid
from pathlib import Path

from . import __version__
from .coding import DockerSandbox, coding_task, load_tasks
from .config import snapshot
from .providers import Provider
from .report import write_reports


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def environment(notes):
    ram = None
    try:
        ram = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        pass
    return {"os": platform.system(), "os_release": platform.release(), "architecture": platform.machine(),
            "cpu": platform.processor(), "logical_cpu_count": os.cpu_count(), "ram_bytes": ram,
            "python": platform.python_version(), "notes": notes}


def save(data, directory):
    directory = Path(directory)
    temp = directory / "results.json.tmp"
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(directory / "results.json")


def run(config, directory, suite="speed", selected=None):
    models = [m for m in config["models"] if not selected or m["id"] in selected]
    if selected and set(selected) - {m["id"] for m in models}:
        raise ValueError("Selected model ID was not found in config")
    # A raw completion endpoint serves one loaded model; its model field does not switch weights.
    llama_urls = [m["base_url"] for m in models if m["provider"] == "llamacpp"]
    if len(llama_urls) != len(set(llama_urls)):
        raise ValueError("Use a distinct running llama.cpp endpoint for each model, or select one with --model and merge separate runs")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("Output directory must be empty; choose a new run directory")
    tasks = load_tasks(config.get("tasks_file")) if suite in ("all", "coding") else []
    data = {"schema_version": 1, "benchkit_version": __version__, "run_id": uuid.uuid4().hex,
            "started_at": now(), "status": "running", "suite": suite, "config": snapshot(config),
            "environment": environment(config.get("environment", {})), "models": [],
            "tasks": tasks,
            "tasks_sha256": hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()}
    save(data, directory)
    sandbox = DockerSandbox()
    coding_error = None
    if tasks:
        try:
            sandbox.preflight(tasks)
        except RuntimeError as e:
            coding_error = str(e)
    try:
        b = config["benchmark"]
        for model in models:
            record = {**model, "speed": [], "coding": [], "errors": [], "coding_tasks_expected": len(tasks)}
            data["models"].append(record)
            print(f"Benchmarking {model['id']} ({model['provider']})", flush=True)
            try:
                provider = Provider(model, b["timeout_seconds"])
                if suite in ("speed", "all"):
                    sizes = b["input_tokens"] if model["provider"] == "llamacpp" else b["input_chars"]
                    for n in range(b["warmup"]):
                        provider.speed(min(sizes[0], 128), min(b["output_tokens"], 16), uuid.uuid4().hex[:16])
                    for size in sizes:
                        for rep in range(b["repeats"]):
                            try:
                                trial = provider.speed(size, b["output_tokens"], uuid.uuid4().hex[:16])
                            except Exception as e:
                                trial = {"status": "error", "input_size": size,
                                         "input_unit": "tokens" if model["provider"] == "llamacpp" else "characters",
                                         "error": provider.http.redact(str(e))}
                            trial["repeat"] = rep + 1
                            record["speed"].append(trial)
                            save(data, directory)
                            print(f"  speed {size} repeat {rep+1}: {trial['status']}", flush=True)
                if tasks:
                    if coding_error:
                        record["errors"].append(coding_error)
                    else:
                        for task in tasks:
                            outcome = coding_task(provider, task, config["coding"], sandbox)
                            record["coding"].append(outcome)
                            save(data, directory)
                            print(f"  coding {task['id']}: {outcome['status']} pass={outcome.get('passed', False)}", flush=True)
            except Exception as e:
                record["errors"].append(str(e))
            save(data, directory)
        any_error = any(m["errors"] or any(t["status"] == "error" for t in m["speed"] + m["coding"]) for m in data["models"])
        data["status"] = "partial" if any_error else "completed"
    except KeyboardInterrupt:
        data["status"] = "interrupted"
    finally:
        data["finished_at"] = now()
        save(data, directory)
        write_reports(data, directory)
    return data


def merge(paths):
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    first = runs[0]
    if any(r.get("schema_version") != 1 for r in runs):
        raise ValueError("Only schema_version 1 reports can be merged")
    # Never silently rank different task suites as the same coding workload.
    if len({r.get("tasks_sha256") for r in runs}) > 1 or len({r["suite"] for r in runs}) > 1:
        raise ValueError("Merge requires matching suite and task fingerprint")
    models = [m for r in runs for m in r["models"]]
    if len({m["id"] for m in models}) != len(models):
        raise ValueError("Merged model IDs must be unique; choose distinct IDs in each run")
    return {"schema_version": 1, "benchkit_version": __version__, "run_id": uuid.uuid4().hex,
            "status": "completed" if all(r["status"] == "completed" for r in runs) else "partial",
            "suite": first["suite"], "environment": {"merged_runs": [r["environment"] for r in runs]},
            "models": models, "tasks": first.get("tasks", []), "tasks_sha256": first.get("tasks_sha256"),
            "source_runs": runs, "finished_at": now()}
