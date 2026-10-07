import streamlit as st
import pandas as pd
import re
import requests
from thefuzz import fuzz

# ==========================================
# 1. PODEŠAVANJE STRANICE I AUTHORIZACIJA
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
    Fleksibilni parser koji pronalazi utakmice na osnovu ID broja meča.
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    matches = []
    
    for idx, line in enumerate(lines):
        # Traži ID utakmice (broj od 4 do 6 cifara)
        if re.match(r'^\d{4,6}$', line):
            try:
                match_id = line
                league = lines[idx - 1] if idx - 1 >= 0 else "Nepoznata liga"
                
                home = lines[idx + 1] if idx + 1 < len(lines) else "Domaćin"
                away = lines[idx + 2] if idx + 2 < len(lines) else "Gost"
                
                # Pretraga rezultata u narednim linijama (format npr. 2:2, 0:0)
                score = "N/A"
                for j in range(idx, min(idx + 12, len(lines))):
                    if re.match(r'^\d+:\d+$', lines[j]):
                        score = lines[j]
                        break
                
                # Pretraga oznake A ili M
                block_lines = lines[idx:min(idx + 15, len(lines))]
                auto_check = "A" if "A" in block_lines else ("M" if "M" in block_lines else "M")
                
                matches.append({
                    "ID": match_id,
                    "Liga": league,
                    "Home": home,
                    "Away": away,
                    "Meč": f"{home} - {away}",
                    "Vreme": lines[idx + 3] if idx + 3 < len(lines) else "",
                    "Moj Sistem Rezultat": score,
                    "Oznaka": auto_check
                })
            except Exception:
                continue
                
    return matches

# ==========================================
# 3. FUZZY MATCHING & LIVE FEED / API Pozivi
# ==========================================
def are_teams_matching(home1, away1, home2, away2):
    """Proverava tekstualnu sličnost timova (prag 75%)."""
    sim_home = fuzz.partial_ratio(home1.lower(), home2.lower())
    sim_away = fuzz.partial_ratio(away1.lower(), away2.lower())
    return ((sim_home + sim_away) / 2) > 75

def fetch_external_live_data(match_id, home, away, api_key=None):
    """
    Povlači live podatke preko RapidAPI-ja (ako postoji ključ) ili preko besplatnog serivsa.
    """
    # 1. Ako je unet RapidAPI ključ
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
                        return {"ext_score": f"{gh}:{ga}", "status": f"{elapsed}' (Live)"}
        except Exception:
            pass

    # 2. Besplatan fallback live feed preko TheSportsDB
    try:
        url = f"https://www.thesportsdb.com/api/v1/json/3/searchevents.php?e={home}_vs_{away}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data and data.get("event"):
                event = data["event"][0]
                gh = event.get("intHomeScore")
                ga = event.get("intAwayScore")
                if gh is not None and ga is not None:
                    return {"ext_score": f"{gh}:{ga}", "status": "U toku"}
    except Exception:
        pass

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 4. KORISNIČKI INTERFEJS & PRIKAZ TABELE
# ==========================================
st.title("⚽ Settlement Live Checker & Mismatch Detector")
st.caption("Automatska verifikacija live
