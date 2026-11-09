"""Small bounded HTTP client; no SDK required, retries or silent redirects."""

import json
import time
import urllib.error
import urllib.request

LIMIT = 16 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTP:
    def __init__(self, base_url, headers=None, timeout=180):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect)

    def redact(self, text):
        for key in ("Authorization", "x-api-key"):
            secret = self.headers.get(key, "")
            if secret:
                text = text.replace(secret, "[REDACTED]")
                if secret.startswith("Bearer "):
                    text = text.replace(secret[7:], "[REDACTED]")
        return text

    def open(self, path, body):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **self.headers})
        try:
            return self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            detail = self.redact(e.read(2048).decode("utf-8", errors="replace"))
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(self.redact(f"Request failed: {e}")) from None

    def post(self, path, body):
        with self.open(path, body) as response:
            payload = response.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise RuntimeError("Response exceeds 16 MiB limit")
        data = json.loads(payload)
        if data.get("error"):
            raise RuntimeError(self.redact(str(data["error"])))
        return data

    def events(self, path, body, ndjson=False):
        deadline = time.monotonic() + self.timeout
        size = 0
        with self.open(path, body) as response:
            data_lines = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Stream exceeded request deadline")
                # urllib's socket timeout is otherwise an idle timeout, not a deadline.
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    sock.settimeout(remaining)
                line = response.readline(1024 * 1024 + 1)
                if not line:
                    if data_lines:
                        yield self._event(data_lines)
                    break
                size += len(line)
                if len(line) > 1024 * 1024 or size > LIMIT:
                    raise RuntimeError("Stream exceeds response size limit")
                text = line.decode("utf-8").rstrip("\r\n")
                if ndjson:
                    if text.strip():
                        yield self._event([text])
                elif not text:
                    if data_lines:
                        yield self._event(data_lines)
                        data_lines = []
                elif text.startswith("data:"):
                    data_lines.append(text[5:].lstrip(" "))

    def _event(self, lines):
        raw = "\n".join(lines)
        if raw == "[DONE]":
            return {"_done": True}
        data = json.loads(raw)
        if data.get("error") or data.get("type") == "error":
            raise RuntimeError(self.redact(str(data.get("error", data))))
        return data
