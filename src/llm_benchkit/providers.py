"""Provider adapters. Engine timings and client observations stay separate."""

import copy
import hashlib
import json
import os
import time

from .transport import HTTP


def prompt_text(chars, nonce):
    header = f"Request {nonce}. Review this code for correctness. Explain improvements.\n"
    unit = ("def order_total(items, tax=0.18):\n"
            "    subtotal = sum(item['price'] * item['quantity'] for item in items)\n"
            "    return round(subtotal * (1 + tax), 2)\n\n")
    return (header + unit * (chars // len(unit) + 2))[:chars]


def normalized_message(message):
    message = copy.deepcopy(message)
    message.setdefault("role", "assistant")
    message.setdefault("content", "")
    for index, call in enumerate(message.get("tool_calls") or []):
        call.setdefault("id", f"call_{index}")
        call.setdefault("type", "function")
        args = call["function"].get("arguments", {})
        if not isinstance(args, str):
            call["function"]["arguments"] = json.dumps(args)
    return message


class Provider:
    def __init__(self, model, timeout=180):
        self.config = model
        self.kind = model["provider"]
        self.options = copy.deepcopy(model.get("request", {}))
        headers = {}
        env = model.get("api_key_env")
        if env:
            secret = os.environ.get(env)
            if not secret:
                raise ValueError(f"Missing API key environment variable: {env}")
            headers["x-api-key" if self.kind == "anthropic" else "Authorization"] = (
                secret if self.kind == "anthropic" else "Bearer " + secret)
        if self.kind == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        self.http = HTTP(model["base_url"], headers, timeout)

    def _body(self, messages, limit, stream, tools=None):
        messages = copy.deepcopy(messages)
        opts = copy.deepcopy(self.options)
        if self.kind == "anthropic":
            system = "\n".join(m.get("content", "") for m in messages if m["role"] == "system")
            converted = []
            for m in messages:
                if m["role"] == "system":
                    continue
                if m["role"] == "tool":
                    block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                    if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                        converted[-1]["content"].append(block)
                    else:
                        converted.append({"role": "user", "content": [block]})
                elif m.get("_native_blocks") is not None:
                    converted.append({"role": "assistant", "content": m["_native_blocks"]})
                else:
                    converted.append({"role": m["role"], "content": m.get("content") or ""})
            body = {**opts, "model": self.config["model"], "messages": converted,
                    "max_tokens": limit, "stream": stream}
            if system:
                body["system"] = system
            if tools:
                body["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                                  "input_schema": t["function"]["parameters"]} for t in tools]
            return "/messages", body
        for m in messages:
            m.pop("_native_blocks", None)
        if self.kind == "ollama":
            for m in messages:
                m["content"] = m.get("content") or ""
                if m.get("tool_calls"):
                    for call in m["tool_calls"]:
                        call["function"]["arguments"] = json.loads(call["function"]["arguments"])
                if m["role"] == "tool":
                    m["tool_name"] = m.pop("name", "")
                    m.pop("tool_call_id", None)
            options = {**opts.pop("options", {}), "num_predict": limit}
            body = {**opts, "model": self.config["model"], "messages": messages,
                    "options": options, "stream": stream}
            if tools:
                body["tools"] = tools
            return "/api/chat", body
        body = {**opts, "model": self.config["model"], "messages": messages,
                self.config.get("token_limit_field", "max_tokens"): limit, "stream": stream}
        if stream:
            body.setdefault("stream_options", {"include_usage": True})
        if tools:
            body.update(tools=tools, tool_choice="auto")
        return "/chat/completions" if self.kind == "openai" else "/v1/chat/completions", body

    def chat(self, messages, tools, limit):
        path, body = self._body(messages, limit, False, tools)
        response = self.http.post(path, body)
        if self.kind == "anthropic":
            blocks = response.get("content", [])
            message = {"role": "assistant", "content": "".join(b.get("text", "") for b in blocks),
                       "_native_blocks": blocks, "tool_calls": [
                           {"id": b["id"], "type": "function", "function": {
                               "name": b["name"], "arguments": json.dumps(b["input"])}}
                           for b in blocks if b["type"] == "tool_use"]}
        elif self.kind == "ollama":
            message = response["message"]
        else:
            message = response["choices"][0]["message"]
        return normalized_message(message), response.get("usage", {})

    def speed(self, size, limit, nonce):
        exact = self.kind == "llamacpp"
        prompt = prompt_text(size * 10 if exact else size, nonce)
        if exact:
            tokens = self.http.post("/tokenize", {"content": prompt, "add_special": True})["tokens"]
            if len(tokens) < size:
                raise RuntimeError("Generated prompt did not yield enough tokens")
            prompt = tokens[:size]
            path = "/completion"
            body = {**copy.deepcopy(self.options), "prompt": prompt, "n_predict": limit,
                    "temperature": 0, "seed": 123, "stream": True, "cache_prompt": False,
                    "ignore_eos": True}
        else:
            path, body = self._body([{"role": "user", "content": prompt}], limit, True)
        start = time.perf_counter()
        first = visible = last = None
        gaps = []
        chunks = 0
        text_hash = hashlib.sha256()
        chars = 0
        usage = {}
        timings = {}
        complete = False
        finish = None
        for event in self.http.events(path, body, ndjson=self.kind == "ollama"):
            now = time.perf_counter()
            text = reasoning = ""
            if exact:
                text = event.get("content", "")
                timings.update(event.get("timings", {}))
                if event.get("stop"):
                    complete = True
                    finish = event.get("stop_type", "stop")
            elif self.kind == "ollama":
                message = event.get("message", {})
                text, reasoning = message.get("content", ""), message.get("thinking", "")
                if event.get("done"):
                    complete = True
                    finish = event.get("done_reason")
                    usage = {"prompt_tokens": event.get("prompt_eval_count"),
                             "completion_tokens": event.get("eval_count"),
                             "prompt_tokens_details": {"cached_tokens": event.get("prompt_eval_cached_count")}}
                    timings = {"prompt_n": event.get("prompt_eval_count"),
                               "predicted_n": event.get("eval_count")}
                    for duration, count, target in (("prompt_eval_duration", "prompt_eval_count", "prompt_per_second"),
                                                     ("eval_duration", "eval_count", "predicted_per_second")):
                        if event.get(duration) and event.get(count) is not None:
                            timings[target] = event[count] / (event[duration] / 1e9)
            elif self.kind == "anthropic":
                kind = event.get("type")
                if kind == "message_start":
                    usage.update(event.get("message", {}).get("usage", {}))
                elif kind == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                    reasoning = event.get("delta", {}).get("thinking", "")
                elif kind == "message_delta":
                    usage.update(event.get("usage", {}))
                    finish = event.get("delta", {}).get("stop_reason")
                elif kind == "message_stop":
                    complete = True
            else:
                usage.update(event.get("usage") or {})
                timings.update(event.get("timings") or {})
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    text += delta.get("content") or ""
                    reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if choice.get("finish_reason") is not None:
                        complete = True
                        finish = choice["finish_reason"]
            if text or reasoning:
                first = first if first is not None else now
                if last is not None:
                    gaps.append(now - last)
                last = now
                chunks += 1
            if text:
                visible = visible if visible is not None else now
                chars += len(text)
                text_hash.update(text.encode())
            if event.get("_done") or (exact and event.get("stop")) or (self.kind == "ollama" and event.get("done")) or event.get("type") == "message_stop":
                break
        wall = time.perf_counter() - start
        if not complete:
            raise RuntimeError("Stream ended without a terminal completion event")
        if first is None:
            raise RuntimeError("Model returned no text or exposed reasoning content")
        if self.kind == "anthropic":
            # Anthropic input_tokens excludes cache creation/read tokens.
            usage["prompt_tokens"] = sum(usage.get(k, 0) or 0 for k in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            usage["completion_tokens"] = usage.get("output_tokens")
        inputs = timings.get("prompt_n", usage.get("prompt_tokens"))
        outputs = timings.get("predicted_n", usage.get("completion_tokens"))
        return {
            "status": "ok", "input_size": size, "input_unit": "tokens" if exact else "characters",
            "prompt_tokens": inputs, "completion_tokens": outputs,
            "cached_prompt_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens",
                                      usage.get("cache_read_input_tokens")),
            "reasoning_tokens": usage.get("completion_tokens_details", {}).get("reasoning_tokens"),
            "engine_prefill_tps": timings.get("prompt_per_second"),
            "engine_decode_tps": timings.get("predicted_per_second"),
            "client_output_tps": outputs / wall if outputs is not None else None,
            "ttft_seconds": first - start, "first_visible_seconds": None if visible is None else visible - start,
            "wall_seconds": wall, "max_chunk_gap_seconds": max(gaps, default=0),
            "gaps_over_2s": sum(g > 2 for g in gaps), "content_chunks": chunks,
            "output_characters": chars, "output_sha256": text_hash.hexdigest(),
            "finish_reason": finish, "usage": usage, "engine_timings": timings,
        }
