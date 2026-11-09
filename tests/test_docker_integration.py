"""Opt-in real-container checks; never execute generated/model code on the host."""

import os
import tempfile
import unittest
from pathlib import Path

from llm_benchkit.coding import DockerSandbox, load_tasks, safe_path


@unittest.skipUnless(os.environ.get("BENCHKIT_DOCKER_TEST") == "1", "Set BENCHKIT_DOCKER_TEST=1 for real Docker checks")
class DockerIntegration(unittest.TestCase):
    def test_broken_fixtures_and_reference_controls(self):
        tasks = load_tasks()
        sandbox = DockerSandbox()
        sandbox.preflight(tasks)
        reference = Path(__file__).parent / "reference"
        for task in tasks:
            with self.subTest(task=task["id"]), tempfile.TemporaryDirectory(prefix="llm-benchkit-test-") as d:
                root = Path(d)
                root.chmod(0o755)
                for name, content in {**task["source_files"], **task["test_files"]}.items():
                    path = safe_path(root, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                    path.chmod(0o644)
                baseline = sandbox.run(root, task, 20)
                self.assertEqual(baseline["status"], "completed", baseline)
                self.assertFalse(baseline["passed"], baseline)
                for name in task["source_files"]:
                    safe_path(root, name).write_text((reference / task["id"] / name).read_text(encoding="utf-8"), encoding="utf-8")
                result = sandbox.run(root, task, 20)
                self.assertTrue(result["passed"], result)
                self.assertEqual(result["checks_passed"], task["expected_checks"])
