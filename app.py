"""Settlement Live Checker Pro (v2)

Potrebno: streamlit>=1.37, pandas, requests, rapidfuzz  (vidi requirements.txt)
Secrets (.streamlit/secrets.toml):
    APP_PASSWORD = "nova-jaka-lozinka"
    APISPORTS_KEY = "tvoj-api-kljuc"        # opciono
"""
import hmac
import io
import json
import math
import os
import re
import struct
import time
import unicodedata
import wave
from datetime import date

import pandas as pd
import requests
import streamlit as st
from rapidfuzz import fuzz

st.set_page_config(page_title="Settlement Live Checker Pro", page_icon="⚽", layout="wide")

# ==========================================
# 0. KONSTANTE
# ==========================================
STATE_FILE = os.environ.get("SETTLEMENT_STATE_FILE", "settlement_state.json")
API_URL = "https://v3.football.api-sports.io/fixtures"
FINISHED = {"FT", "AET", "PEN"}
SKIP_STATUSES = {"NS", "TBD", "PST", "CANC"}
QUALIFIERS = {"u17", "u18", "u19", "u20", "u21", "u23", "w", "women", "ii", "b", "reserves"}
IGNORE_TOKENS = {"A", "M"}
BASE_ALIASES = {
    "red star": "crvena zvezda",
    "man utd": "manchester united",
    "man city": "manchester city",
    "partizan": "partizan beograd",
    "inter": "inter milan",
    "ac milan": "milan",
}
SOUNDS = {
    "Standardni beep": [(880, 0.25), (0, 0.1), (880, 0.25)],
    "Kratki ping": [(1320, 0.18)],
    "Upozorenje / Sirena": [(700, 0.3), (1000, 0.3)] * 3,
}
STATUS_RANK = {"MISMATCH (NESLAGANJE)": 0, "ČEKA POTVRDU": 1, "NEMA PODATAKA (N/A)": 2,
               "SISTEM BEZ REZULTATA": 3, "OK": 4}


def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default


def g(d, *path, default=None):
    """Bezbedno čitanje ugnježdenih ključeva (None -> default)."""
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


# ==========================================
# 1. AUTORIZACIJA
# ==========================================
def check_password():
    if st.session_state.get("authenticated"):
        return True
    expected = str(get_secret("APP_PASSWORD"))
    if not expected:
        st.error("APP_PASSWORD nije podešen u .streamlit/secrets.toml")
        return False
    st.title("🔒 Prijava na sistem")
    with st.form("login"):
        pwd = st.text_input("Lozinka:", type="password")
        ok = st.form_submit_button("Prijavi se")
    if ok:
        if hmac.compare_digest(pwd.encode(), expected.encode()):
            st.session_state["authenticated"] = True
            st.rerun()
        time.sleep(1.5)  # usporava pogađanje
        st.error("Netačna lozinka!")
    return False


if not check_password():
    st.stop()


# ==========================================
# 2. TRAJNO STANJE (override, aliasi, incidenti)
# ==========================================
def load_store():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    return {k: d.get(k, {}) for k in ("overrides", "aliases", "incidents")}


def save_store():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st.session_state["store"], f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        st.toast(f"Čuvanje stanja nije uspelo: {e}")


if "store" not in st.session_state:
    st.session_state["store"] = load_store()
for _k, _v in {"process_triggered": False, "refresh_nonce": 0, "pending": {}}.items():
    st.session_state.setdefault(_k, _v)


