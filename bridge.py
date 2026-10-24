"""
Encode Craft Bridge — local job receiver prototype.

This bridge accepts local JSON job requests from a future FilmCraft integration
and stores them in an inbox file. It does not modify FilmCraft or perform exports
by itself yet; the Rust-side integration must render/export the timeline and send
the resulting file path or a render job reference.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import secrets
import threading
from datetime import datetime, timezone

HOST = "127.0.0.1"
PORT = 8765
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "EncodeCraft"
INBOX = APP_DIR / "filmcraft_inbox.jsonl"
TOKEN_FILE = APP_DIR / "bridge_token.txt"
MAX_BODY = 64 * 1024


def setup():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    if not INBOX.exists():
        INBOX.touch()


def load_token():
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "EncodeCraftBridge/0.1"

    def log_message(self, fmt, *args):
        print("[Bridge] " + (fmt % args))

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {
                "ok": True,
                "service": "Encode Craft Bridge",
                "version": "0.1",
                "inbox": str(INBOX)
            })
        self._send(404, {"ok": False, "error": "Unknown endpoint"})

    def do_POST(self):
        if self.path != "/enqueue":
            return self._send(404, {"ok": False, "error": "Unknown endpoint"})

        # A per-installation bearer token prevents unrelated local processes
        # from silently adding jobs. This is a basic local safeguard, not a
        # substitute for OS-level security.
        auth = self.headers.get("Authorization", "")
        expected = "Bearer " + load_token()
        if not secrets.compare_digest(auth, expected):
            return self._send(401, {"ok": False, "error": "Unauthorized"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._send(400, {"ok": False, "error": "Invalid Content-Length"})

        if length < 1 or length > MAX_BODY:
            return self._send(413, {"ok": False, "error": "Request body must be 1–65536 bytes"})

        try:
            body = self.rfile.read(length)
            job = json.loads(body.decode("utf-8"))
        except Exception:
            return self._send(400, {"ok": False, "error": "Body must be valid UTF-8 JSON"})

        if not isinstance(job, dict):
            return self._send(400, {"ok": False, "error": "Job must be a JSON object"})

        # First milestone accepts an already-rendered source file. Direct
        # timeline rendering will be added in the FilmCraft Rust integration.
        source = job.get("source")
        if not isinstance(source, str) or not source.strip():
            return self._send(400, {
                "ok": False,
                "error": "Missing 'source'. First milestone expects a rendered file path."
            })

        fmt = str(job.get("format", "MP4")).upper()
        allowed = {"MP4", "MOV", "WEBM", "MKV", "AVI", "GIF", "MP3", "WAV", "FLAC"}
        if fmt not in allowed:
            return self._send(400, {"ok": False, "error": f"Unsupported format: {fmt}"})

        clean_job = {
            "id": secrets.token_hex(8),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "origin": "FilmCraft",
            "source": source.strip(),
            "format": fmt,
            "output_dir": str(job.get("output_dir", "")).strip(),
            "preset": str(job.get("preset", "Balanced")).strip(),
            "status": "received"
        }

        # Append one JSON record per line. Encode Craft can later watch this
        # inbox and show each record in its queue.
        with threading.Lock():
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps(clean_job, ensure_ascii=False) + "\n")

        self._send(202, {"ok": True, "job_id": clean_job["id"], "status": "received"})


def main():
    setup()
    print("Encode Craft Bridge is listening only on this PC.")
    print(f"Endpoint: http://{HOST}:{PORT}")
    print(f"Inbox: {INBOX}")
    print(f"Token file: {TOKEN_FILE}")
    print("Press Ctrl+C to stop.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping bridge...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
