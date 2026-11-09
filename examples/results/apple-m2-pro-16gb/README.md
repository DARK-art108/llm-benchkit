# Apple M2 Pro, 16 GB — measured benchmark example

**Measured November 9, 2026.** This folder publishes the actual earlier benchmark, not a new run or an illustration with invented numbers. It used the machine-specific harness that preceded the portable CLI. Personal home, workspace and temporary filesystem paths were anonymized; numeric measurements and test outcomes are unchanged.

## Main comparison

Hardware: Apple M2 Pro, 10 CPU cores (6 performance / 4 efficiency), 16 GPU cores, 16 GB unified memory; macOS 15.5. Engine: llama.cpp Metal, revision `522021325546ea322b0b1e58a50f9dbf03a5f197`, with the local BF16 Metal constexpr compatibility patch.

All three primary models use Q4_K_M. Short speed results below are medians of two warm-engine runs with 4,096 fresh input tokens, 128 generated tokens, 16K context capacity and prompt reuse disabled.

| Model | Release | Prefill tok/s | Decode tok/s | First output s | Coding checks | Full tasks |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| LFM3 1.7B | 2026-10-27 | 1245.0 | 101.1 | 3.29 | 12/27 | 0/3 |
| Qwen3.5 4B | 2026-03-02 | 457.7 | 36.4 | 8.96 | 24/27 | 2/3 |
| Spark X2.6 4B | 2026-10-21 | 290.1 | 31.9 | 14.25 | 17/27 | 1/3 |

Release sources and detailed interpretation are in the [full report](report.md). Qwen was the best coding balance among these configurations, while LFM3 had the fastest plain generation. None fully passed the concurrency task, and one long Qwen tool response averaged 6.47 tokens/s. Short completion rates do not establish stable heavy-use performance.

## Files

| Artifact | Contents |
| --- | --- |
| [report.md](report.md) | Full measured report, limitations, release sources and tested preset |
| [measurements.csv](measurements.csv) | All summarized speed conditions, including 8K/16K context and separate MLX rows |
| [summary.json](summary.json) | Per-model speed medians/ranges and coding totals |
| [methodology.json](methodology.json) | Runtime revision, reasoning/sampling settings, contexts and notes |
| [model-manifest.json](model-manifest.json) | Source repositories, pinned revisions, file sizes and checksums |
| [results.json](results.json) | Original GGUF timing trials, final coding results and named calibration/context-check fields |
| [mlx-results.json](mlx-results.json) | Separate Qwen MLX observations with its different settings |
| [reference-control-validation.json](reference-control-validation.json) | Hand-written reference controls passed all 27 checks; these are not model scores |
| [transcripts/](transcripts/) | Final assistant/tool conversations and test output for all 12 model/task combinations |
| [logs/](logs/) | Engine logs for the GGUF and MLX checks |

## Method and limits

- Coding covered three synthetic projects: Python TTL/LRU cache (8 checks), Python Decimal checkout (12), and JavaScript bounded async concurrency (7). This is not SWE-bench.
- Final GGUF coding allowed 10 assistant turns, 4,096 output tokens and a 512-token reasoning budget. Sampling differed by model as recorded in methodology.json. Cache/money used 8K context; concurrency was rerun for all three at 16K after initial context overflows.
- Historical generated-code execution used macOS process isolation. The portable runner now uses Docker, so its task times should not be treated as interchangeable with these.
- MLX used a different 4-bit checkpoint, thinking disabled and greedy coding sampling. Its code score is not a controlled backend-only comparison against the reasoning-enabled GGUF trials.
- The Mac's other apps stayed open and substantial swap was already allocated. These conditions affect repeatability; no single cause of the observed slowdowns was established.
- Initial calibration/context-overflow results are not included in the headline coding totals. The final per-task transcripts, current `coding` arrays and summary tables identify the ranked attempts.
- No hosted Claude/GPT model was tested, and these runs did not establish all-day stability or cloud-assistant equivalence.

## Schema note

These JSON files retain the **legacy harness format** to preserve the original evidence. They do not have the portable CLI's `schema_version: 1` structure and should not be passed to `llm-benchkit report` or `merge`. Read the provided Markdown/CSV/JSON directly. New CLI runs generate their own reports in the documented format.
