# Original M2 Pro experiment

Measured November 9, 2026 using the earlier, machine-specific harness. These are historical observations, **not results produced by the new portable CLI**. They motivated the separation of engine timings, observed latency, code correctness and incomplete coverage in BenchKit. No model weights are included in this repository.

Hardware: MacBook Pro, Apple M2 Pro (10 CPU / 16 GPU cores), 16 GB unified memory, macOS 15.5. llama.cpp revision `522021325546ea322b0b1e58a50f9dbf03a5f197`, with a local BF16 Metal constexpr compatibility patch. User apps remained open and substantial swap was already allocated.

All three GGUF checkpoints used Q4_K_M. Speed: median of two warm-engine raw trials, 4,096 fresh input tokens, 128 output tokens, 16K context capacity and prompt reuse disabled.

| Model | Base-model release | Prefill tok/s | Decode tok/s | First output s | Coding checks | Full tasks |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| LFM3 1.7B | [2026-10-27](https://www.liquid.ai/blog/lfm3) | 1245.0 | 101.1 | 3.29 | 12/27 | 0/3 |
| Qwen3.5 4B | [2026-03-02](https://github.com/QwenLM/Qwen3.8#news) | 457.7 | 36.4 | 8.96 | 24/27 | 2/3 |
| Spark X2.6 4B | [2026-10-21](https://github.com/XHToken/Spark-X2.6#release) | 290.1 | 31.9 | 14.25 | 17/27 | 1/3 |

Coding used the same three fixture projects now included in BenchKit, with a 512-token reasoning budget, 4,096 output allowance, 10 assistant turns and author sampling settings. Cache/money tasks used 8K context. Concurrency tasks overflowed 8K and were rerun for all models at 16K; none fully passed concurrency. Reference implementations passed all 27 checks. The earlier harness used macOS process isolation; the portable harness uses Docker, so task runtimes are not directly comparable.

Qwen was the best tested local coding balance, but one long Qwen tool conversation averaged only 6.47 output tokens/s. Short speed trials did not establish stable heavy-use performance. No hosted Claude/GPT API was benchmarked head-to-head. These three synthetic projects do not establish a general coding leaderboard.

Model sources:

- [LiquidAI/LFM3-1.7B-GGUF](https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF), revision `cd0c74c575b5c416f3011b5b4c298077f26ca8c2`.
- [unsloth/Qwen3.5-4B-GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF), revision `e87f176479d0855a907a41277aca2f8ee7a09523`.
- [XHToken/Spark-X2.6-4B-GGUF](https://huggingface.co/XHToken/Spark-X2.6-4B-GGUF), revision `9d716770ac7477776de5f891f70cdf98b003a5cd`.
