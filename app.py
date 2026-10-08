import streamlit as st
import pandas as pd
import re
import requests
import time
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
# 2. AUDIO ALARM SA IZBOROM ZVUKA
# ==========================================
SOUND_URLS = {
    "Beep": "https://media.geeksforgeeks.org/wp-content/uploads/20190531135120/beep.mp3",
    "Ping": "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
    "Upozorenje": "https://assets.mixkit.co/active_storage/sfx/995/995-preview.mp3"
}

def play_sound_alarm(sound_choice):
    url = SOUND_URLS.get(sound_choice, SOUND_URLS["Standardni Beep"])
    audio_html = f"""
        <audio autoplay style="display:none;">
            <source src="{url}" type="audio/mpeg">
        </audio>
    """
    st.markdown(audio_html, unsafe_allow_html=True)

# ==========================================
# 3. REČNIK SINONIMA I NORMALIZACIJA
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
    name = name.lower().strip()
    name = re.sub(r'\b(fc|fk|u19|u21|club|cd|sc|sp|sporting)\b', '', name, flags=re.IGNORECASE).strip()
    return TEAM_ALIASES.get(name, name)

def are_teams_matching(home1, away1, home2, away2):
    """
    Stroga provera: Domaćin sa Domaćinom i Gost sa Gostom (min 75% podudaranja).
    Obrnuta domaćinstva se NAMERNO ne prepoznaju jer predstavljaju nevažeće klađenje.
    """
    h1 = normalize_team_name(home1)
    a1 = normalize_team_name(away1)
    h2 = normalize_team_name(home2)
    a2 = normalize_team_name(away2)
    
    sim_home = fuzz.partial_ratio(h1, h2)
    sim_away = fuzz.partial_ratio(a1, a2)
    
    return sim_home >= 75 and sim_away >= 75

# Funkcija za predlaganje parova iz API-ja za N/A utakmice
def find_best_candidate(home, away, live_fixtures):
    h = normalize_team_name(home)
    a = normalize_team_name(away)
    
    best_candidate = None
    best_score = 0
    
    for fix in live_fixtures:
        ext_home = fix.get("teams", {}).get("home", {}).get("name", "")
        ext_away = fix.get("teams", {}).get("away", {}).get("name", "")
        
        eh = normalize_team_name(ext_home)
        ea = normalize_team_name(ext_away)
        
        score_h = fuzz.partial_ratio(h, eh)
        score_a = fuzz.partial_ratio(a, ea)
        avg_score = (score_h + score_a) / 2
        
        if avg_score > 50 and avg_score > best_score:
            best_score = avg_score
            best_candidate = f"{ext_home} - {ext_away}"
            
    return best_candidate

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
# 5. API POZIVI
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
# 6. INTERFEJS I LOGIKA
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

st.sidebar.subheader("🔊 Zvučna Upozorenja")
sound_alert = st.sidebar.checkbox("Omogući zvučni alarm", value=True)
sound_choice = st.sidebar.selectbox("Vrsta zvuka:", list(SOUND_URLS.keys()))

# MANUAL OVERRIDE
st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ Ručno spajanje (Override)")
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

# INICIJALIZACIJA STANJA SOKETA I ARHIVE
if "process_triggered" not in st.session_state:
    st.session_state["process_triggered"] = False

if "session_mismatches" not in st.session_state:
    st.session_state["session_mismatches"] = []

# UNOS TEKSTA
# Funkcija za potpuno čišćenje i polja i izveštaja
def clear_text_callback():
    st.session_state["raw_text_input"] = ""
    st.session_state["process_triggered"] = False

# UNOS TEKSTA (vezan na session_state)
raw_text = st.text_area(
    "Zalepite tabelu iz vašeg programa (Ctrl + V):", 
    height=160, 
    key="raw_text_input"
)

col_btn1, col_btn2, _ = st.columns([2, 1, 3])

with col_btn1:
    if st.button("🚀 Učitaj i proveri tabelu", type="primary", use_container_width=True):
        st.session_state["process_triggered"] = True
        st.cache_data.clear()

with col_btn2:
    st.button(
        "🗑️ Očisti tekst", 
        on_click=clear_text_callback, 
        use_container_width=True
    )

