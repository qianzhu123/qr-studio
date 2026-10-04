"""server.py — qr-studio 本地服务（仅标准库，无框架依赖）。

启动:  python backend/server.py  [--port 8788]
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

from build import build_qr  # noqa: E402
from qr_decode import decode_image, trace_redirects  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
PROFILES = os.path.join(ROOT, "profiles")


def _load_image(data_url: str):
    if not data_url:
        return None
    raw = data_url.split(",", 1)[-1]
    buf = np.frombuffer(base64.b64decode(raw), np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- GET ----
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._file(os.path.join(FRONTEND, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self._file(os.path.join(FRONTEND, path[len("/static/"):]), _ctype(path))
        if path == "/api/profiles":
            names = []
            if os.path.isdir(PROFILES):
                names = [f[:-5] for f in os.listdir(PROFILES) if f.endswith(".json")]
            return self._json({"profiles": names})
        return self._json({"error": "not found"}, 404)

    def _file(self, p, ctype):
        try:
            with open(p, "rb") as f:
                self._send(200, f.read(), ctype)
        except FileNotFoundError:
            self._json({"error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self._read_body()
        except Exception as e:
            return self._json({"error": f"bad json: {e}"}, 400)

        if path == "/api/generate":
            return self._generate(body)
        if path == "/api/decode":
            return self._decode(body)
        if path == "/api/trace":
            return self._json({"chain": trace_redirects(body.get("url", ""))})
        if path == "/api/profiles":
            return self._save_profile(body)
        return self._json({"error": "not found"}, 404)

    def _generate(self, body):
        try:
            result = build_qr(body)
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        out = {
            "meta": result["meta"],
            "verify": result["verify"],
        }
        if body.get("render", {}).get("format", "png") == "png":
            out["image"] = "data:image/png;base64," + base64.b64encode(result["data"]).decode()
        else:
            out["data"] = result["data"] if isinstance(result["data"], str) else \
                result["data"].decode("utf-8", "replace")
        return self._json(out)

    def _decode(self, body):
        img = _load_image(body.get("image", ""))
        if img is None:
            return self._json({"error": "no image"}, 400)
        res = decode_image(img)
        return self._json(res)

    def _save_profile(self, body):
        os.makedirs(PROFILES, exist_ok=True)
        name = body.get("name", "profile")
        with open(os.path.join(PROFILES, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(body.get("config", {}), f, ensure_ascii=False, indent=2)
        return self._json({"ok": True, "name": name})


def _ctype(p):
    if p.endswith(".html"):
        return "text/html; charset=utf-8"
    if p.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if p.endswith(".css"):
        return "text/css; charset=utf-8"
    return "application/octet-stream"


def main():
    port = 8788
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"qr-studio  →  http://127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
