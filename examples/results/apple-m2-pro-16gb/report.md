# Local model benchmark - M2 Pro, 16 GB

Tested November 9, 2026 using the earlier Mac-specific harness. This is historical evidence, not a run from the portable CLI. See the [example index](README.md) for artifact/schema details.

**Recommendation: Qwen3.5-4B Q4_K_M with the installed llama.cpp Metal engine, for reviewed and scoped local coding assistance.** It completed two of three coding tasks and 24 of 27 checks. None of the three tested configurations met an error-free, unattended heavy-coding requirement. The long-context checks also exposed slowdowns and repeated repair/tool loops.

## Release dates and measured short-completion speed

Same installed llama.cpp build and Metal backend; published Q4_K_M checkpoints; 16K context capacity; fresh 4,096-token synthetic code input; 128 output tokens; medians of two runs. Engine kernels are warmed, but prompt reuse is disabled. Raw speed trials do not include reasoning/tool orchestration overhead.

| Model | Base-model release | Prefill tokens/s | Decode tokens/s | First token | Model file |
|---|---|---:|---:|---:|---:|
| LFM3 1.7B | [2026-10-27](https://www.liquid.ai/blog/lfm3) | 1,245.0 | 101.1 | 3.29 s | 1.10 GB |
| Qwen3.5 4B | [2026-03-02](https://github.com/QwenLM/Qwen3.8#news) | 457.7 | 36.4 | 8.96 s | 2.74 GB |
| Spark X2.6 4B | [2026-10-21](https://github.com/XHToken/Spark-X2.6#release) | 290.1 | 31.9 | 14.25 s | 3.54 GB |

The release dates are for the original models, not the dates the quantized files were uploaded or downloaded. A Q4_K_M checkpoint uses mixed precision; file sizes and exact bit allocation differ by model.

## Code editing and tests

The models used read_file, write_file, search_code and run_tests tools in isolated fixture projects. The source and tests were inspectable; tests could not be modified. Each task allowed up to 10 assistant turns. Final runs used a 4,096-token output allowance, up to 512 reasoning tokens, and the author sampling settings recorded in methodology.json. Cache and money tasks used 8K context; concurrency was rerun at 16K for every model after the original 8K sessions hit the context limit.

| Model | Cache checks /8 | Money checks /12 | Concurrency checks /7 | Total /27 | Fully completed tasks /3 | Total task time |
|---|---:|---:|---:|---:|---:|---:|
| LFM3 1.7B | 6 | 2 | 4 | 12 | 0 | 2.81 min |
| Qwen3.5 4B | 8 | 12 | 4 | 24 | 2 | 9.14 min |
| Spark X2.6 4B | 8 | 3 | 6 | 17 | 1 | 6.80 min |

Tasks: TTL expiry and LRU eviction in Python; Decimal/HALF_UP monetary calculations across two Python files; bounded JavaScript asynchronous concurrency, ordering, validation and rejection handling. These are 27 test methods across three small projects, not 27 independent repository tasks. A task passes only when the edited files pass its entire suite. Partial passes remain failures at task level.

Hand-written control implementations passed all 27 checks, confirming the test suites are satisfiable. Model-generated code ran without network access and with filesystem writes restricted to its own fixture. A generated program exceeding the 10-second test timeout was marked incomplete and its process group terminated.

## Why Qwen is the local pick

Qwen had the highest complete-task count and most passing checks. It passed all cache and money checks. Its concurrency code remained incorrect after the longer-context retry, which took about 6.4 minutes. Spark passed the cache task but failed the money and concurrency tasks. LFM3 was by far the fastest at plain generation but failed all three complete editing tasks in these tested settings.

**This is a best-of-these-tested-setups recommendation, not a claim of Claude/GPT-level autonomous coding or a universal model ranking.** Different agents, prompts, quantizations, sampling budgets and runtime revisions can change the results.

## Sustained-use and context findings

- The short plain-completion trials showed no inter-chunk decode gaps above two seconds. This does not establish all-day stability.
- The 8K concurrency sessions overflowed their context windows. The 16K retry gave the models room to continue, but none fully solved the task.
- A Qwen response with roughly 9K tokens already in the conversation averaged 6.47 tokens/s over 885 output tokens. Short-completion figures therefore overstate how fast a long tool loop can feel.
- During the diagnostic snapshot there was no reported thermal warning. The Mac had about 16 GB of swap already in use, and a later three-second sample observed swap-ins. These observations do not establish a single cause for the slowdown.
- User applications stayed open. No memory purge, application termination, OS tuning or overclock was performed.

## Practical preset

- Model: `unsloth/Qwen3.5-4B-GGUF`, file `Qwen3.5-4B-Q4_K_M.gguf` (downloaded and visible in TurboLLM).
- Engine: installed `Llama-master` / llama.cpp Metal.
- Start with 8K context for focused tasks; use 16K when history requires it, with the measured latency caveats above.
- Reasoning enabled, budget 512 tokens; max output 4,096 tokens.
- Temperature 0.6, top_p 0.95, top_k 20.
- One request/model slot; full GPU offload; flash attention on; six CPU threads.
- Start a fresh conversation for a separate coding task and supply relevant files. Review changes and run your project tests.

## Additional Qwen MLX check

The installed mlx-lm 0.32.2 runtime with `mlx-community/Qwen3.5-4B-MLX-4bit` measured 345.6 prefill tokens/s, 52.2 decode tokens/s and 11.85 seconds to first token at 4K input. Its separate thinking-disabled, greedy coding run passed 19/27 checks and 0/3 full tasks.

The MLX coding profile differed from the final reasoning-enabled GGUF profile. The checkpoint quantization and prefill implementation also differed. These results do not isolate a backend-only accuracy difference, and MLX was not qualified as the daily agent preset in this study.

## Runtime, sources and evidence

- Hardware: MacBook Pro Mac14,9; Apple M2 Pro; 10 CPU cores; 16 GPU cores; 16 GB unified memory; macOS 15.5 (24F74).
- Runtime: `version: 0.8.0-dev (build 1, commit 5220213)`.
- Source revision: `522021325546ea322b0b1e58a50f9dbf03a5f197`; the existing local BF16 Metal constexpr compatibility patch remains in this build.
- Source repositories and SHA-256 checksums: [model-manifest.json](model-manifest.json). All downloaded model files were verified.
- Spark's official GGUF metadata displays its name as `Dense F32` in TurboLLM; the source repository, filename and verified checksum identify the tested Spark checkpoint.

- [CSV measurements](measurements.csv)
- [Summarized data](summary.json)
- [GGUF raw results and task outcomes](results.json)
- [MLX raw results](mlx-results.json)
- [Methodology and exact settings](methodology.json)
- [Reference-control validation](reference-control-validation.json)
- [Pinned model manifests](model-manifest.json)
- [Final coding transcripts](transcripts/)
- [Sanitized server logs](logs/)

Per-task JSON files include assistant/tool transcripts, test output, token counts and timings. Server logs provide further timing evidence. Earlier calibration attempts and 8K context checks remain in explicitly named fields in results.json where recorded and are excluded from the final coding ranking. No hosted Claude/GPT API was called, so no direct cloud-speed or cloud-quality equivalence was established.

Personal project/home/temp paths in the published evidence have been anonymized. Timing values, token counts, test outcomes, model revisions and checksums are unchanged.