# OBRADA PODATAKA
if raw_text and st.session_state["process_triggered"]:
    parsed_matches = parse_copied_data(raw_text)
    
    if not parsed_matches:
        st.warning("⚠️ Nije prepoznata struktura teksta. Proverite uslov kopiranja.")
    else:
        live_games, remaining_reqs = fetch_all_live_fixtures(api_key_input) if api_key_input else ([], "N/A")
        
        if remaining_reqs != "N/A":
            st.sidebar.info(f"📊 Preostalo API zahteva: **{remaining_reqs}**")
        
        results = []
        has_mismatch = False
        count_ok, count_mismatch, count_na = 0, 0, 0
        suggestions = []
        
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
                
                # Traženje predloga za spajanje
                cand = find_best_candidate(m["Home"], m["Away"], live_games)
                if cand:
                    suggestions.append({"match_id": m["ID"], "my_match": m["Meč"], "candidate": cand})
                    
            elif my_score != ext_score:
                status_check = "MISMATCH (NESLAGANJE)"
                has_mismatch = True
                count_mismatch += 1
                
                # Dodavanje u trajnu arhivu sesije ako već nije dodato
                mismatch_record = {
                    "Vreme": time.strftime("%H:%M:%S"),
                    "ID": m["ID"],
                    "Liga": m["Liga"],
                    "Meč": m["Meč"],
                    "Tvoj Sistem": my_score,
                    "Teren / Live": ext_score
                }
                if not any(x["ID"] == m["ID"] and x["Tvoj Sistem"] == my_score and x["Teren / Live"] == ext_score for x in st.session_state["session_mismatches"]):
                    st.session_state["session_mismatches"].append(mismatch_record)
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
        
        # METRIKE
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ukupno mečeva", len(df))
        m2.metric("Usklađeno (OK)", count_ok)
        m3.metric("Neslaganja (MISMATCH)", count_mismatch, delta_color="inverse")
        m4.metric("Nema podataka (N/A)", count_na)
        
        # BRZA PRETRAGA I FILTERI
        st.markdown("---")
        col_search, col_filter = st.columns([2, 2])
        
        with col_search:
            search_query = st.text_input("🔍 Brza pretraga (ID, klub ili liga):", "")
            
        with col_filter:
            filter_status = st.radio(
                "Filtriraj po statusu:", 
                ["Svi mečevi", "Samo Neslaganja (MISMATCH)", "Samo Nema Podataka (N/A)"], 
                horizontal=True
            )
        
        # FILTRIRANJE
        if filter_status == "Samo Neslaganja (MISMATCH)":
            df = df[df["Status"] == "MISMATCH (NESLAGANJE)"]
        elif filter_status == "Samo Nema Podataka (N/A)":
            df = df[df["Status"] == "NEMA PODATAKA (N/A)"]
            
        if search_query:
            query = search_query.lower()
            df = df[
                df["ID"].astype(str).str.contains(query) | 
                df["Meč"].str.lower().str.contains(query) | 
                df["Liga"].str.lower().str.contains(query)
            ]
            
        if has_mismatch and sound_alert:
            play_sound_alarm(sound_choice)
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

        # AUTO-ALIAS SUGGESTER (Pametni predlozi za spajanje jednim klikom)
        if suggestions:
            with st.expander("💡 Pametni predlozi za ručno spajanje (Jedan klik)", expanded=True):
                st.caption("Aplikacija je pronašla potencijalne parove na API-ju za nepovezane mečeve:")
                for sug in suggestions:
                    c1, c2, c3 = st.columns([2, 3, 2])
                    c1.write(f"**ID {sug['match_id']}**: {sug['my_match']}")
                    c2.write(f"API kandidat: **{sug['candidate']}**")
                    if c3.button(f"➕ Spoji sa '{sug['candidate']}'", key=f"sug_{sug['match_id']}"):
                        st.session_state["manual_overrides"][str(sug['match_id'])] = {
                            "override_search": sug['candidate'].split('-')[0].strip()
                        }
                        st.success(f"Uspešno spojeno! Kliknite na 'Učitaj i proveri tabelu'.")
                        st.rerun()

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Preuzmi trenutni izveštaj (CSV)",
            data=csv,
            file_name="settlement_mismatch_report.csv",
            mime="text/csv"
        )

# ==========================================
# 7. ISTORIJA NESLAGANJA U TOKU SMENE
# ==========================================
if st.session_state["session_mismatches"]:
    st.markdown("---")
    st.subheader("📜 Arhiva svih detektovanih neslaganja u toku radne sesije")
    st.caption("Ova tabela pamti sve sporne mečeve iz svih tabela koje ste učitali u toku smene.")
    
    mismatch_df = pd.DataFrame(st.session_state["session_mismatches"])
    st.dataframe(mismatch_df, use_container_width=True)
    
    if st.button("🗑️ Obriši arhivu neslaganja"):
        st.session_state["session_mismatches"] = []
        st.rerun()

# LIVE MONITOR I DIJAGNOSTIKA
if raw_text and st.session_state["process_triggered"]:
    with st.expander("📺 Pregled svih trenutno aktivnih live utakmica na API-ju"):
        if 'live_games' in locals() and live_games:
            live_list = []
            for lg in live_games:
                live_list.append({
                    "Liga": lg.get("league", {}).get("name", ""),
                    "Domaćin": lg.get("teams", {}).get("home", {}).get("name", ""),
                    "Gost": lg.get("teams", {}).get("away", {}).get("name", ""),
                    "Rezultat": f"{lg.get('goals',{}).get('home',0)}:{lg.get('goals',{}).get('away',0)}",
                    "Minut": lg.get("fixture", {}).get("status", {}).get("elapsed", "Live")
                })
            st.dataframe(pd.DataFrame(live_list), use_container_width=True)
        else:
            st.info("Nema učitanih live utakmica sa API-ja.")

if refresh_mode == "Automatsko" and st.session_state["process_triggered"]:
    time.sleep(auto_interval)
    st.rerun()
