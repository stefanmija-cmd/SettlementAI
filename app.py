import streamlit as st
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup
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
    """Autorizacija za pristup aplikaciji."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔒 Prijava na sistem")
        st.write("Unesite lozinku za pristup aplikaciji.")
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
# 2. PARSER KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    """
    Parser prilagođen strukturi tabele iz radnog programa.
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    matches = []
    
    for idx, line in enumerate(lines):
        # Tražimo ID meča (4 do 6 cifara)
        if re.match(r'^\d{4,6}$', line):
            try:
                match_id = line
                league = lines[idx - 1] if idx - 1 >= 0 else "Nepoznata liga"
                home = lines[idx + 1] if idx + 1 < len(lines) else ""
                away = lines[idx + 2] if idx + 2 < len(lines) else ""
                
                # Traženje rezultata u tvojoj tabeli
                my_score = "N/A"
                for j in range(idx, min(idx + 15, len(lines))):
                    if re.match(r'^\d+:\d+$', lines[j]):
                        my_score = lines[j]
                        break
                
                # Ako nema formata X:Y, traže se dva uzastopna broja
                if my_score == "N/A":
                    for j in range(idx + 3, min(idx + 12, len(lines) - 1)):
                        if lines[j].isdigit() and lines[j+1].isdigit():
                            if len(lines[j]) <= 2 and len(lines[j+1]) <= 2:
                                my_score = f"{lines[j]}:{lines[j+1]}"
                                break
                
                # Oznaka A ili M
                block_lines = lines[idx:min(idx + 18, len(lines))]
                auto_check = "A" if "A" in block_lines else ("M" if "M" in block_lines else "M")
                
                matches.append({
                    "ID": match_id,
                    "Liga": league,
                    "Home": home,
                    "Away": away,
                    "Meč": f"{home} - {away}",
                    "Moj Sistem Rezultat": my_score,
                    "Oznaka": auto_check
                })
            except Exception:
                continue
                
    return matches

# ==========================================
# 3. SOFASCORE & EXTRA FEED INTEGRACIJA
# ==========================================
def are_teams_matching(home1, away1, home2, away2):
    """Proverava tekstualnu sličnost timova (prag 68%)."""
    sim_home = fuzz.partial_ratio(home1.lower(), home2.lower())
    sim_away = fuzz.partial_ratio(away1.lower(), away2.lower())
    return ((sim_home + sim_away) / 2) > 68

@st.cache_data(ttl=30)
def fetch_sofascore_live_events():
    """
    Povlači trenutne live utakmice direktno sa SofaScore API-ja.
    """
    url = "https://api.sofascore.com/api/v1/sport/football/events/live"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/"
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json().get("events", [])
    except Exception:
        pass
    return []

def fetch_external_live_data(match_id, home, away, api_key=None):
    """
    Pretražuje SofaScore i RapidAPI za live mečeve.
    """
    if not home or not away:
        return {"ext_score": "N/A", "status": "N/A"}

    # 1. Provera preko SofaScore API-ja
    sofa_events = fetch_sofascore_live_events()
    for ev in sofa_events:
        ss_home = ev.get("homeTeam", {}).get("name", "")
        ss_away = ev.get("awayTeam", {}).get("name", "")
        
        if are_teams_matching(home, away, ss_home, ss_away):
            home_score = ev.get("homeScore", {}).get("current", 0)
            away_score = ev.get("awayScore", {}).get("current", 0)
            status_description = ev.get("status", {}).get("description", "Live")
            
            return {
                "ext_score": f"{home_score}:{away_score}",
                "status": f"{status_description} (SofaScore)"
            }

    # 2. Provera preko RapidAPI ključa (kao rezervna opcija ako je unet)
    if api_key and len(api_key.strip()) > 5:
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            "X-RapidAPI-Key": api_key.strip(),
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        params = {"live": "all"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if "response" in data:
                for fix in data["response"]:
                    ext_home = fix["teams"]["home"]["name"]
                    ext_away = fix["teams"]["away"]["name"]
                    if are_teams_matching(home, away, ext_home, ext_away):
                        gh = fix["goals"]["home"]
                        ga = fix["goals"]["away"]
                        elapsed = fix["fixture"]["status"]["elapsed"]
                        return {"ext_score": f"{gh}:{ga}", "status": f"{elapsed}' (API-Football)"}
        except Exception:
            pass

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 4. KORISNIČKI INTERFEJS & PRIKAZ TABELE
# ==========================================
st.title("⚽ Settlement Live Checker & Mismatch Detector")
st.caption("Automatska verifikacija live rezultata sa SofaScore-a i detekcija neslaganja.")

# Sajdbar
st.sidebar.header("⚙️ Podešavanja")
api_key_input = st.sidebar.text_input("RapidAPI Ključ (Opciono):", type="password")
only_mismatches = st.sidebar.checkbox("Prikaži samo neslaganja", value=False)
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()

# Unos teksta
raw_text = st.text_area("Zalepite tabelu kopiranu iz vašeg programa (Ctrl + V):", height=180)

if raw_text:
    parsed_matches = parse_copied_data(raw_text)
    
    if not parsed_matches:
        st.warning("⚠️ Nije prepoznata struktura teksta. Proverite da li ste dobro kopirali tabelu.")
    else:
        results = []
        has_mismatch = False
        
        for m in parsed_matches:
            ext_data = fetch_external_live_data(m["ID"], m["Home"], m["Away"], api_key_input)
            ext_score = ext_data["ext_score"]
            my_score = m["Moj Sistem Rezultat"]
