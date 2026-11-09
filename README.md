# LLM BenchKit

Benchmark text LLM speed and tool-based code editing, then generate Markdown, HTML, CSV and JSON reports. Bring your own model server or hosted API; no model names, Mac paths, weights or API keys are built into the runner.

The project grew out of a three-model coding/speed comparison on an M2 Pro. The reusable runner is a new implementation; the [original measurements](docs/original-m2-pro-results.md) came from the earlier local harness.

## Example: measured results on an Apple M2 Pro

Measured **November 9, 2026** on an **M2 Pro (10 CPU / 16 GPU cores), 16 GB unified memory**, using llama.cpp Metal and Q4_K_M models. Speed figures are medians of two warm-engine runs: **4,096 fresh input tokens, 128 output tokens, 16K context capacity**, with prompt reuse disabled.

| Model | Base-model release | Prefill tok/s | Decode tok/s | First output | Coding checks | Full coding tasks |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| LFM3 1.7B | 2026-10-27 | **1,245.0** | **101.1** | **3.29 s** | 12/27 | 0/3 |
| Qwen3.5 4B | 2026-03-02 | 457.7 | 36.4 | 8.96 s | **24/27** | **2/3** |
| Spark X2.6 4B | 2026-10-21 | 290.1 | 31.9 | 14.25 s | 17/27 | 1/3 |

Qwen gave the best coding results of these tested configurations; LFM3 generated plain output fastest. These are **three small synthetic coding projects**, not SWE-bench. Coding used a 512-token reasoning budget with 8K context for cache/money and 16K for concurrency. One long Qwen tool response slowed to **6.47 tok/s**; the short trials do not establish stable heavy-use performance. No hosted Claude/GPT model was tested.

The [example results folder](examples/results/apple-m2-pro-16gb/README.md) contains the [full report](examples/results/apple-m2-pro-16gb/report.md), [CSV measurements](examples/results/apple-m2-pro-16gb/measurements.csv), summaries, methodology, raw timing records and coding transcripts. The additional MLX check is documented separately because its coding settings differed. These historical measurements came from the earlier Mac-specific harness, not the portable CLI in this repository. Personal filesystem paths in published evidence have been anonymized; measurements are unchanged.

## What it measures

- Backend-reported prefill/decode tokens per second, where available.
- Time to first output chunk, time to first visible text, total request time and gaps between chunks.
- Client output throughput, actual token usage, cached tokens and output lengths when supplied by the API.
- Coding edits using `read_file`, `write_file`, `search_code` and `run_tests`: full tasks passed, individual checks, duration, transcripts and edited files.
- Medians and min/max over repeated speed trials, with failures retained instead of silently discarded.

This is a configurable benchmark harness, not a claim to support every model protocol or to replace SWE-bench. It tests **text models served through the adapters below**. Vision, audio, embedding-only models, the OpenAI Responses protocol and direct in-process PyTorch/Transformers inference are outside this release. Serve those text models through a supported API or add an adapter.

## Requirements

- Python **3.11+** on macOS, Linux or Windows. No Python runtime dependencies.
- A running model API, reachable from the machine running BenchKit.
- **Coding suite only:** a running Docker daemon and the configured container images.

BenchKit does not download model weights, start/stop your model server, change your system settings or provide free hosted inference. Hosted API trials, including warmups and coding repair turns, may incur charges.

## Quick start

After cloning this repository, open its folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Set the model to an exact tag already installed in Ollama.
llm-benchkit init --provider ollama --model YOUR_MODEL_TAG --output config.local.json
llm-benchkit validate --config config.local.json
llm-benchkit run --config config.local.json --suite speed --output results/first-run
```

On Windows, use `py -3` to create the environment and `.venv\Scripts\Activate.ps1` to activate it. The CLI and configuration are the same.

Open `results/first-run/report.html` in a browser, or read `report.md`. `results.json` retains the underlying evidence; `speed.csv` and `coding.csv` are spreadsheet-friendly summaries. Choose a new, empty output directory for each run.

You can also run `python -m llm_benchkit` in place of `llm-benchkit`.

## Model servers and providers

| Adapter (`provider`) | `base_url` example | Speed endpoint | Coding endpoint |
| --- | --- | --- | --- |
| `llamacpp` | `http://127.0.0.1:8080` | `/tokenize` + `/completion` | `/v1/chat/completions` |
| `ollama` | `http://127.0.0.1:11434` | `/api/chat`, streaming NDJSON | `/api/chat` |
| `openai` | `http://127.0.0.1:8000/v1` | `/chat/completions`, streaming SSE | `/chat/completions` |
| `anthropic` | `https://api.anthropic.com/v1` | `/messages`, streaming SSE | `/messages` |

The `openai` adapter is for compatible Chat Completions APIs, including suitably configured vLLM, LM Studio, MLX servers and hosted gateways. Compatibility depends on the server/model: streaming, usage and structured function calls must be supported for the corresponding suite. Unsupported requests are recorded as errors, not emulated or retried with changed settings.

