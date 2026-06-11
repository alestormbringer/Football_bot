import os
from dotenv import load_dotenv

load_dotenv()

# --- Credenziali ---
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
SUPABASE_URL          = os.getenv("SUPABASE_URL")
SUPABASE_KEY          = os.getenv("SUPABASE_KEY")
OPENROUTER_KEY        = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN")

# --- football-data.org ---
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
FOOTBALL_DATA_HEADERS  = {
    "X-Auth-Token": FOOTBALL_DATA_API_KEY,
}

# Piano Free: 10 richieste/minuto (rispettato lato client da FootballDataClient)
RATE_LIMIT_PER_MINUTE = 10

# --- Competizioni (codici e ID football-data.org, piano Free) ---
# NOTA: Europa League, Conference League e le coppe nazionali (FA Cup,
# Coppa Italia, Copa del Rey) e la Nations League NON sono incluse nel
# piano Free di football-data.org -> rimosse finché non si fa upgrade.
LEAGUES = {
    # Campionati nazionali
    "premier_league": {"id": 2021, "code": "PL",  "name": "Premier League", "country": "England", "type": "league",
                       "international": False},
    "la_liga":        {"id": 2014, "code": "PD",  "name": "La Liga",        "country": "Spain",   "type": "league",
                       "international": False},
    "serie_a":        {"id": 2019, "code": "SA",  "name": "Serie A",        "country": "Italy",   "type": "league",
                       "international": False},
    "bundesliga":     {"id": 2002, "code": "BL1", "name": "Bundesliga",     "country": "Germany", "type": "league",
                       "international": False},
    "ligue_1":        {"id": 2015, "code": "FL1", "name": "Ligue 1",        "country": "France",  "type": "league",
                       "international": False},
    # Coppe europee per club
    "champions":      {"id": 2001, "code": "CL",  "name": "Champions League", "country": "World", "type": "cup",
                       "international": False},
    # ---------------------------------------------------------------
    # Tornei internazionali per nazionali
    # Giocano OGNI giorno della settimana durante il loro periodo
    # (international_daily_fetch li copre lun-gio, oltre al weekend).
    # ---------------------------------------------------------------
    "world_cup":      {"id": 2000, "code": "WC",  "name": "FIFA World Cup", "country": "World",  "type": "cup",
                       "international": True},
    "euro":           {"id": 2018, "code": "EC",  "name": "UEFA Euro",      "country": "Europe", "type": "cup",
                       "international": True},
}

LEAGUE_IDS = [v["id"] for v in LEAGUES.values()]

# Mappa id -> chiave stringa (utile per lookup inverso)
LEAGUE_ID_MAP = {v["id"]: k for k, v in LEAGUES.items()}

# Competizioni internazionali per nazionali (attive solo durante le loro finestre)
INTERNATIONAL_LEAGUE_KEYS = [k for k, v in LEAGUES.items() if v.get("international")]

# Competizioni di club (attive durante la stagione regolare)
CLUB_LEAGUE_KEYS = [k for k, v in LEAGUES.items() if not v.get("international")]

# --- OpenRouter ---
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# openrouter/free seleziona automaticamente un modello :free disponibile,
# evitando i 429 upstream quando un singolo provider (es. Venice per Qwen) è congestionato.
LLM_PRIMARY   = "openrouter/free"
LLM_FALLBACK  = "qwen/qwen3-coder:free"
LLM_MAX_TOKENS = 1200

# --- Scheduler (orari UTC, VPS in Europa) ---
FRIDAY_FETCH_HOUR   = 6   # 06:00 UTC = 08:00 ora italiana
SATURDAY_FETCH_HOUR = 8
SUNDAY_FETCH_HOUR   = 8

# --- Telegram ---
# Chiavi per InlineKeyboard onboarding
COMPETITION_DISPLAY_NAMES = {
    # Campionati nazionali
    "premier_league": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F Premier League",
    "la_liga":        "\U0001F1EA\U0001F1F8 La Liga",
    "serie_a":        "\U0001F1EE\U0001F1F9 Serie A",
    "bundesliga":     "\U0001F1E9\U0001F1EA Bundesliga",
    "ligue_1":        "\U0001F1EB\U0001F1F7 Ligue 1",
    # Coppe europee per club
    "champions":      "⭐ Champions League",
    # Tornei internazionali
    "world_cup":      "\U0001F30D FIFA World Cup",
    "euro":           "\U0001F3C6 UEFA Euro",
}

# Gruppi per la UI onboarding (mostra sezioni separate)
COMPETITION_GROUPS = {
    "Campionati":            ["premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"],
    "Coppe europee":         ["champions"],
    "Tornei internazionali": ["world_cup", "euro"],
}
