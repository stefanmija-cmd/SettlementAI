"""Validate browser snapshots and adapt them to SettlementCheck fixtures."""
import json
from datetime import datetime, timezone


def load_snapshot(data, now=None, max_age=300):
    """Return (fixtures, capture timestamp); reject stale or malformed data."""
    if len(data) > 5_000_000:
        raise ValueError("Flashscore datoteka je prevelika (maksimum 5 MB).")
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("schema") != "settlementai.flashscore.v1":
            raise ValueError("Nepoznat Flashscore format. Koristite exportSnapshot().")
        captured = datetime.fromisoformat(payload["capturedAt"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError("Vreme snimka mora sadržati vremensku zonu.")
        current = now or datetime.now(timezone.utc)
        age = (current - captured).total_seconds()
        if age > max_age:
            raise ValueError("Flashscore snimak je stariji od 5 minuta. Izvezite i učitajte novi snimak." if max_age == 300
                             else "Flashscore veza nema sveže podatke više od 45 sekundi. Proverite browser i prijemnik.")
        if age < -30:
            raise ValueError("Flashscore snimak ima vreme u budućnosti. Proverite sat uređaja.")
        matches = payload["matches"]
        if not isinstance(matches, list) or not matches or len(matches) > 10000:
            raise ValueError("Flashscore snimak mora sadržati od 1 do 10000 mečeva.")
        fixtures, ids = [], set()
        for match in matches:
            if not isinstance(match, dict):
                raise ValueError("Neispravan Flashscore meč.")
            mid, home, away = (match[k] for k in ("id", "home", "away"))
            if not all(isinstance(v, str) and v.strip() and len(v) <= 500 for v in (mid, home, away)):
                raise ValueError("Meč mora imati ID i nazive oba tima.")
            if mid in ids:
                raise ValueError("Dupliran Flashscore ID meča.")
            ids.add(mid)
            scores = [match[k] for k in ("homeScore", "awayScore")]
            if not all(isinstance(v, str) and v.isascii() and v.isdigit() and len(v) <= 3 for v in scores):
                raise ValueError("Flashscore rezultat mora sadržati dva nenegativna cela broja.")
            fixtures.append({
                "fixture": {"id": mid, "status": {"short": "SNAPSHOT", "elapsed": None}},
                "league": {"name": "Flashscore"},
                "teams": {"home": {"name": home}, "away": {"name": away}},
                "goals": {"home": int(scores[0]), "away": int(scores[1])},
            })
        return fixtures, captured.timestamp()
    except (KeyError, TypeError, AttributeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Neispravan Flashscore JSON. Izvezite novi snimak pomoću exportSnapshot().") from exc
