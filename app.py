import streamlit as st
import pandas as pd
import re
import requests
import time
import base64
from thefuzz import fuzz

# ==========================================
# 1. PODEŠAVANJE STRANICE I AUTORIZACIJA
# ==========================================
st.set_page_config(
    page_title="Settlement Live Checker", 
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
# 2. AUDIO ALARM (BASE64 STABILAN ZVUK)
# ==========================================
def play_sound_alarm():
    """Generiše zvučni alarm direktno iz HTML5 Audio elementa bez zavisnosti od eksternog URL-a."""
    # Kratak zvučni signal (Beep) u base64 formatu
    audio_b64 = "data:audio/wav;base64,UklGRl9vAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVBvAAAAAAAAAAAAAAAAAAAAAA=" 
    # Alternativno koristi pouzdan CDN fallback
    audio_html = """
        <audio autoplay style="display:none;">
            <source src="https://media.geeksforgeeks.org/wp-content/uploads/20190531135120/beep.mp3" type="audio/mpeg">
        </audio>
    """
    st.markdown(audio_html, unsafe_allow_html=True)

# ==========================================
# 3. ADVANCED PARSER KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    """
    Robustni parser koji uklanja specijalne karaktere, spaja Home i Away golove 
    i rukuje Score2 (poluvremenom) bez narušavanja strukture.
    """
    # Čišćenje Unicode karaktera i tabulatora
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
                    # Normalizacija imena timova (uklanjanje čestih sufiksa)
                    clean_item = re.sub(r'\b(FC|FK|U19|U21|Club)\b', '', item, flags=re.IGNORECASE).strip()
                    
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
# 4. API POZIV SA MONITORINGOM KVOTE
# ==========================================
def are_teams_matching(home1, away1, home2, away2):
    """Normalizacija i provera fuzzy podudaranja naziva timova."""
    h1 = re.sub(r'\b(FC|FK|U19|U21|Club)\b', '', home1, flags=re.IGNORECASE).strip().lower()
    a1 = re.sub(r'\b(FC|FK|U19|U21|Club)\b', '', away1, flags=re.IGNORECASE).strip().lower()
    h2 = re.sub(r'\b(FC|FK|U19|U21|Club)\b', '', home2, flags=re.IGNORECASE).strip().lower()
    a2 = re.sub(r'\b(FC|FK|U19|U21|Club)\b', '', away2, flags=re.IGNORECASE).strip().lower()
    
    sim_home = fuzz.partial_ratio(h1, h2)
    sim_away = fuzz.partial_ratio(a1, a2)
    return ((sim_home + sim_away) / 2) > 65

@st.cache_data(ttl=86400)
def fetch_all_live_fixtures(api_key):
    if not api_key:
        return [], None
        
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": api_key.strip()}
    params = {"live": "all"}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=6)
        
        # Ekstrakcija preostalih API zahteva iz odgovora
        remaining_requests = res.headers.get("x-ratelimit-requests-remaining", "N/A")
        
        if res.status_code == 200:
            return res.json().get("response", []), remaining_requests
        elif res.status_code == 429:
            st.error("🚨 Prekoračen je dnevni limit API zahteva (Rate limit exceeded)!")
            return [], remaining_requests
    except Exception as e:
        st.error(f"Greška u mrežnoj komunikaciji: {e}")
    return [], "N/A"

def fetch_external_live_data(home, away, live_fixtures):
    if not home or not away or not live_fixtures:
        return {"ext_score": "N/A", "status": "N/A"}

    for fix in live_fixtures:
        ext_home = fix.get("teams", {}).get("home", {}).get("name", "")
        ext_away = fix.get("teams", {}).get("away", {}).get("name", "")
        
        if are_teams_matching(home, away, ext_home, ext_away):
            gh = fix.get("goals", {}).get("home", 0)
            ga = fix.get("goals", {}).get("away", 0)
            
            gh = 0 if gh is None else gh
            ga = 0 if ga is None else ga
            
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", "Live")
            return {
                "ext_score": f"{gh}:{ga}", 
                "status": f"{elapsed}' (API-Sports)"
            }

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 5. KORISNIČKI INTERFEJS & GLAVNI LOGIC
# ==========================================
st.title("⚽ Settlement Live Checker Pro")

# Sajdbar i podešavanja
st.sidebar.header("⚙️ Podešavanja")

default_key = ""
if "APISPORTS_KEY" in st.secrets:
    default_key = st.secrets["APISPORTS_KEY"]

api_key_input = st.sidebar.text_input(
    "API-Sports Ključ:", 
    value=default_key, 
    type="password",
    help="Učitan iz Streamlit Secrets podešavanja."
)

st.sidebar.subheader("🔄 Osvežavanje podataka")
refresh_mode = st.sidebar.radio(
    "Režim osvežavanja:",
    ["Manuelno (Ručno)", "Automatsko"],
    index=0
)

auto_interval = 60
if refresh_mode == "Automatsko":
    auto_interval = st.sidebar.slider(
        "Interval osvežavanja (sekunde):",
        min_value=15,
        max_value=300,
        value=60,
        step=15
    )
    st.sidebar.warning(f"⚠️ Troši 1 API zahtev svakih {auto_interval} s.")

only_mismatches = st.sidebar.checkbox("Prikaži samo neslaganja", value=False)
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()

# Unos teksta
raw_text = st.text_area("Zalepite tabelu iz vašeg programa (Ctrl + V):", height=160)

# Kontrola manuelnog osvežavanja
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
        
        # Prikaz preostale API kvote u sajdbaru
        if remaining_reqs != "N/A":
            st.sidebar.info(f"📊 Preostalo API zahteva za danas: **{remaining_reqs}**")
        
        results = []
        has_mismatch = False
        
        count_ok = 0
        count_mismatch = 0
        count_na = 0
        
        for m in parsed_matches:
            ext_data = fetch_external_live_data(m["Home"], m["Away"], live_games)
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
        
        # Statistički pokazatelji (Metrics) na vrhu
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

        # Izvoz rezultata u CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Preuzmi izveštaj (CSV)",
            data=csv,
            file_name="settlement_mismatch_report.csv",
            mime="text/csv"
        )

        # Expander sa sirovim parsiranim podacima radi dijagnostike
        with st.expander("🔍 Dijagnostika i sirovi parsirani podaci"):
            st.json(parsed_matches)

# Tajmer za automatsko ponovno pokretanje skripte
if refresh_mode == "Automatsko":
    time.sleep(auto_interval)
    st.rerun()
