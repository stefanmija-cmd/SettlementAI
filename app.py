import streamlit as st
import pandas as pd
import re
import requests
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
                
                # Ako nema formata X:Y, traže se dva uzastopna broja (Home i Away golovi)
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
# 3. FUZZY MATCHING & FLASHSCORE LIVE FEED
# ==========================================
try:
    from fs_football import Flashscore
    FS_AVAILABLE = True
except ImportError:
    FS_AVAILABLE = False

def are_teams_matching(home1, away1, home2, away2):
    """Proverava tekstualnu sličnost timova (prag 70%)."""
    sim_home = fuzz.partial_ratio(home1.lower(), home2.lower())
    sim_away = fuzz.partial_ratio(away1.lower(), away2.lower())
    return ((sim_home + sim_away) / 2) > 70

@st.cache_data(ttl=30)
def get_flashscore_live_matches():
    """Povlači sve live mečeve sa Flashscore-a sa keširanjem od 30 sekundi."""
    if not FS_AVAILABLE:
        return []
    try:
        fs = Flashscore()
        return fs.get_live_matches()
    except Exception:
        return []

def fetch_external_live_data(match_id, home, away, api_key=None):
    """
    Pretražuje eksterne izvore (RapidAPI ili Flashscore) za live mečeve.
    """
    if not home or not away:
        return {"ext_score": "N/A", "status": "N/A"}

    # 1. Provera preko opcionog RapidAPI ključa
    if api_key and len(api_key.strip()) > 5:
        url
