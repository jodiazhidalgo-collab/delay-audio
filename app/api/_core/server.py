import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .router import respuesta_api, respuesta_api_post


STATIC_ROOT = "/app/static"
PREVIEW_ROOT = "/logs/delay_audio_preview"

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send(self, data, typ="text/html; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def j(self, obj, status=200):
        self.send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def static(self, path):
        rel = path.removeprefix("/static/").replace("/", os.sep)
        root = os.path.abspath(STATIC_ROOT)
        full = os.path.abspath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self.send(b"No encontrado.", "text/plain; charset=utf-8", 404)

        ext = os.path.splitext(full)[1].lower()
        typ = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                return self.send(f.read(), typ)
        except Exception:
            return self.send(b"No se pudo leer el recurso.", "text/plain; charset=utf-8", 500)

    def preview(self, path):
        rel = path.removeprefix("/preview/").replace("/", os.sep)
        root = os.path.abspath(PREVIEW_ROOT)
        full = os.path.abspath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self.send(b"No encontrado.", "text/plain; charset=utf-8", 404)
        if os.path.splitext(full)[1].lower() != ".mp4":
            return self.send(b"No permitido.", "text/plain; charset=utf-8", 403)
        try:
            file_size = os.path.getsize(full)
            range_header = self.headers.get("Range") or ""
            if range_header.startswith("bytes="):
                start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
                start = int(start_text or "0")
                end = int(end_text) if end_text else file_size - 1
                start = max(0, min(start, file_size - 1))
                end = max(start, min(end, file_size - 1))
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Connection", "close")
                self.end_headers()
                with open(full, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                self.close_connection = True
                return
            with open(full, "rb") as f:
                return self.send(f.read(), "video/mp4")
        except Exception:
            return self.send(b"No se pudo leer el preview.", "text/plain; charset=utf-8", 500)

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        path = parsed.path

        if path == "/favicon.ico":
            return self.send(b"", "image/x-icon", 204)

        if path.startswith("/static/"):
            return self.static(path)

        if path.startswith("/preview/"):
            return self.preview(path)

        if path == "/api":
            return self.j(respuesta_api(q))

        return self.send(self.server.pagina())

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api":
            return self.j({"ok": False, "error": "POST no permitido"}, 404)

        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > 1024 * 1024:
                return self.j({"ok": False, "error": "Solicitud no valida"}, 400)
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                return self.j({"ok": False, "error": "JSON no valido"}, 400)
            return self.j(respuesta_api_post(parsed.path, data))
        except Exception:
            return self.j({"ok": False, "error": "No se pudo procesar POST"}, 400)

    def log_message(self, *args):
        pass


def run(pagina, host="0.0.0.0", port=8080):
    port = int(os.environ.get("PORT", port))
    server = ThreadingHTTPServer((host, port), H)
    server.pagina = pagina
    server.daemon_threads = True
    server.serve_forever()
