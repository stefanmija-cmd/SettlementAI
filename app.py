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
# 2. PARSER KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    matches = []
    
    for idx, line in enumerate(lines):
        if re.match(r'^\d{4,6}$', line):
            try:
                match_id = line
                league = lines[idx - 1] if idx - 1 >= 0 else "Nepoznata liga"
                home = lines[idx + 1] if idx + 1 < len(lines) else ""
                away = lines[idx + 2] if idx + 2 < len(lines) else ""
                
                my_score = "N/A"
                for j in range(idx, min(idx + 15, len(lines))):
                    if re.match(r'^\d+:\d+$', lines[j]):
                        my_score = lines[j]
                        break
                
                if my_score == "N/A":
                    for j in range(idx + 3, min(idx + 12, len(lines) - 1)):
                        if lines[j].isdigit() and lines[j+1].isdigit():
                            if len(lines[j]) <= 2 and len(lines[j+1]) <= 2:
                                my_score = f"{lines[j]}:{lines[j+1]}"
                                break
                
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
# 3. API-FOOTBALL (v3.football.api-sports.io)
# ==========================================
def are_teams_matching(home1, away1, home2, away2):
    """Provera sličnosti naziva timova sa pragom od 68%."""
    sim_home = fuzz.partial_ratio(home1.lower(), home2.lower())
    sim_away = fuzz.partial_ratio(away1.lower(), away2.lower())
    return ((sim_home + sim_away) / 2) > 68

@st.cache_data(ttl=120)  # Kešira odgovor na 2 minuta da sačuva besplatne kvote/pozive
def fetch_all_live_fixtures(api_key):
    """
    Uputi SAMO JEDAN poziv prema v3.football.api-sports.io 
    i preuzme SVE mečeve koji se trenutno igraju u svetu.
    """
    if not api_key:
        return []
        
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        "x-apisports-key": api_key.strip()
    }
    params = {"live": "all"}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=6)
        if res.status_code == 200:
            data = res.json()
            return data.get("response", [])
    except Exception:
        pass
    return []

def fetch_external_live_data(home, away, live_fixtures):
    """Lokalno pretražuje već preuzete live mečeve bez trošenja novih API zahteva."""
    if not home or not away or not live_fixtures:
        return {"ext_score": "N/A", "status": "N/A"}

    for fix in live_fixtures:
        ext_home = fix.get("teams", {}).get("home", {}).get("name", "")
        ext_away = fix.get("teams", {}).get("away", {}).get("name", "")
        
        if are_teams_matching(home, away, ext_home, ext_away):
            gh = fix.get("goals", {}).get("home", 0)
            ga = fix.get("goals", {}).get("away", 0)
            
            # Ako iz nekog razloga golovi budu None umesto broja
            gh = 0 if gh is None else gh
            ga = 0 if ga is None else ga
            
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", "Live")
            return {
                "ext_score": f"{gh}:{ga}", 
                "status": f"{elapsed}' (API-Sports)"
            }

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 4. KORISNIČKI INTERFEJS
# ==========================================
st.title("⚽ Settlement Live Checker")
st.caption("Verifikacija rezultata preko v3.football.api-sports.io")

st.sidebar.header("⚙️ Podešavanja")
api_key_input = st.sidebar.text_input("API-Sports Ključ (x-apisports-key):", type="password")
only_mismatches = st.sidebar.checkbox("Prikaži samo neslaganja", value=False)
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)

if not api_key_input:
    st.info("💡 Unesite tvoj API ključ sa `api-sports.io` u sajdbaru sa leve strane da omogućiš sinhronizaciju.")

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()

raw_text = st.text_area("Zalepite tabelu iz programa (Ctrl + V):", height=180)

if raw_text:
    parsed_matches = parse_copied_data(raw_text)
    
    if not parsed_matches:
        st.warning("⚠️ Nije prepoznata struktura teksta.")
    else:
        # Preuzimamo sve live utakmice samo JEDNOM u 2 minuta
        live_games = fetch_all_live_fixtures(api_key_input) if api_key_input else []
        
        results = []
        has_mismatch = False
        
        for m in parsed_matches:
            ext_data = fetch_external_live_data(m["Home"], m["Away"], live_games)
            ext_score = ext_data["ext_score"]
            my_score = m["Moj Sistem Rezultat"]
            
            if ext_score == "N/A":
                status_check = "NEMA PODATAKA (N/A)"
            elif my_score != ext_score:
                status_check = "MISMATCH (NESLAGANJE)"
                has_mismatch = True
            else:
                status_check = "OK"
            
            results.append({
                "Status": status_check,
                "ID": m["ID"],
                "Oznaka": m["Oznaka"],
                "Liga": m["Liga"],
                "Meč": m["Meč"],
                "Tvoj Sistem": my_score,
                "Teren / Live Feed": ext_score,
                "Status Meča": ext_data["status"]
            })
            
        df = pd.DataFrame(results)
        
        if only_mismatches:
            df = df[df["Status"] == "MISMATCH (NESLAGANJE)"]
            
        if has_mismatch and sound_alert:
            st.audio("https://www.soundjay.com/buttons/sounds/beep-07a.mp3", autoplay=True)
            st.error("🚨 DETEKTOVANO JE NESLAGANJE REZULTATA!")
            
        def highlight_status(val):
            if val == "MISMATCH (NESLAGANJE)":
                return 'background-