Use the **root URL** for llama.cpp and Ollama; include `/v1` for OpenAI-compatible and Anthropic URLs. Do not include the final endpoint path. Configure API keys as environment variables using `api_key_env`; keys are never read from JSON. The configured key value is redacted from request errors. Do not put other secrets in request options or metadata.

For llama.cpp, start your installed `llama-server` with your model and suitable flags, for example:

```bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8080 -c 8192 --jinja
llm-benchkit run --config examples/llamacpp.json --suite speed --output results/gguf-run
```

Edit the example's alias/metadata to match the server. Flags and model tool templates depend on your installed engine; consult [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server). The native speed API benchmarks the weights currently loaded at that endpoint: its `model` field does **not** select a different GGUF file. BenchKit rejects multiple llama.cpp configs pointing at the same URL in one run. For limited-memory machines, load each model separately, select it with `--model`, then merge the separate results.

For hosted APIs, copy and edit [examples/hosted.json](examples/hosted.json), select actual model IDs and set the named environment variables. `token_limit_field` supports `max_tokens` (default) or `max_completion_tokens` for the compatible adapter. Some models require a larger output budget for reasoning or reject sampling parameters; set supported native options explicitly. No automatic fallback changes the benchmark workload.

## Configuration

```json
{
  "models": [
    {
      "id": "model-a-q4",
      "provider": "openai",
      "base_url": "http://127.0.0.1:8000/v1",
      "model": "YOUR_SERVED_MODEL_ID",
      "request": {"temperature": 0.6, "top_p": 0.95},
      "metadata": {"quantization": "4-bit", "engine_version": "record-me"}
    }
  ],
  "benchmark": {
    "input_chars": [1024, 8192],
    "input_tokens": [1024, 4096],
    "output_tokens": 128,
    "repeats": 3,
    "warmup": 1,
    "timeout_seconds": 180
  },
  "coding": {"max_turns": 10, "output_tokens": 4096, "test_timeout_seconds": 10},
  "environment": {"hardware": "record CPU/GPU/RAM", "context_capacity": 8192}
}
```

- Every model needs a unique `id`, a provider, a base URL and the actual API `model` identifier.
- Add optional `release_date` in `YYYY-MM-DD` and `release_source` with an official URL. Dates are user-supplied and not automatically verified.
- `metadata` records quantization, model revision/checksum, runtime version, context capacity and other reproduction notes. These notes do not change the model server.
- `request` contains provider-native options, used for speed and coding. Ollama puts sampling/context options inside its nested `options` object; see [examples/ollama.json](examples/ollama.json). Coding output limits come from `coding.output_tokens`.
- BenchKit controls model, messages, tools, stream and output-limit fields. Do not place them in `request`. The llama.cpp **raw speed** profile additionally forces temperature 0, seed 123, no prompt reuse and `ignore_eos=true`; its coding profile uses your supplied sampling options.
- Warmups are excluded from speed summaries. `warmup: 0` includes cold behavior in the first measured request. A warmup is not proof the entire model is resident or thermally stable.
- Model request timeout is an overall streaming deadline; coding test timeout applies per container invocation. Max turns bounds API repair loops. There are no automatic HTTP retries, parallel benchmark requests or context-overflow retries.
- Synthetic prompts contain a fresh random identifier near the beginning. This reduces common-prefix reuse; it does not guarantee that a remote provider disables caching.

Examples: [Ollama](examples/ollama.json), [llama.cpp](examples/llamacpp.json), [hosted/Claude](examples/hosted.json).

## Coding benchmark

Pull the images once and ensure Docker is running:

```bash
docker pull python:3.12-slim
docker pull node:22-slim
llm-benchkit run --config config.local.json --suite all --output results/speed-and-code
# Or use --suite coding for coding only.
```

The built-in suite has three small projects and **27 checks**:

| Task | Language | Checks | Focus |
| --- | --- | --- | --- |
| TTL/LRU cache | Python | 8 | Expiry boundaries, recency, eviction, validation |
| Money and checkout | Python | 12 | Decimal rounding, discounts, multiple files, invalid inputs |
| Bounded async map | JavaScript | 7 | Concurrency limit, result order, rejection handling |

An unmodified fixture must fail before the model edits it. The model can inspect source and tests, edit only allowlisted source paths and request test runs. The final state is tested again. A complete task passes only when all expected checks pass after at least one source write. API/infrastructure errors have separate incomplete coverage and are excluded from evaluated task totals; ordinary wrong code, syntax errors and generated-code timeouts remain failed tasks.

Generated programs execute only in Docker: no network, read-only root and fixture mounts, unprivileged user, dropped capabilities, process/memory/CPU limits and bounded output. Only the temporary fixture is mounted; the Docker socket and host home directory are not mounted. Timeout cleanup removes the named container. The runner has **no host-execution fallback**. Treat Docker as a practical isolation layer, not a perfect defense against hostile code or benchmark gaming. Only use task images and task definitions you trust. Container runtime overhead is included in coding task time.

