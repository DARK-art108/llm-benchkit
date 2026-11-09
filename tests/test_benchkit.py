import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from llm_benchkit.cli import main
from llm_benchkit.coding import DockerSandbox, coding_task, load_tasks, safe_path
from llm_benchkit.config import load_config
from llm_benchkit.providers import Provider
from llm_benchkit.report import build_report, write_reports
from llm_benchkit.runner import merge, run


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, body, dict(self.headers)))
        if body.get("model") == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/collect")
            self.end_headers()
            return
        if body.get("model") == "broken":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"test-secret-key"}')
            return
        if self.path == "/tokenize":
            return self.reply({"tokens": list(range(len(body["content"]) // 4))})
        if not body.get("stream"):
            if self.path == "/messages":
                return self.reply({"content": [{"type": "tool_use", "id": "use1", "name": "read_file", "input": {"path": "a.py"}}], "usage": {"input_tokens": 5}})
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]}
            if self.path == "/api/chat":
                msg["tool_calls"][0]["function"]["arguments"] = {"path": "a.py"}
                return self.reply({"message": msg})
            return self.reply({"choices": [{"message": msg}], "usage": {"prompt_tokens": 5}})
        if self.path == "/completion":
            events = [{"content": "one"}, {"content": "two"}, {"stop": True, "timings": {
                "prompt_n": len(body["prompt"]), "predicted_n": body["n_predict"],
                "prompt_per_second": 100, "predicted_per_second": 25}}]
        elif self.path == "/api/chat":
            events = [{"message": {"content": "one"}, "done": False}, {"message": {"content": "two"}, "done": True,
                       "prompt_eval_count": 20, "prompt_eval_cached_count": 3, "eval_count": 4,
                       "prompt_eval_duration": 1000000000, "eval_duration": 2000000000}]
        elif self.path == "/messages":
            events = [{"type": "message_start", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7}}},
                      {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}},
                      {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "yes"}},
                      {"type": "message_delta", "usage": {"output_tokens": 3}, "delta": {"stop_reason": "end_turn"}},
                      {"type": "message_stop"}]
        else:
            events = [{"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
                      {"choices": [{"delta": {"content": "one"}, "finish_reason": None}]},
                      {"choices": [{"delta": {"content": "two"}, "finish_reason": "stop"}]},
                      {"choices": [], "usage": {"prompt_tokens": 25, "completion_tokens": 3,
                                                "prompt_tokens_details": {"cached_tokens": 4}}}]
        if body.get("model") == "truncated":
            events = events[:2]
        if body.get("model") == "stream-error":
            events = [{"error": {"message": "test-secret-key"}}]
        ndjson = self.path == "/api/chat"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson" if ndjson else "text/event-stream")
        self.end_headers()
        for event in events:
            self.wfile.write((("" if ndjson else "data: ") + json.dumps(event) + ("\n" if ndjson else "\n\n")).encode())
            self.wfile.flush()
        if not ndjson:
            self.wfile.write(b"data: [DONE]\n\n")

    def reply(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class APIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def model(self, kind="openai", name="test"):
        return {"id": kind, "provider": kind, "base_url": self.url, "model": name}

    def test_streamed_provider_metrics(self):
        for kind in ("openai", "llamacpp", "ollama", "anthropic"):
            with self.subTest(kind=kind):
                result = Provider(self.model(kind)).speed(256, 8, "fixed-nonce")
                self.assertEqual(result["status"], "ok")
                self.assertGreaterEqual(result["first_visible_seconds"], result["ttft_seconds"])
                if kind == "openai":
                    self.assertIsNone(result["engine_decode_tps"])
                    self.assertIsNone(result["engine_prefill_tps"])
                    self.assertEqual(result["cached_prompt_tokens"], 4)
                elif kind == "llamacpp":
                    self.assertEqual(result["prompt_tokens"], 256)
                    self.assertEqual(result["completion_tokens"], 8)
                    self.assertEqual(result["engine_decode_tps"], 25)
                elif kind == "ollama":
                    self.assertEqual(result["engine_decode_tps"], 2)
                    self.assertEqual(result["engine_prefill_tps"], 20)
                else:
                    self.assertEqual(result["prompt_tokens"], 22)
                    self.assertEqual(result["cached_prompt_tokens"], 5)

    def test_nonstreaming_tools_all_providers(self):
        for kind in ("openai", "llamacpp", "ollama", "anthropic"):
            with self.subTest(kind=kind):
                message, _ = Provider(self.model(kind)).chat([{"role": "user", "content": "read a.py"}], [], 64)
                self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"path": "a.py"})

    def test_configurable_compatible_output_field(self):
        model = self.model()
        model["token_limit_field"] = "max_completion_tokens"
        path, body = Provider(model)._body([{"role": "user", "content": "hi"}], 512, True)
        self.assertEqual(body["max_completion_tokens"], 512)
        self.assertNotIn("max_tokens", body)

    def test_anthropic_tool_results_grouped_and_thinking_preserved(self):
        provider = Provider(self.model("anthropic"))
        blocks = [{"type": "thinking", "thinking": "hmm", "signature": "signed"},
                  {"type": "tool_use", "id": "a", "name": "run_tests", "input": {}}]
        _, body = provider._body([
            {"role": "system", "content": "sys"}, {"role": "user", "content": "fix"},
            {"role": "assistant", "_native_blocks": blocks},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "tool", "tool_call_id": "b", "content": "ok"}], 64, False)
        self.assertEqual(body["messages"][1]["content"], blocks)
        self.assertEqual(len(body["messages"][2]["content"]), 2)
        self.assertEqual(body["system"], "sys")

    def test_incomplete_stream_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            Provider(self.model(name="truncated")).speed(256, 8, "nonce")

    def test_api_and_stream_errors_redact_keys(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "test-secret-key"}):
            for name in ("broken", "stream-error"):
                model = self.model(name=name)
                model["api_key_env"] = "TEST_API_KEY"
                with self.assertRaises(RuntimeError) as ctx:
                    Provider(model).speed(256, 8, "nonce")
                self.assertNotIn("test-secret-key", str(ctx.exception))

    def test_redirect_is_not_followed(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            Provider(self.model(name="redirect")).speed(128, 8, "nonce")

    def test_missing_docker_preserves_speed_and_marks_coding_incomplete(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"models": [self.model()], "benchmark": {"warmup": 0, "repeats": 1, "input_chars": [128]}}))
            with patch("llm_benchkit.runner.DockerSandbox.preflight", side_effect=RuntimeError("Docker unavailable")):
                data = run(load_config(path), Path(d) / "out", suite="all")
            self.assertEqual(data["status"], "partial")
            self.assertEqual(data["models"][0]["speed"][0]["status"], "ok")
            self.assertEqual(data["models"][0]["coding"], [])
            report = build_report(data)
            self.assertIn("0/3", report)
            self.assertNotIn("Observed coding leaders", report)

    def test_cli_end_to_end_and_offline_report(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            root = Path(d)
            config = root / "config.json"
            config.write_text(json.dumps({"models": [self.model()], "benchmark": {
                "warmup": 0, "repeats": 2, "input_chars": [128], "output_tokens": 8}}))
            self.assertEqual(main(["run", "--config", str(config), "--output", str(root / "run")]), 0)
            saved = json.loads((root / "run/results.json").read_text())
            self.assertEqual(len(saved["models"][0]["speed"]), 2)
            self.assertEqual(saved["status"], "completed")
            for file in ("report.md", "report.html", "speed.csv", "coding.csv"):
                self.assertTrue((root / "run" / file).exists())
            self.assertEqual(main(["report", str(root / "run/results.json"), "--output", str(root / "rebuilt")]), 0)
            self.assertEqual((root / "run/report.md").read_text(), (root / "rebuilt/report.md").read_text())

    def test_failed_model_retained_and_next_model_runs(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            path = Path(d) / "config.json"
            models = [self.model(name="broken"), self.model(name="test")]
            models[1]["id"] = "working"
            path.write_text(json.dumps({"models": models, "benchmark": {"warmup": 0, "repeats": 1, "input_chars": [128]}}))
            result = run(load_config(path), Path(d) / "run")
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["models"][0]["speed"][0]["status"], "error")
            self.assertEqual(result["models"][1]["speed"][0]["status"], "ok")


class ConfigAndReport(unittest.TestCase):
    def config(self, mutation):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            data = {"models": [{"id": "m", "provider": "ollama", "base_url": "http://localhost:11434", "model": "m"}]}
            mutation(data)
            path.write_text(json.dumps(data))
            return load_config(path)

    def test_config_rejects_invalid_inputs(self):
        mutations = [lambda d: d.update(benchmark={"repeats": 0}),
                     lambda d: d.update(benchmark={"repeats": True}),
                     lambda d: d.update(benchmark={"timeout_seconds": float("nan")}),
                     lambda d: d["models"][0].update(base_url="http://user:secret@localhost"),
                     lambda d: d["models"][0].update(request={"api_key": "secret"}),
                     lambda d: d["models"][0].update(request={"max_tokens": 0}),
                     lambda d: d["models"].append(copy.deepcopy(d["models"][0])),
                     lambda d: d["models"][0].update(release_date="made-up"),
                     lambda d: d.update(benchmark={"repeat": 2})]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.config(mutation)

    def test_task_path_safety(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("../secret", "/etc/passwd", "C:\\Windows", "nested/../../x"):
                with self.assertRaises(ValueError):
                    safe_path(root, name)
            try:
                (root / "link").symlink_to(root.parent, target_is_directory=True)
            except OSError:
                pass  # Windows may not grant symlink privileges; traversal checks still run.
            else:
                with self.assertRaises(ValueError):
                    safe_path(root, "link/secret")
        self.assertEqual(sum(t["expected_checks"] for t in load_tasks()), 27)

    def test_html_and_csv_escape_untrusted_output(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"run_id": "<script>alert(1)</script>", "models": [{"id": "=SUM(1)", "provider": "openai", "speed": [
                {"input_size": 128, "input_unit": "characters", "status": "ok", "ttft_seconds": 1}]}]}
            write_reports(data, d)
            page = (Path(d) / "report.html").read_text()
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn("'=SUM(1)", (Path(d) / "speed.csv").read_text())

    def test_merge_rejects_different_tasks_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [Path(d) / "a.json", Path(d) / "b.json"]
            data = {"schema_version": 1, "suite": "all", "tasks_sha256": "a", "models": [{"id": "m"}]}
            for p in paths:
                p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unique"):
                merge(paths)
            data["tasks_sha256"] = "b"
            paths[1].write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                merge(paths)

    def test_merge_preserves_environments_and_settings(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name in ("a", "b"):
                path = Path(d) / (name + ".json")
                path.write_text(json.dumps({"schema_version": 1, "suite": "speed", "tasks_sha256": "empty",
                    "status": "completed", "environment": {"hardware": name}, "config": {"profile": name},
                    "models": [{"id": name, "provider": "ollama", "speed": []}]}))
                paths.append(path)
            result = merge(paths)
            self.assertEqual([m["id"] for m in result["models"]], ["a", "b"])
            self.assertEqual(result["source_runs"][1]["config"]["profile"], "b")
            self.assertEqual(result["environment"]["merged_runs"][0]["hardware"], "a")


class AgentFlow(unittest.TestCase):
    def test_read_only_tests_cannot_be_edited_and_final_state_is_scored(self):
        task = load_tasks()[0]
        outcomes = []

        class FakeSandbox:
            def run(self, directory, task, timeout):
                content = (directory / "cache.py").read_text()
                self_test = (directory / "tests.py").read_text()
                outcomes.append(self_test)
                ok = content == "fixed"
                return {"status": "completed", "passed": ok, "checks_passed": 8 if ok else 0,
                        "checks_total": 8, "timed_out": False, "output": "ok"}

        class FakeProvider:
            http = type("HTTP", (), {"redact": staticmethod(lambda text: text)})()
            called = False

            def chat(self, messages, tools, limit):
                if self.called:
                    return {"role": "assistant", "content": "done"}, {}
                self.called = True
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"id": str(i), "function": {"name": "write_file", "arguments": json.dumps({"path": p, "content": c})}}
                    for i, (p, c) in enumerate([("tests.py", "tampered"), ("../escape.py", "bad"), ("cache.py", "fixed")])]}, {}

        result = coding_task(FakeProvider(), task, {"test_timeout_seconds": 1, "output_tokens": 64, "max_turns": 2}, FakeSandbox())
        self.assertTrue(result["passed"])
        self.assertEqual(result["writes"], 1)
        self.assertTrue(all(content == task["test_files"]["tests.py"] for content in outcomes))
        self.assertEqual(sum("error" in t.get("result", {}) for t in result["transcript"]), 2)

    def test_docker_flags_and_cleanup(self):
        calls = []

        class Process:
            returncode = 0
            stdout = io.BytesIO(b'BENCHKIT_RESULT={"total":8,"passed":8}\n')

            def wait(self, timeout=None):
                return 0

            def poll(self):
                return self.returncode

        def popen(cmd, **kwargs):
            calls.append(cmd)
            return Process()

        with tempfile.TemporaryDirectory() as d, patch("llm_benchkit.coding.subprocess.Popen", side_effect=popen), patch("llm_benchkit.coding.subprocess.run") as cleanup:
            result = DockerSandbox().run(Path(d), load_tasks()[0], 10)
            self.assertTrue(result["passed"])
            self.assertIn("none", calls[0])
            self.assertIn("--read-only", calls[0])
            self.assertIn("--cap-drop", calls[0])
            self.assertIn("readonly", " ".join(calls[0]))
            self.assertEqual(cleanup.call_args.args[0][:3], ["docker", "rm", "-f"])

    def test_docker_timeout_cleans_container_not_only_client(self):
        class Process:
            stdout = io.BytesIO(b"partial output")
            returncode = None

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("docker", timeout)
                return self.returncode

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

        with tempfile.TemporaryDirectory() as d, patch("llm_benchkit.coding.subprocess.Popen", return_value=Process()), patch("llm_benchkit.coding.subprocess.run") as cleanup:
            result = DockerSandbox().run(Path(d), load_tasks()[0], 1)
            self.assertTrue(result["timed_out"])
            self.assertFalse(result["passed"])
            self.assertEqual(cleanup.call_args.args[0][:3], ["docker", "rm", "-f"])


if __name__ == "__main__":
    unittest.main()
