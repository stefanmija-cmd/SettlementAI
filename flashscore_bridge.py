"""Token-authenticated snapshot receiver. Put behind an HTTPS reverse proxy."""
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from flashscore_import import load_snapshot


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token):
        if len(token) < 24:
            raise ValueError("FLASHSCORE_BRIDGE_TOKEN mora imati najmanje 24 znaka.")
        self.token = token
        self.snapshot = None
        self.captured = 0
        self.lock = threading.Lock()
        super().__init__(address, BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not log request headers or data.

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("Origin") == "https://www.flashscore.com":
            self.send_header("Access-Control-Allow-Origin", "https://www.flashscore.com")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if self.path != "/snapshot" or self.headers.get("Origin") != "https://www.flashscore.com":
            self.reply(403, {"error": "Origin not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "https://www.flashscore.com")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def authorized(self):
        if self.path != "/snapshot":
            self.reply(404, {"error": "Not found"})
            return False
        value = self.headers.get("Authorization", "").encode()
        expected = ("Bearer " + self.server.token).encode()
        if not hmac.compare_digest(value, expected):
            self.reply(401, {"error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"ok": True})
            return
        if not self.authorized():
            return
        with self.server.lock:
            snapshot = self.server.snapshot
        if snapshot is None:
            self.reply(404, {"error": "Još nema podataka iz browsera."})
            return
        try:
            load_snapshot(json.dumps(snapshot), max_age=45)
        except ValueError as exc:
            self.reply(409, {"error": str(exc)})
            return
        self.reply(200, snapshot)

    def do_POST(self):
        self.connection.settimeout(10)
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 5_000_000:
                self.reply(413, {"error": "Body must be between 1 byte and 5 MB"})
                return
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("Incomplete body")
            _, captured = load_snapshot(data, max_age=45)
            snapshot = json.loads(data)
            with self.server.lock:
                if captured < self.server.captured:
                    self.reply(409, {"error": "Stariji snimak je odbijen."})
                    return
                self.server.snapshot = snapshot
                self.server.captured = captured
            self.reply(200, {"ok": True, "matches": len(snapshot["matches"])})
        except (ValueError, TimeoutError, OSError) as exc:
            self.reply(400, {"error": str(exc)})


def fetch_snapshot(url, token):
    import requests
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("Prijemnik zahteva HTTPS (HTTP je dozvoljen samo lokalno).")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("URL prijemnika ne sme sadržati lozinku, query ili fragment.")
    if len(token) < 24:
        raise ValueError("Podesite FLASHSCORE_BRIDGE_TOKEN (najmanje 24 znaka).")
    try:
        with requests.get(url.rstrip("/") + "/snapshot", headers={"Authorization": "Bearer " + token},
                          timeout=(5, 10), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError(f"Flashscore prijemnik: HTTP {response.status_code}. Proverite vezu, token i da li browser šalje sveže podatke.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 5_000_000:
                    raise ValueError("Flashscore odgovor prelazi 5 MB.")
                chunks.append(chunk)
            return load_snapshot(b"".join(chunks), max_age=45)
    except requests.RequestException as exc:
        raise ValueError("Flashscore prijemnik nije dostupan. Proverite URL i mrežnu vezu.") from exc


if __name__ == "__main__":
    server = BridgeServer((os.environ.get("FLASHSCORE_BRIDGE_HOST", "127.0.0.1"),
                           int(os.environ.get("PORT", os.environ.get("FLASHSCORE_BRIDGE_PORT", "8765")))),
                          os.environ.get("FLASHSCORE_BRIDGE_TOKEN", ""))
    print("Flashscore prijemnik pokrenut; jedan feed po instanci.", flush=True)
    server.serve_forever()
