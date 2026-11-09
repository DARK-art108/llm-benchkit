"""JSON configuration, explicit model metadata and publishable snapshots."""

import copy
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

PROVIDERS = {"openai", "llamacpp", "ollama", "anthropic"}
DEFAULT_BENCHMARK = {
    "input_chars": [1024, 8192], "input_tokens": [1024, 4096],
    "output_tokens": 128, "repeats": 3, "warmup": 1, "timeout_seconds": 180,
}
DEFAULT_CODING = {"max_turns": 10, "output_tokens": 4096, "test_timeout_seconds": 10}


def positive(value, name, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'} integer")
    return value


def load_config(path):
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config must be a JSON object")
    unknown = set(raw) - {"models", "benchmark", "coding", "environment", "tasks_file"}
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")
    models = raw.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("models must be a nonempty list")
    ids = set()
    for m in models:
        if not isinstance(m, dict):
            raise ValueError("Every model must be an object")
        allowed = {"id", "provider", "base_url", "model", "api_key_env", "request",
                   "release_date", "release_source", "metadata", "token_limit_field"}
        if set(m) - allowed:
            raise ValueError(f"Unknown model keys: {sorted(set(m) - allowed)}")
        for key in ("id", "provider", "base_url", "model"):
            if not isinstance(m.get(key), str) or not m[key].strip():
                raise ValueError(f"Every model needs a nonempty {key}")
        if m["id"] in ids:
            raise ValueError(f"Duplicate model id: {m['id']}")
        ids.add(m["id"])
        if m["provider"] not in PROVIDERS:
            raise ValueError(f"Unknown provider: {m['provider']}")
        if m.get("token_limit_field", "max_tokens") not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("token_limit_field must be max_tokens or max_completion_tokens")
        if "token_limit_field" in m and m["provider"] != "openai":
            raise ValueError("token_limit_field applies only to the openai-compatible adapter")
        url = urlsplit(m["base_url"])
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("base_url must be an HTTP(S) URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Use api_key_env; base_url cannot contain credentials, query or fragment")
        m["base_url"] = m["base_url"].rstrip("/")
        for key in ("request", "metadata"):
            if not isinstance(m.get(key, {}), dict):
                raise ValueError(f"{key} must be an object")
        controlled = {"model", "messages", "prompt", "stream", "tools", "tool_choice", "max_tokens", "max_completion_tokens", "n_predict", "n"}
        if controlled & set(m.get("request", {})):
            raise ValueError(f"These request fields are controlled by BenchKit: {sorted(controlled)}")
        if "api_key_env" in m and (not isinstance(m["api_key_env"], str) or not m["api_key_env"]):
            raise ValueError("api_key_env must name an environment variable")
        # Keep arbitrary provider options, but never allow credentials in the saved config.
        if any(k.lower() in {"api_key", "headers", "authorization", "x-api-key"} for k in m.get("request", {})):
            raise ValueError("Credentials belong in environment variables, not request")
        if m.get("release_date"):
            dt.date.fromisoformat(m["release_date"])
    if not isinstance(raw.get("benchmark", {}), dict) or not isinstance(raw.get("coding", {}), dict):
        raise ValueError("benchmark and coding settings must be objects")
    b = {**DEFAULT_BENCHMARK, **raw.get("benchmark", {})}
    if set(b) - set(DEFAULT_BENCHMARK):
        raise ValueError("Unknown benchmark setting")
    for key in ("input_chars", "input_tokens"):
        if not isinstance(b[key], list) or not b[key]:
            raise ValueError(f"{key} must be a nonempty list")
        for val in b[key]:
            positive(val, key)
    for key in ("output_tokens", "repeats", "warmup"):
        positive(b[key], key, allow_zero=key == "warmup")
    t = b["timeout_seconds"]
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    c = {**DEFAULT_CODING, **raw.get("coding", {})}
    if set(c) - set(DEFAULT_CODING):
        raise ValueError("Unknown coding setting")
    for key, val in c.items():
        positive(val, key)
    raw.update(benchmark=b, coding=c)
    if not isinstance(raw.get("environment", {}), dict):
        raise ValueError("environment must be an object of user-supplied runtime notes")
    if "tasks_file" in raw:
        raw["tasks_file"] = str((path.resolve().parent / raw["tasks_file"]).resolve())
    return raw


def snapshot(config):
    result = copy.deepcopy(config)
    if "tasks_file" in result:
        result["tasks_file"] = Path(result["tasks_file"]).name
    return result
