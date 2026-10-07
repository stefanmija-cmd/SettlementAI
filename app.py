import streamlit as st
import pandas as pd
import re
import requests
from thefuzz import fuzz

# ==========================================
# 1. PODEŠAVANJE STRANICE I LOZINKE
# ==========================================
st.set_page_config(
    page_title="Settlement Live Checker", 
    page_icon="⚽", 
    layout="wide"
)

# Postavi svoju željenu lozinku ovde
PASSWORD = "settlement123"

def check_password():
    """Jednostavan sistem autorizacije za pristup aplikaciji."""
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
# 2. LOGIKA ZA PARSIRANJE KOPIRANOG TEKSTA
# ==========================================
def parse_copied_data(text):
    """
    Parsira tekst koji je kopiran iz internog programa.
    Prepoznaje strukturu sa sporom, ligom, ID-jem, timovima i rezultatima.
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    matches = []
    
    i = 0
    while i < len(lines):
        # Tražimo početak meča (obično 'F' za fudbal i brojčani ID nakon lige)
        if lines[i] == 'F' and (i + 2) < len(lines) and lines[i+2].isdigit():
            try:
                sport = lines[i]
                league = lines[i+1]
                match_id = lines[i+2]
                home = lines[i+3]
                away = lines[i+4]
                time_str = lines[i+5]
                
                # Izvlačenje trenutnog rezultata (npr. 2:2 ili 0:0)
                score = "N/A"
                for j in range(i+6, min(i+15, len(lines))):
                    if re.match(r'^\d+:\d+$', lines[j]):
                        score = lines[j]
                        break
                
                # Provera da li meč ima automatsko ('A') ili ručno ('M') čekiranje
                auto_check = "A" if "A" in lines[i+6:i+16] else "M"
                
                matches.append({
                    "ID": match_id,
                    "Liga": league,
                    "Home": home,
                    "Away": away,
                    "Meč": f"{home} - {away}",
                    "Vreme": time_str,
                    "Moj Sistem Rezultat": score,
                    "Oznaka": auto_check
                })
                i += 10 # Preskačemo blok procesiranih linija
            except Exception:
                i += 1
        else:
            i += 1
    return matches

# ==========================================
# 3. FUZZY MATCHING & API INTEGRACIJA
# ==========================================
def are_teams_matching(home1, away1, home2, away2):
    """Proverava da li se imena timova poklapaju sa više od 75% sličnosti."""
    sim_home = fuzz.partial_ratio(home1.lower(), home2.lower())
    sim_away = fuzz.partial_ratio(away1.lower(), away2.lower())
    return ((sim_home + sim_away) / 2) > 75

def fetch_external_live_data(match_id, home, away, api_key=None):
    """
    Povlači live podatke sa API-ja ili vraća simulaciju ako API ključ nije podešen.
    """
    if not api_key:
        # DEMO REŽIM (Simulacija za testiranje)
        if match_id == "72500":
            return {"ext_score": "2:3", "status": "38' (Live)"}
        elif match_id == "72499":
            return {"ext_score": "0:0", "status": "2nd half"}
        return {"ext_score": "N/A", "status": "N/A"}

    # REALNI API REŽIM (RapidAPI / API-Football)
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": api_key,
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
                    return {
                        "ext_score": f"{gh}:{ga}",
                        "status": f"{elapsed}'"
                    }
    except Exception as e:
        st.error(f"Greška sa API-jem: {e}")

    return {"ext_score": "N/A", "status": "N/A"}

# ==========================================
# 4. KORISNIČKI INTERFEJS (STYLING & DISPLAY)
# ==========================================
st.title("⚽ Settlement Live Checker & Mismatch Detector")
st.caption("Poređenje podataka iz radnog programa sa eksternim izvorima u realnom vremenu.")

# Sidebar podešavanja
st.sidebar.header("⚙️ Podešavanja")
api_key_input = st.sidebar.text_input("RapidAPI Ključ (Opciono):", type="password")
only_mismatches = st.sidebar.checkbox("Prikaži samo neslaganja", value=False)
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)

if st.sidebar.button("Odjavi se"):
    st.session_state["authenticated"] = False
    st.rerun()

# Polje za unos teksta
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
            
            status_check = "OK"
            if ext_score != "N/A" and m["Moj Sistem Rezultat"] != ext_score:
                status_check = "MISMATCH (NESLAGANJE)"
                has_mismatch = True
            
            results.append({
                "Status": status_check,
                "ID": m["ID"],
                "Oznaka": m["Oznaka"],
                "Liga": m["Liga"],
                "Meč": m["Meč"],
                "Tvoj Sistem": m["Moj Sistem Rezultat"],
                "Teren / Live Feed": ext_score,
                "Status Meča": ext_data["status"]
            })
            
        df = pd.DataFrame(results)
        
        if only_mismatches:
            df = df[df["Status"] == "MISMATCH (NESLAGANJE)"]
            
        # Zvučni alarm ako postoji neslaganje
        if has_mismatch and sound_alert:
            st.audio("https://www.soundjay.com/buttons/sounds/beep-07a.mp3", autoplay=True)
            st.error("🚨 DETEKTOVANO JE NESLAGANJE REZULTATA U PROGRAMU I NA TERENU!")
            
        # Bojenje redova tabele
        def highlight_status(val):
            if val == "MISMATCH (NESLAGANJE)":
                return 'background-color: #d32f2f; color: white; font-weight: bold;'
            return 'background-color: #2e7d32; color: white;'

        st.subheader(f"📊 Pregled utakmica ({len(df)})")
        st.dataframe(
            df.style.map(highlight_status, subset=['Status']), 
            use_container_width=True
        )
