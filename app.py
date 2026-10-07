import streamlit as st
import pandas as pd
import re
import requests
import time
import json
from thefuzz import fuzz

# ==========================================
# 1. PODEŠAVANJE STRANICE I AUTORIZACIJA
# ==========================================
st.set_page_config(
    page_title="Settlement Live Checker Pro", 
    page_icon="⚽", 
    layout="wide"
)

PASSWORD = "settlement123"

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔒 Prijava na sistem")
        pwd_input = st.text_input("Lozinka:", type="password")
        if st.button("Prijavi se"):
            if pwd_input == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Netačna lozinka!")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. AUDIO ALARM (STABILAN ZVUK)
# ==========================================
def play_sound_alarm():
    audio_html = """
        <audio autoplay style="display:none;">
            <source src="https://media.geeksforgeeks.org/wp-content/uploads/20190531135120/beep.mp3" type="audio/mpeg">
        </audio>
    """
    st.markdown(audio_html, unsafe_allow_html=True)

# ==========================================
# 3. REČNIK SINONIMA I NORMALIZACIJA TIMOVA
# ==========================================
TEAM_ALIASES = {
    "red star": "crvena zvezda",
    "man utd": "manchester united",
    "man city": "manchester city",
    "partizan": "partizan beograd",
    "inter": "inter milan",
    "ac milan": "milan",
    "real madrid": "real madrid",
    "atletico madrid": "atletico madrid"
}

def normalize_team_name(name):
    """Sve malim slovima, uklanjanje prefiksa/sufiksa i zamena iz rečnika sinonima."""
    name = name.lower().strip()
    name = re.sub(r'\b(fc|fk|u19|u21|club|cd|sc|sp|sporting)\b', '', name, flags=re.IGNORECASE).strip()
    return TEAM_ALIASES.get(name, name)

def are_teams_matching(home1, away1, home2, away2):
    """
    Stroža provera: Obavezno i Domaćin I Gost moraju preći prag od 75% podudaranja
    kako bi se izbeglo pogrešno spajanje gradskih rivala ili kluba sa sličnim imenom.
    """
    h1 = normalize_team_name(home1)
    a1 = normalize_team_name(away1)
    h2 = normalize_team_name(home2)
    a2 = normalize_team_name(away2)
    
    sim_home = fuzz.partial_ratio(h1, h2)
    sim_away = fuzz.partial_ratio(a1, a2)
    
    return sim_home >= 75 and sim_away >= 75

# ==========================================
# 4. PARSER KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    text = text.replace('\t', '\n').replace('\r', '')
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.split('\n') if line.strip()]
    matches = []
    
    for idx, line in enumerate(lines):
        if re.match(r'^\d{4,6}$', line):
            try:
                match_id = line
                league = lines[idx - 1] if idx - 1 >= 0 else "Nepoznata liga"
                block = lines[idx + 1 : min(idx + 18, len(lines))]
                
                scores_found = []
                half_time_score = "N/A"
                team_names = []
                
                for item in block:
                    if re.match(r'^\d+:\d+$', item):
                        half_time_score = item
                        continue
                        
                    if item.isdigit() and len(item) <= 2:
                        scores_found.append(item)
                        continue
                        
                    if not item.isdigit() and item not in ["A", "M"] and ":" not in item:
                        if len(item) > 1 and item != league:
                            team_names.append(item)

                if len(scores_found) >= 2:
                    my_score = f"{scores_found[0]}:{scores_found[1]}"
                else:
                    my_score = "N/A"
                    
                home_team = team_names[0] if len(team_names) > 0 else "Domaćin"
                away_team = team_names[1] if len(team_names) > 1 else "Gost"
                
                auto_check = "A" if "A" in block else ("M" if "M" in block else "M")
                
                matches.append({
                    "ID": match_id,
                    "Liga": league,
                    "Home": home_team,
                    "Away": away_team,
                    "Meč": f"{home_team} - {away_team}",
                    "Moj Sistem Rezultat": my_score,
                    "Score2 (HT)": half_time_score,
                    "Oznaka": auto_check
                })
            except Exception:
                continue
                
    return matches

