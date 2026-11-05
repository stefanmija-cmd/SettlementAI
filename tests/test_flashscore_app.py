"""Exercise the real Streamlit comparison with uploaded browser snapshots."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


class FlashscoreAppTests(unittest.TestCase):
    def test_upload_compares_and_rejects_stale_data_without_api_calls(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SETTLEMENT_STATE_FILE": directory + "/state.json"}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.session_state["authenticated"] = True
            app.run()
            app.selectbox(key="provider").select("Flashscore")
            app.session_state["operator"] = "Test"
            app.session_state["raw_text_input"] = "Liga\n12345\nPartizan\nRadnicki\n2\n1"
            app.session_state["process_triggered"] = True
            payload = {"schema": "settlementai.flashscore.v1", "capturedAt": datetime.now(timezone.utc).isoformat(),
                       "matches": [{"id": "g_1_test", "home": "Partizan", "away": "Radnicki", "homeScore": "2", "awayScore": "1"}]}

            def run_upload():
                with patch.object(st.sidebar, "file_uploader", return_value=io.BytesIO(json.dumps(payload).encode())), patch("requests.get", side_effect=AssertionError("Unexpected API call")):
                    app.run()
                self.assertFalse(app.exception, [e.message for e in app.exception])

            def result():
                frames = [f.value for f in app.dataframe if "Pouzdanost" in f.value.columns]
                self.assertTrue(frames)
                return frames[0].iloc[0]

            run_upload()
            self.assertFalse(app.error)
            self.assertEqual(result()["Status"], "OK")
            self.assertEqual(result()["Rezultat"], "2:1 → 2:1")
            for slider in app.slider:
                if slider.label == "Neslaganje je alarm tek posle (s):":
                    slider.set_value(0)
            for checkbox in app.checkbox:
                if checkbox.label == "Zvučni ping za nova neslaganja":
                    checkbox.uncheck()
            payload["matches"][0]["homeScore"] = "3"
            run_upload()
            self.assertEqual(result()["Status"], "Neslaganje")
            self.assertEqual(result()["Rezultat"], "2:1 → 3:1")
            payload["matches"][0]["homeScore"] = "2"
            run_upload()
            self.assertEqual(result()["Status"], "OK")
            payload["capturedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
            run_upload()
            self.assertTrue(any("stariji od 5 minuta" in e.value for e in app.error))
