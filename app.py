"""SettlementCheck

Potrebno: streamlit>=1.40, pandas, requests, rapidfuzz
Secrets (.streamlit/secrets.toml):
    APP_PASSWORD = "nova-jaka-lozinka"
    APISPORTS_KEY = "tvoj-api-kljuc"        # opciono
    FOOTBALLDATA_KEY = "tvoj-fd-kljuc"     # opciono
    RAPIDAPI_KEY = "tvoj-rapidapi-kljuc"    # opciono (SportAPI)
    DEFAULT_PROVIDER = "SportAPI"           # opciono
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
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from rapidfuzz import fuzz

st.set_page_config(page_title="SettlementCheck", page_icon=":material/fact_check:", layout="wide")

# ==========================================
# 0. KONSTANTE
# ==========================================
STATE_FILE = os.environ.get("SETTLEMENT_STATE_FILE", "settlement_state.json")
API_URL = "https://v3.football.api-sports.io/fixtures"
FD_URL = "https://api.football-data.org/v4/matches"

# SportAPI konfiguracija (RapidAPI - sportapi7.p.rapidapi.com)
SPORTAPI_HOST = "sportapi7.p.rapidapi.com"
SPORTAPI_BASE = "https://sportapi7.p.rapidapi.com/api/v1"

TZ = ZoneInfo("Europe/Belgrade")
MATCH_THRESHOLD = 80  # minimalna sličnost imena timova (0-100)
PROVIDERS = ["API-Sports", "football-data.org", "SportAPI"]

FD_STATUS = {
    "IN_PLAY": "LIVE", "LIVE": "LIVE", "PAUSED": "HT", "FINISHED": "FT", "AWARDED": "FT",
    "SUSPENDED": "SUSP", "INTERRUPTED": "SUSP", "POSTPONED": "PST", "CANCELLED": "CANC",
    "CANCELED": "CANC"
}

SPORTAPI_STATUS = {
    "notstarted": "NS",
    "in-progress": "LIVE",
    "finished": "FT",
    "postponed": "PST",
    "canceled": "CANC",
    "delayed": "PST",
    "interrupted": "SUSP",
    "suspended": "SUSP"
}


def ov_key(provider, mid):
    """Ručna spajanja su vezana za provajdera."""
    return mid if provider == "API-Sports" else f"{provider}|{mid}"

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
PING = [(1320, 0.18)]
STATUS_RANK = {"Neslaganje": 0, "Čeka potvrdu": 1, "Nema podataka": 2,
               "Sistem bez rezultata": 3, "OK": 4}


def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default


def g(d, *path, default=None):
    """Bezbedno čitanje ugnježdenih ključeva."""
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


# ==========================================
# DIZAJN (crna + zel