# ==========================================
# 5. API POZIVI I DATA FETCHING
# ==========================================
@st.cache_data(ttl=86400)
def fetch_all_live_fixtures(api_key):
    if not api_key:
        return [], "N/A"
        
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": api_key.strip()}
    params = {"live": "all"}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=6)
        remaining_requests = res.headers.get("x-ratelimit-requests-remaining", "N/A")
        
        if res.status_code == 200:
            return res.json().get("response", []), remaining_requests
        elif res.status_code == 429:
            st.error("🚨 Prekoračen je dnevni limit API zahteva!")
            return [], remaining_requests
    except Exception as e:
        st.error(f"Mrežna greška: {e}")
    return [], "N/A"

def fetch_external_live_data(home, away, match_id, live_fixtures, manual_overrides):
    if not home or not away or not live_fixtures:
        return {"ext_score": "N/A", "status": "N/A"}

    # 1. PROVERA RUČNOG MAPIRANJA (MANUAL OVERRIDE)
    if match_id in manual_overrides and manual_overrides[match_id].get("override_search"):
        search_term = manual_overrides[match_id]["override_search"].lower()
        for fix in live_fixtures:
            ext_home = fix.get("teams", {}).get("home", {}).get("name", "")
            ext_away = fix.get("teams", {}).get("away", {}).get("name", "")
            full_fixture_str = f"{ext_home} {ext_away}".lower()
            
            if search_term in full_fixture_str:
                gh = fix.get("goals", {}).get("home", 0) or 0
                ga = fix.get("goals", {}).get("away", 0) or 0
                elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", "Live")
                return {
                    "ext_score": f"{gh}:{ga}", 
                    "status": f"{elapsed}' (Ručno spojeno)"
                }

    # 2. AUTOMATSKO SPAJANJE SA DVOSTRUKOM PROVEROM (75%+)
    for fix in live_fixtures:
        ext_home = fix.get("teams", {}).get("home", {}).get("name", "")
        ext_away = fix.get("teams", {}).get("away", {}).get("name", "")
        
        if are_teams_matching(home, away, ext_home, ext_away):
            gh = fix.get("goals", {}).get("home", 0) or 0
            ga = fix.get("goals", {}).get("away", 0) or 0
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", "Live")
            return {
                "ext_score": f"{gh}:{ga}", 
                "status": f"{elapsed}' (API-Sports)"
            }

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 6. INTERFEJS I GLAVNA LOGIKA
# ==========================================
st.title("⚽ Settlement Live Checker Pro")

st.sidebar.header("⚙️ Podešavanja")

default_key = ""
if "APISPORTS_KEY" in st.secrets:
    default_key = st.secrets["APISPORTS_KEY"]

api_key_input = st.sidebar.text_input(
    "API-Sports Ključ:", 
    value=default_key, 
    type="password"
)

st.sidebar.subheader("🔄 Osvežavanje")
refresh_mode = st.sidebar.radio(
    "Režim osvežavanja:",
    ["Manuelno (Ručno)", "Automatsko"],
    index=0
)

auto_interval = 60
if refresh_mode == "Automatsko":
    auto_interval = st.sidebar.slider("Interval (sekunde):", 15, 300, 60, 15)
    st.sidebar.warning(f"⚠️ Troši 1 API zahtev svakih {auto_interval}s.")

only_mismatches = st.sidebar.checkbox("Prikaži samo neslaganja", value=False)
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)

# MANUAL OVERRIDE SEKCIJA U SAJDBARU
st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ Ručno spajanje (Override)")
st.sidebar.caption("Ako sistem promaši tim, upišite ID meča i deo zvaničnog imena tima sa API-ja:")

override_match_id = st.sidebar.text_input("ID meča iz tvog sistema (npr. 1234):")
override_team_search = st.sidebar.text_input("Naziv tima na API-ju (npr. Red Star):")

if "manual_overrides" not in st.session_state:
    st.session_state["manual_overrides"] = {}

