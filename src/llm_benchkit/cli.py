import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .coding import load_tasks
from .config import load_config
from .report import write_reports
from .runner import merge, run, save


def main(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark text LLM APIs and generate reproducible reports")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a starter config")
    init.add_argument("--output", default="benchkit.json")
    init.add_argument("--provider", choices=["openai", "ollama", "llamacpp", "anthropic"], default="ollama")
    init.add_argument("--model", required=True)
    init.add_argument("--base-url")
    validate = commands.add_parser("validate", help="Validate config/tasks without calling APIs")
    validate.add_argument("--config", required=True)
    bench = commands.add_parser("run", help="Run sequential trials; hosted endpoints may charge per request")
    bench.add_argument("--config", required=True)
    bench.add_argument("--output", required=True)
    bench.add_argument("--suite", choices=["speed", "coding", "all"], default="speed")
    bench.add_argument("--model", action="append", help="Select a model ID; repeat to select several")
    report = commands.add_parser("report", help="Rebuild reports offline from raw JSON")
    report.add_argument("results")
    report.add_argument("--output", required=True)
    combine = commands.add_parser("merge", help="Combine separate model runs with unique IDs")
    combine.add_argument("results", nargs="+")
    combine.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            defaults = {"ollama": "http://127.0.0.1:11434", "llamacpp": "http://127.0.0.1:8080",
                        "openai": "http://127.0.0.1:8000/v1", "anthropic": "https://api.anthropic.com/v1"}
            model = {"id": "my-model", "provider": args.provider, "base_url": args.base_url or defaults[args.provider],
                     "model": args.model, "metadata": {"quantization": "set-me", "engine_version": "set-me"}}
            if args.provider == "anthropic":
                model["api_key_env"] = "ANTHROPIC_API_KEY"
            data = {"models": [model], "benchmark": {"input_chars": [1024, 8192], "input_tokens": [1024, 4096],
                                                     "output_tokens": 128, "repeats": 3, "warmup": 1},
                    "environment": {"hardware": "set-me", "context_capacity": "set-me"}}
            with Path(args.output).open("x", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"Created {args.output}")
        elif args.command == "validate":
            config = load_config(args.config)
            tasks = load_tasks(config.get("tasks_file"))
            print(f"Valid config: {len(config['models'])} models, {len(tasks)} coding tasks")
        elif args.command == "run":
            data = run(load_config(args.config), args.output, args.suite, args.model)
            print(f"{data['status']}: {Path(args.output).resolve() / 'report.md'}")
            return 0 if data["status"] == "completed" else 130 if data["status"] == "interrupted" else 1
        elif args.command == "report":
            data = json.loads(Path(args.results).read_text(encoding="utf-8"))
            write_reports(data, args.output)
            print(f"Reports saved to {Path(args.output).resolve()}")
        else:
            output = Path(args.output)
            if output.exists() and any(output.iterdir()):
                raise ValueError("Merge output directory must be empty")
            data = merge(args.results)
            output.mkdir(parents=True, exist_ok=True)
            save(data, output)
            write_reports(data, output)
            print(f"Merged report: {output.resolve() / 'report.md'}")
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0