# ==========================================
# 3. ZVUK (generisan lokalno, bez spoljnih linkova)
# ==========================================
@st.cache_resource
def make_wav(name):
    rate, frames = 22050, bytearray()
    for freq, dur in SOUNDS[name]:
        for i in range(int(rate * dur)):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate)) if freq else 0
            frames += struct.pack("<h", v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ==========================================
# 4. NORMALIZACIJA I POREĐENJE TIMOVA
# ==========================================
def strip_accents(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def clean_name(name):
    n = strip_accents(name).lower()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\b(fc|fk|cd|sc|club)\b", " ", n)  # u19/u21/sporting se NE brišu
    return re.sub(r"\s+", " ", n).strip()


def normalize_team_name(name):
    c = clean_name(name)
    return st.session_state["store"]["aliases"].get(c) or BASE_ALIASES.get(c, c)


def same_qualifiers(a, b):
    return (set(a.split()) & QUALIFIERS) == (set(b.split()) & QUALIFIERS)


def find_match(nh, na, index, threshold):
    """Vraća (fixture, skor, dvosmisleno). Domaćin-domaćin i gost-gost, isti U/W/B nastavci."""
    scored = []
    for fx in index:
        if not (same_qualifiers(nh, fx["nh"]) and same_qualifiers(na, fx["na"])):
            continue
        sh = fuzz.token_sort_ratio(nh, fx["nh"])
        sa = fuzz.token_sort_ratio(na, fx["na"])
        if sh >= threshold and sa >= threshold:
            scored.append(((sh + sa) / 2, fx))
    if not scored:
        return None, 0, False
    scored.sort(key=lambda t: t[0], reverse=True)
    ambiguous = len(scored) > 1 and scored[0][0] - scored[1][0] < 3
    return scored[0][1], scored[0][0], ambiguous


def find_candidate(m, index):
    nh, na = normalize_team_name(m["Home"]), normalize_team_name(m["Away"])
    best, best_s = None, 60
    for fx in index:
        s = (fuzz.token_sort_ratio(nh, fx["nh"]) + fuzz.token_sort_ratio(na, fx["na"])) / 2
        if s > best_s:
            best, best_s = fx, s
    return best


def apply_override(m, fx):
    """Trajno spaja meč sa fixture ID-om i uči sinonime."""
    store = st.session_state["store"]
    store["overrides"][m["ID"]] = {"fixture_id": fx["id"], "label": f"{fx['home']} - {fx['away']}"}
    for mine, theirs in ((m["Home"], fx["home"]), (m["Away"], fx["away"])):
        a, b = clean_name(mine), clean_name(theirs)
        if a and b and a != b and mine not in ("Domaćin", "Gost"):
            store["aliases"][a] = b
    save_store()


# ==========================================
# 5. PARSER KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    text = text.replace("\t", "\n").replace("\r", "")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]
    id_pos = [i for i, ln in enumerate(lines) if re.match(r"^\d{4,6}$", ln)]
    matches = []

    for n, idx in enumerate(id_pos):
        end = min(idx + 18, len(lines))
        if n + 1 < len(id_pos):  # blok ne sme zaći u sledeći meč
            end = min(end, max(id_pos[n + 1] - 1, idx + 1))
        block = lines[idx + 1:end]
        league = lines[idx - 1] if idx > 0 else "Nepoznata liga"

        scores, ht, teams = [], "N/A", []
        for item in block:
            if re.match(r"^\d+:\d+$", item):
                ht = item
            elif item.isdigit() and len(item) <= 2:
                scores.append(item)
            elif (not item.isdigit() and item not in IGNORE_TOKENS and ":" not in item
                  and len(item) > 1 and item != league):
                teams.append(item)

        home = teams[0] if len(teams) > 0 else "Domaćin"
        away = teams[1] if len(teams) > 1 else "Gost"
        matches.append({
            "ID": lines[idx],
            "Liga": league,
            "Home": home,
            "Away": away,
            "Meč": f"{home} - {away}",
            "Moj Sistem Rezultat": f"{scores[0]}:{scores[1]}" if len(scores) >= 2 else "N/A",
            "Score2 (HT)": ht,
            "Oznaka": "A" if "A" in block else "M",
        })
    return matches


# ==========================================
# 6. API POZIVI
# ==========================================
def _request(api_key, params):
    r = requests.get(API_URL, headers={"x-apisports-key": api_key}, params=params, timeout=8)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):  # API-Sports greške često dolaze sa HTTP 200
        raise RuntimeError(str(body["errors"]))
    return body.get("response", []), r.headers.get("x-ratelimit-requests-remaining", "N/A")


# Izuzeci se ne keširaju. 'nonce' forsira svež poziv samo za ovu sesiju.
@st.cache_data(ttl=15, show_spinner=False)
def _fetch_live(api_key, nonce):
    return _request(api_key, {"live": "all"})


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_date(api_key, day, nonce):
    return _request(api_key, {"date": day, "timezone": "Europe/Belgrade"})


def load_fixtures(api_key, include_finished, day, nonce):
    merged, remaining, errors = {}, "N/A", []
    calls = [("live", lambda: _fetch_live(api_key, nonce))]
    if include_finished:  # prvo datum, pa live da live pregazi iste mečeve
        calls.insert(0, ("datum", lambda: _fetch_date(api_key, day, nonce)))
    for name, fn in calls:
        try:
            data, remaining = fn()
            for fx in data:
                merged[g(fx, "fixture", "id")] = fx
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            errors.append("Prekoračen dnevni limit API zahteva!" if code == 429 else f"{name}: HTTP {code}")
        except Exception as e:
            errors.append(f"{name}: {e}")
    return list(merged.values()), remaining, errors


def build_index(fixtures, use_90):
    idx = []
    for fx in fixtures:
        short = g(fx, "fixture", "status", "short", default="")
        if short in SKIP_STATUSES:
            continue
        if use_90 and short in {"AET", "PEN"}:
            gh, ga = g(fx, "score", "fulltime", "home", default=0), g(fx, "score", "fulltime", "away", default=0)
        else:
            gh, ga = g(fx, "goals", "home", default=0), g(fx, "goals", "away", default=0)
        elapsed = g(fx, "fixture", "status", "elapsed")
        home, away = g(fx, "teams", "home", "name", default=""), g(fx, "teams", "away", "name", default="")
        idx.append({
            "id": g(fx, "fixture", "id"),
            "liga": g(fx, "league", "name", default=""),
            "home": home, "away": away,
            "nh": normalize_team_name(home), "na": normalize_team_name(away),
            "score": f"{gh}:{ga}",
            "short": short,
            "status": f"{short} {elapsed}'" if elapsed and short not in FINISHED else short,
        })
    return idx


# ==========================================
# 7. INCIDENTI (novo -> potvrđeno -> rešeno)
# ==========================================
def ack_incident(key):
    inc = st.session_state["store"]["incidents"].get(key)
    if inc:
        inc["stanje"] = "potvrđeno"
        inc["operater"] = st.session_state.get("operator", "").strip()
        save_store()


def ack_all():
    for key, inc in st.session_state["store"]["incidents"].items():
        if inc["stanje"] == "novo":
            ack_incident(key)


def clear_resolved():
    store = st.session_state["store"]
    store["incidents"] = {k: v for k, v in store["incidents"].items() if v["stanje"] != "rešeno"}
    save_store()


def clear_overrides():
    st.session_state["store"]["overrides"] = {}
    save_store()


def highlight_status(val):
    return {
        "MISMATCH (NESLAGANJE)": "background-color:#d32f2f;color:white;font-weight:bold;",
        "ČEKA POTVRDU": "background-color:#f9a825;color:black;font-weight:bold;",
        "NEMA PODATAKA (N/A)": "background-color:#4a4a4a;color:#d1d1d1;",
        "SISTEM BEZ REZULTATA": "background-color:#6a1b9a;color:white;",
        "OK": "background-color:#2e7d32;color:white;font-weight:bold;",
    }.get(val, "")


# ==========================================
# 8. SIDEBAR
# ==========================================
st.title("⚽ Settlement Live Checker Pro")
st.sidebar.header("⚙️ Podešavanja")

api_key_input = st.sidebar.text_input("API-Sports ključ (opciono, zamenjuje secrets):", type="password")
api_key = (api_key_input or str(get_secret("APISPORTS_KEY"))).strip()

st.sidebar.subheader("📡 Izvor podataka")
include_finished = st.sidebar.checkbox("Uključi i završene mečeve (po datumu)", value=True)
day = st.sidebar.date_input("Datum:", value=date.today()).isoformat() if include_finished else ""
use_90 = st.sidebar.checkbox("Za AET/PEN koristi rezultat posle 90 min", value=False)
threshold = st.sidebar.slider("Prag poklapanja imena timova:", 70, 95, 80, 5)

st.sidebar.subheader("⏱️ Tolerancija kašnjenja")
grace = st.sidebar.slider("Neslaganje je alarm tek posle (s):", 0, 300, 60, 15,
                          help="Završeni mečevi (FT/AET/PEN) se ne odlažu.")

st.sidebar.subheader("🔄 Osvežavanje")
refresh_mode = st.sidebar.radio("Režim:", ["Manuelno (Ručno)", "Automatsko"], index=0)
auto_interval = 60
if refresh_mode == "Automatsko":
    auto_interval = st.sidebar.slider("Interval (sekunde):", 15, 300, 60, 15)
    st.sidebar.warning("⚠️ Troši do 2 API zahteva po ciklusu.")

st.sidebar.subheader("🔊 Zvučna upozorenja")
sound_alert = st.sidebar.checkbox("Zvučni alarm za NOVA neslaganja", value=True)
sound_choice = st.sidebar.selectbox("Vrsta zvuka:", list(SOUNDS.keys()))
if st.sidebar.button("▶️ Probaj zvuk"):
    st.sidebar.audio(make_wav(sound_choice), format="audio/wav", autoplay=True)

st.sidebar.subheader("👤 Operater")
st.sidebar.text_input("Ime (upisuje se pri 'Preuzeo sam'):", key="operator")

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()


# ==========================================
# 9. UNOS TEKSTA
# ==========================================
def clear_text_callback():
    st.session_state["raw_text_input"] = ""
    st.session_state["process_triggered"] = False


def trigger_callback():
    st.session_state["process_triggered"] = True
    st.session_state["refresh_nonce"] += 1  # svež API poziv za ovu sesiju


raw_text = st.text_area("Zalepite tabelu iz vašeg programa (Ctrl + V):", height=160, key="raw_text_input")
col1, col2, _ = st.columns([2, 1, 3])
col1.button("🚀 Učitaj i proveri tabelu", type="primary", use_container_width=True, on_click=trigger_callback)
col2.button("🗑️ Očisti tekst", on_click=clear_text_callback, use_container_width=True)


# ==========================================
# 10. REZULTATI (fragment: osvežava se sam, UI ostaje živ)
# ==========================================
cfg = dict(api_key=api_key, include_finished=include_finished, day=day, use_90=use_90,
           threshold=threshold, grace=grace, sound_alert=sound_alert, sound_choice=sound_choice)
run_every = auto_interval if (refresh_mode == "Automatsko" and st.session_state["process_triggered"]) else None


@st.fragment(run_every=run_every)
def results_view(text, cfg):
    store = st.session_state["store"]
    inc_store, overrides = store["incidents"], store["overrides"]
    index = []

    if text and st.session_state["process_triggered"]:
        parsed = parse_copied_data(text)
        if not parsed:
            st.warning("⚠️ Nije prepoznata struktura teksta. Proverite uslov kopiranja.")
        else:
            fixtures, remaining, errors = [], "N/A", []
            if cfg["api_key"]:
                fixtures, remaining, errors = load_fixtures(
                    cfg["api_key"], cfg["include_finished"], cfg["day"], st.session_state["refresh_nonce"])
            else:
                st.warning("Nedostaje API ključ (secrets ili polje u sidebar-u).")
            for e in errors:
                st.error(f"🚨 {e}")
            if remaining != "N/A":
                st.caption(f"📊 Preostalo API zahteva: **{remaining}**")

            index = build_index(fixtures, cfg["use_90"])
            by_id = {fx["id"]: fx for fx in index}
            pending, now = st.session_state["pending"], time.time()
            results, suggestions = [], []
            current_keys, ids_with_data, changed = set(), set(), False
            counts = {"ok": 0, "mismatch": 0, "wait": 0, "na": 0}

            for m in parsed:
                mid, my = m["ID"], m["Moj Sistem Rezultat"]
                ov = overrides.get(mid)
                note, conf, fx = "", 0, None
                if ov:
                    fx, conf, note = by_id.get(ov["fixture_id"]), 100, "ručno"
                    if fx is None:
                        note = "ručno spojeno, nema u feedu"
                else:
                    fx, conf, amb = find_match(normalize_team_name(m["Home"]), normalize_team_name(m["Away"]),
                                               index, cfg["threshold"])
                    if amb:
                        fx, note = None, "dvosmisleno poklapanje"

                inc_state = ""
                if fx is None:
                    status, ext_score, ext_status = "NEMA PODATAKA (N/A)", "N/A", note or "N/A"
                    counts["na"] += 1
                    pending.pop(mid, None)
                    cand = find_candidate(m, index)
                    if cand and not ov:
                        suggestions.append((m, cand))
                else:
                    ids_with_data.add(mid)
                    ext_score = fx["score"]
                    ext_status = fx["status"] + (f" ({note})" if note else "")
                    if my == "N/A":
                        status = "SISTEM BEZ REZULTATA"
                        counts["na"] += 1
                    elif my == ext_score:
                        status = "OK"
                        counts["ok"] += 1
                        pending.pop(mid, None)
                    else:
                        key = f"{mid}|{my}|{ext_score}"
                        p = pending.get(mid)
                        if not p or p["key"] != key:
                            p = pending[mid] = {"key": key, "since": now}
                        left = cfg["grace"] - (now - p["since"])
                        if fx["short"] in FINISHED or left <= 0:
                            status = "MISMATCH (NESLAGANJE)"
                            counts["mismatch"] += 1
                            current_keys.add(key)
                            inc = inc_store.get(key)
                            if inc is None or inc["stanje"] == "rešeno":
                                inc_store[key] = {
                                    "id": mid, "liga": m["Liga"], "meč": m["Meč"], "sistem": my,
                                    "live": ext_score, "otkriveno": time.strftime("%d.%m %H:%M:%S"),
                                    "stanje": "novo", "operater": "", "razreseno": "", "alarmed": False}
                                changed = True
                            inc_state = inc_store[key]["stanje"]
                        else:
                            status = "ČEKA POTVRDU"
                            counts["wait"] += 1
                            ext_status += f" (još {int(left)}s)"

                results.append({
                    "Status": status, "Incident": inc_state, "ID": mid, "Oznaka": m["Oznaka"],
                    "Liga": m["Liga"], "Meč": m["Meč"], "Tvoj Sistem": my,
                    "Score2 (HT)": m["Score2 (HT)"], "Teren / Live Feed": ext_score,
                    "Status Meča": ext_status, "Pouzdanost": int(conf)})

            # Incidenti kojima se rezultat izjednačio (ili promenio) -> rešeno
            for key, inc in inc_store.items():
                if inc["stanje"] != "rešeno" and inc["id"] in ids_with_data and key not in current_keys:
                    inc["stanje"], inc["razreseno"] = "rešeno", time.strftime("%d.%m %H:%M:%S")
                    changed = True

            # Zvuk samo za nove, još neoglašene incidente
            fresh = [i for i in inc_store.values() if i["stanje"] == "novo" and not i.get("alarmed")]
            if fresh and cfg["sound_alert"]:
                st.audio(make_wav(cfg["sound_choice"]), format="audio/wav", autoplay=True)
            for i in fresh:
                i["alarmed"], changed = True, True
            if changed:
                save_store()

            # --- Aktivna neslaganja ---
            active = {k: v for k, v in inc_store.items() if v["stanje"] != "rešeno"}
            if active:
                n_new = sum(v["stanje"] == "novo" for v in active.values())
                (st.error if n_new else st.warning)(
                    f"🚨 Nepreuzeta neslaganja: {n_new}" if n_new else "🟡 Sva aktivna neslaganja su preuzeta.")
                with st.container(border=True):
                    for k, v in active.items():
                        c1, c2, c3 = st.columns([5, 2, 2])
                        c1.write(f"**ID {v['id']}** · {v['meč']} · sistem **{v['sistem']}**, "
                                 f"live **{v['live']}** · {v['otkriveno']}")
                        c2.write("🔴 novo" if v["stanje"] == "novo" else f"🟡 preuzeo: {v['operater'] or '—'}")
                        if v["stanje"] == "novo":
                            c3.button("✋ Preuzeo sam", key=f"ack_{k}", on_click=ack_incident, args=(k,))
                    if n_new > 1:
                        st.button("✋ Preuzeo sve", on_click=ack_all)

            # --- Metrike ---
            df_full = pd.DataFrame(results)
            df_full["_r"] = df_full["Status"].map(STATUS_RANK)
            df_full = df_full.sort_values("_r", kind="stable").drop(columns="_r")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Ukupno mečeva", len(df_full))
            m2.metric("Usklađeno (OK)", counts["ok"])
            m3.metric("Neslaganja", counts["mismatch"], delta_color="inverse")
            m4.metric("Čeka potvrdu", counts["wait"])
            m5.metric("Nema podataka", counts["na"])

            # --- Filteri ---
            st.markdown("---")
            cs, cf = st.columns([2, 2])
            q = cs.text_input("🔍 Brza pretraga (ID, klub ili liga):", "", key="search_q")
            flt = cf.radio("Filtriraj po statusu:", ["Svi mečevi", "Neslaganja (+ čeka potvrdu)", "Nema podataka"],
                           horizontal=True, key="status_filter")
            df = df_full
            if flt.startswith("Neslaganja"):
                df = df[df["Status"].isin(["MISMATCH (NESLAGANJE)", "ČEKA POTVRDU"])]
            elif flt == "Nema podataka":
                df = df[df["Status"].isin(["NEMA PODATAKA (N/A)", "SISTEM BEZ REZULTATA"])]
            if q:
                df = df[df["ID"].astype(str).str.contains(q, case=False, regex=False)
                        | df["Meč"].str.contains(q, case=False, regex=False)
                        | df["Liga"].str.contains(q, case=False, regex=False)]

            st.subheader("📊 Pregled utakmica")
            styler = df.style
            styler = (styler.map if hasattr(styler, "map") else styler.applymap)(highlight_status, subset=["Status"])
            st.dataframe(styler, use_container_width=True, hide_index=True)

            # --- Ručno spajanje + predlozi ---
            with st.expander(f"🛠️ Ručno spajanje ({len(overrides)} sačuvanih)"):
                if index:
                    mby = {m["ID"]: m for m in parsed}
                    sel_m = st.selectbox("Meč iz tvog sistema:", [m["ID"] for m in parsed],
                                         format_func=lambda i: f"{i} – {mby[i]['Meč']}", key="ov_match")
                    sel_f = st.selectbox("Utakmica na API-ju:", [f["id"] for f in index],
                                         format_func=lambda i: f"{by_id[i]['home']} - {by_id[i]['away']} "
                                                               f"({by_id[i]['liga']}, {by_id[i]['status']})",
                                         key="ov_fix")
                    st.button("💾 Sačuvaj spajanje", on_click=lambda: apply_override(mby[sel_m], by_id[sel_f]))
                else:
                    st.info("Nema učitanih utakmica sa API-ja.")
                if overrides:
                    st.button("Obriši sva ručna spajanja", on_click=clear_overrides)

            if suggestions:
                with st.expander("💡 Predlozi za spajanje (jedan klik)", expanded=True):
                    for m, cand in suggestions:
                        c1, c2, c3 = st.columns([2, 3, 2])
                        c1.write(f"**ID {m['ID']}**: {m['Meč']}")
                        c2.write(f"API kandidat: **{cand['home']} - {cand['away']}** ({cand['status']})")
                        c3.button("➕ Spoji", key=f"sug_{m['ID']}", on_click=apply_override, args=(m, cand))

            st.download_button("📥 Preuzmi izveštaj (CSV, svi mečevi)",
                               df_full.to_csv(index=False).encode("utf-8"),
                               file_name="settlement_report.csv", mime="text/csv")

    # --- Arhiva incidenata (prikazuje se i bez učitane tabele) ---
    if inc_store:
        st.markdown("---")
        st.subheader("📜 Arhiva neslaganja")
        st.caption("Pamti se i posle osvežavanja stranice (settlement_state.json).")
        arch = pd.DataFrame(inc_store.values())[
            ["otkriveno", "id", "liga", "meč", "sistem", "live", "stanje", "operater", "razreseno"]]
        arch.columns = ["Otkriveno", "ID", "Liga", "Meč", "Tvoj Sistem", "Live", "Stanje", "Preuzeo", "Rešeno"]
        st.dataframe(arch.iloc[::-1], use_container_width=True, hide_index=True)
        st.button("🗑️ Obriši rešena neslaganja", on_click=clear_resolved)

    # --- Live monitor ---
    if index:
        with st.expander("📺 Sve utakmice trenutno dostupne sa API-ja"):
            st.dataframe(pd.DataFrame([{"Liga": f["liga"], "Domaćin": f["home"], "Gost": f["away"],
                                        "Rezultat": f["score"], "Status": f["status"]} for f in index]),
                         use_container_width=True, hide_index=True)


results_view(raw_text, cfg)
