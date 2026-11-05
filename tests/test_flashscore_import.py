import json
import unittest
from datetime import datetime, timezone, timedelta

from flashscore_import import load_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.payload = {"schema": "settlementai.flashscore.v1", "capturedAt": self.now.isoformat(),
                        "matches": [{"id": "g_1_test", "home": "Partizan", "away": "Radnicki", "homeScore": "2", "awayScore": "1"}]}

    def load(self):
        return load_snapshot(json.dumps(self.payload).encode(), now=self.now)

    def test_fixture_adapter(self):
        fixtures, timestamp = self.load()
        self.assertEqual(fixtures[0]["goals"], {"home": 2, "away": 1})
        self.assertEqual(fixtures[0]["fixture"]["id"], "g_1_test")
        self.assertEqual(timestamp, self.now.timestamp())

    def test_stale_and_future_snapshots_rejected(self):
        for seconds in (-301, 31):
            self.payload["capturedAt"] = (self.now + timedelta(seconds=seconds)).isoformat()
            with self.assertRaises(ValueError):
                self.load()

    def test_invalid_scores_duplicates_and_empty_snapshot_rejected(self):
        for score in (None, True, -1, "-1", "1:0", "", "١", "9999"):
            self.payload["matches"][0]["homeScore"] = score
            with self.assertRaises(ValueError):
                self.load()
        self.payload["matches"][0]["homeScore"] = "1"
        self.payload["matches"] *= 2
        with self.assertRaises(ValueError):
            self.load()
        self.payload["matches"] = []
        with self.assertRaises(ValueError):
            self.load()

    def test_malformed_input_rejected(self):
        for data in (b"not JSON", b"[]", b"{}", b'\xff'):
            with self.assertRaises(ValueError):
                load_snapshot(data)


if __name__ == "__main__":
    unittest.main()