if st.sidebar.button("Sačuvaj ručno spajanje"):
    if override_match_id and override_team_search:
        st.session_state["manual_overrides"][override_match_id.strip()] = {
            "override_search": override_team_search.strip()
        }
        st.sidebar.success(f"Ručno spajanje dodato za ID: {override_match_id}")
        st.rerun()

if st.session_state["manual_overrides"]:
    if st.sidebar.button("Obriši sva ručna spajanja"):
        st.session_state["manual_overrides"] = {}
        st.rerun()

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()

# UNOS TEKSTA
raw_text = st.text_area("Zalepite tabelu iz vašeg programa (Ctrl + V):", height=160)

if refresh_mode == "Manuelno (Ručno)":
    col1, _ = st.columns([1, 3])
    with col1:
        if st.button("🔄 Osveži live feed", type="primary"):
            st.cache_data.clear()
            st.toast("Podaci osveženi!", icon="🚀")
else:
    st.cache_data.clear()
    time.sleep(0.1)

if raw_text:
    parsed_matches = parse_copied_data(raw_text)
    
    if not parsed_matches:
        st.warning("⚠️ Nije prepoznata struktura teksta.")
    else:
        live_games, remaining_reqs = fetch_all_live_fixtures(api_key_input) if api_key_input else ([], "N/A")
        
        if remaining_reqs != "N/A":
            st.sidebar.info(f"📊 Preostalo API zahteva: **{remaining_reqs}**")
        
        results = []
        has_mismatch = False
        count_ok, count_mismatch, count_na = 0, 0, 0
        
        for m in parsed_matches:
            ext_data = fetch_external_live_data(
                m["Home"], 
                m["Away"], 
                m["ID"], 
                live_games, 
                st.session_state["manual_overrides"]
            )
            
            ext_score = ext_data["ext_score"]
            my_score = m["Moj Sistem Rezultat"]
            
            if ext_score == "N/A":
                status_check = "NEMA PODATAKA (N/A)"
                count_na += 1
            elif my_score != ext_score:
                status_check = "MISMATCH (NESLAGANJE)"
                has_mismatch = True
                count_mismatch += 1
            else:
                status_check = "OK"
                count_ok += 1
            
            results.append({
                "Status": status_check,
                "ID": m["ID"],
                "Oznaka": m["Oznaka"],
                "Liga": m["Liga"],
                "Meč": m["Meč"],
                "Tvoj Sistem": my_score,
                "Score2 (HT)": m["Score2 (HT)"],
                "Teren / Live Feed": ext_score,
                "Status Meča": ext_data["status"]
            })
            
        df = pd.DataFrame(results)
        
        # STATISTIKA NA VRHU
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ukupno mečeva", len(df))
        m2.metric("Usklađeno (OK)", count_ok)
        m3.metric("Neslaganja (MISMATCH)", count_mismatch, delta_color="inverse")
        m4.metric("Nema podataka (N/A)", count_na)
        
        if only_mismatches:
            df = df[df["Status"] == "MISMATCH (NESLAGANJE)"]
            
        if has_mismatch and sound_alert:
            play_sound_alarm()
            st.error("🚨 DETEKTOVANO JE NESLAGANJE REZULTATA!")
            
        def highlight_status(val):
            if val == "MISMATCH (NESLAGANJE)":
                return 'background-color: #d32f2f; color: white; font-weight: bold;'
            elif val == "NEMA PODATAKA (N/A)":
                return 'background-color: #4a4a4a; color: #d1d1d1;'
            elif val == "OK":
                return 'background-color: #2e7d32; color: white; font-weight: bold;'
            return ''

        st.subheader("📊 Pregled utakmica")
        st.dataframe(
            df.style.map(highlight_status, subset=['Status']), 
            use_container_width=True
        )

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Preuzmi izveštaj (CSV)",
            data=csv,
            file_name="settlement_mismatch_report.csv",
            mime="text/csv"
        )

        with st.expander("🔍 Dijagnostika i sirovi parsirani podaci"):
            st.json(parsed_matches)

if refresh_mode == "Automatsko":
    time.sleep(auto_interval)
    st.rerun()
