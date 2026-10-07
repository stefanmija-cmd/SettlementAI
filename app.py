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
            return res.json().get("response
