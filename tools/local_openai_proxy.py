"""Small local OpenAI-compatible bridge for isolated DB-GPT benchmark servers.

It forwards plain LLM requests to the already running DB-GPT service, so
benchmark snapshots can share the user's configured model without copying an
API key into benchmark configs.
"""

from __future__ import annotations

import json
import hashlib
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "http://127.0.0.1:5670/api/v1/chat/completions"


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalOpenAIProxy/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "deepseek-v4-flash"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if self.path.rstrip("/") == "/v1/embeddings":
            texts = request.get("input") or []
            if isinstance(texts, str):
                texts = [texts]
            data = []
            for index, value in enumerate(texts):
                digest = hashlib.sha256(str(value).encode("utf-8")).digest()
                vector = [round((byte / 255.0) * 2.0 - 1.0, 6) for byte in digest[:8]]
                data.append({"object": "embedding", "embedding": vector, "index": index})
            self._json(
                200,
                {
                    "object": "list",
                    "data": data,
                    "model": request.get("model", "text-embedding-3-small"),
                    "usage": {"prompt_tokens": 0, "total_tokens": 0},
                },
            )
            return
        messages = request.get("messages") or []
        parts = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(item.get("text", item)) for item in content)
            parts.append(f"[{role}]\n{content}")
        upstream_body = {
            "user_input": "\n\n".join(parts),
            "chat_mode": "chat_normal",
            "model_name": "deepseek-v4-flash",
            "incremental": False,
        }
        try:
            req = urllib.request.Request(
                UPSTREAM,
                data=json.dumps(upstream_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            content = ""
            raw_bytes = 0
            with urllib.request.urlopen(req, timeout=300) as response:
                for line_bytes in response:
                    raw_bytes += len(line_bytes)
                    line = line_bytes.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        item = json.loads(line[5:].strip())
                        choice = (item.get("choices") or [{}])[0]
                        message = choice.get("message") or {}
                        content = message.get("content") or choice.get("text") or content
                        # DB-GPT asks for a JSON object. Once the SQL field and
                        # closing brace arrive, no further reasoning is needed.
                        if '"sql"' in content and content.rstrip().endswith("}"):
                            break
                    except json.JSONDecodeError:
                        continue
            print(f"upstream bytes={raw_bytes}", flush=True)
            # Auto-execute prompts require a JSON object. Strip the model's
            # optional reasoning/code-fence wrapper before returning content.
            if '"sql"' in content:
                start = content.find("{")
                end = content.rfind("}")
                if start >= 0 and end > start:
                    content = content[start : end + 1]
            payload = {
                "id": "local-proxy",
                "object": "chat.completion",
                "model": request.get("model", "deepseek-v4-flash"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {},
            }
            print(f"response chars={len(content)}", flush=True)
            if request.get("stream"):
                stream_payload = dict(payload)
                stream_payload["choices"] = [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
                raw_payload = json.dumps(stream_payload, ensure_ascii=False).encode("utf-8")
                stream_body = b"data: " + raw_payload + b"\n\ndata: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(stream_body)))
                self.end_headers()
                self.wfile.write(stream_body)
                return
            self._json(200, payload)
        except Exception as exc:  # pragma: no cover - diagnostic bridge
            self._json(502, {"error": {"message": f"upstream failure: {exc}"}})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 5699), Handler)
    print("local OpenAI proxy listening on http://127.0.0.1:5699", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
