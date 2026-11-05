import json
import secrets
import threading
import unittest
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flashscore_bridge import BridgeServer, fetch_snapshot


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.server = BridgeServer(("127.0.0.1", 0), self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.payload = {"schema": "settlementai.flashscore.v1", "capturedAt": datetime.now(timezone.utc).isoformat(),
                        "matches": [{"id": "g_1_test", "home": "Home", "away": "Away", "homeScore": "1", "awayScore": "0"}]}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method="GET", data=None, token=True, origin=None, path="/snapshot"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + self.token
        if origin:
            headers["Origin"] = origin
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                      headers=headers, method=method)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, response.headers

    def test_authenticated_push_pull_and_correction(self):
        self.assertEqual(self.request()[0], 404)
        self.assertEqual(self.request("POST", self.payload)[0], 200)
        fixtures, _ = fetch_snapshot(self.url, self.token)
        self.assertEqual(fixtures[0]["goals"]["home"], 1)
        self.payload["capturedAt"] = datetime.now(timezone.utc).isoformat()
        self.payload["matches"][0]["homeScore"] = "0"
        self.assertEqual(self.request("POST", self.payload)[0], 200)
        self.assertEqual(fetch_snapshot(self.url, self.token)[0][0]["goals"]["home"], 0)

    def test_auth_cors_and_health(self):
        self.assertEqual(self.request(token=False)[0], 401)
        self.assertEqual(self.request("POST", self.payload, token=False)[0], 401)
        self.assertEqual(self.request(path="/health", token=False)[0], 200)
        status, _, headers = self.request("OPTIONS", token=False, origin="https://www.flashscore.com")
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://www.flashscore.com")
        self.assertEqual(self.request("OPTIONS", token=False, origin="https://example.com")[0], 403)

    def test_stale_malformed_and_out_of_order_do_not_replace_feed(self):
        self.assertEqual(self.request("POST", self.payload)[0], 200)
        self.payload["capturedAt"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        self.assertEqual(self.request("POST", self.payload)[0], 409)
        self.payload["capturedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertEqual(self.request("POST", self.payload)[0], 400)
        self.assertEqual(self.request("POST", {})[0], 400)
        self.assertEqual(self.request()[0], 200)
        with self.server.lock:
            self.server.snapshot["capturedAt"] = self.payload["capturedAt"]
        self.assertEqual(self.request()[0], 409)
        with self.assertRaises(ValueError):
            fetch_snapshot(self.url, self.token)

    def test_client_rejects_insecure_remote_and_bad_token(self):
        with self.assertRaises(ValueError):
            fetch_snapshot("http://example.com", self.token)
        with self.assertRaises(ValueError):
            fetch_snapshot(self.url, "short")