If Docker is missing/stopped or an image is missing, an `all` run can still produce its speed report, marks coding incomplete and exits nonzero. Nothing automatically pulls images or starts Docker.

### Add your own tasks

Set `"tasks_file": "my-tasks.json"` at the top level of your config. The path resolves relative to the config file. It replaces the built-in suite. See the complete [custom task example](examples/custom-tasks.json).

Each task defines:

- `id`, `instructions`, positive `expected_checks`.
- `source_files`: editable relative POSIX paths mapped to initial text.
- `test_files`: read-only relative paths mapped to tests/runner text. Paths cannot overlap, traverse directories or alias one another.
- `image`: an already-pulled Docker image. Pin an image digest for stricter reproducibility.
- `command`: an argv array executed inside the container, with `/workspace` as its working directory. Dependencies must already be in the image; containers have no network.
- `result_format`: `marker` or `tap`. Marker runners print `BENCHKIT_RESULT={"total":2,"passed":2}` on a line; TAP runners must emit Node-style `# tests N` and `# pass N` summaries. The process must also exit zero and report the expected count for a full pass. Incomplete test discovery gets no partial-check credit.

The exact tasks and their SHA-256 fingerprint are saved in `results.json`, alongside generated edits and transcripts. These artifacts can contain task data; review them before publishing. Reports/results are ignored by Git by default.

## Read the numbers correctly

**Prefill** processes input; **decode** generates output. Engine timings are available from native llama.cpp/Ollama endpoints when supplied. Generic hosted APIs generally do not expose true engine prefill/decode times; those cells stay **N/A**.

**Client output tok/s** is reported completion tokens divided by total request time. It includes input processing, network and queueing, and can include tokens spent on hidden reasoning. It is not relabeled as GPU decode speed. **First chunk** includes exposed reasoning; **first visible text** excludes it. Streaming chunks can contain multiple tokens, so chunk gaps do not measure individual-token latency.

The llama.cpp native mode uses exact token counts, a raw completion prompt and fixed output length. Other modes use a character-sized code prompt inside a chat template and may stop early. Different tokenizers mean equal characters are not equal tokens. Do not treat these as identical workloads or pool their rates into one ranking. Check actual prompt/output/cache counts and workload settings in the raw data. Ollama prompt timing reflects its reported evaluated prompt, which may omit cached context.

Only like-for-like coding suites should be ranked. Reports show a descriptive coding leader among fully evaluated configurations, based on full-task pass fraction then check pass fraction. That does not establish best daily-use quality or cloud-assistant equivalence. Three fixtures and short completions cannot establish all-day reliability, long-context performance or a universal leaderboard.

## Reports, separate runs and exit codes

```bash
# Select a configured model (repeat --model to select more).
llm-benchkit run --config config.local.json --model model-a --output results/a

# Rebuild reports without calling a model.
llm-benchkit report results/a/results.json --output results/a

# Compare models served at different times. IDs must be unique.
llm-benchkit merge results/a/results.json results/b/results.json --output results/comparison
```

Merge requires matching suite/task fingerprints and retains each source run's configuration and environment. It does not equalize different hardware, native/API workloads, sampling or runtime versions; account for those differences yourself.

`0` means infrastructure completed, **not** that every coding task passed. `1` means partial/infrastructure errors, `2` means invalid CLI/config/output, and `130` means interrupted. Results are saved after each speed trial and coding task; a handled interruption also writes the partial report. Existing run directories are never overwritten by `run` or `merge`.

## Development and verification

```bash
python -m pip install -e .
python -m unittest discover -s tests -v

# Optional real-container fixture/reference checks, after pulling both images:
BENCHKIT_DOCKER_TEST=1 python -m unittest discover -s tests -v
```

The ordinary tests use local HTTP fixtures to exercise all four stream/tool adapters, error redaction, exact-token workloads, the editing agent, Docker arguments/cleanup, config validation and the CLI/report pipeline. They do not call paid/live provider APIs. Docker integration tests validate the known-broken fixtures and hand-written passing controls. GitHub Actions is configured for Python 3.11/3.13 on Linux/macOS/Windows and a separate Linux Docker job; a configured workflow is not evidence that those remote jobs have already passed.

Protocol references: [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), [Ollama chat](https://docs.ollama.com/api/chat), [Claude streaming](https://platform.claude.com/docs/en/build-with-claude/streaming). Provider behavior can change; record versions and inspect failed/unsupported requests.

MIT licensed. Contributions adding adapters, workloads and measured evidence are welcome.

## Publishing your copy

Suggested repository name: **`llm-benchkit`**. Suggested description: **Portable LLM speed and sandboxed coding benchmarks with reproducible reports.**

Create an empty GitHub repository with that name, then connect this local repository and push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/llm-benchkit.git
git push -u origin main
```

Keep model weights, API keys, local configs and unreviewed run artifacts out of Git. The supplied `.gitignore` covers common local artifacts; explicitly review any results you choose to publish.
