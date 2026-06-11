import os
from dotenv import load_dotenv

load_dotenv()

# --- Credenziali ---
API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY")
SUPABASE_URL      = os.getenv("SUPABASE_URL")
SUPABASE_KEY      = os.getenv("SUPABASE_KEY")
OPENROUTER_KEY    = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CURRENT_SEASON    = int(os.getenv("CURRENT_SEASON", 2025))

# --- API-Football ---
API_BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS  = {
    "x-apisports-key": API_FOOTBALL_KEY,
}

# --- ID Leghe (da dashboard API-Football) ---
LEAGUES = {
    # Campionati nazionali
    "premier_league": {"id": 39,  "name": "Premier League",  "country": "England", "type": "league",
                       "international": False},
    "la_liga":        {"id": 140, "name": "La Liga",          "country": "Spain",   "type": "league",
                       "international": False},
    "serie_a":        {"id": 135, "name": "Serie A",          "country": "Italy",   "type": "league",
                       "international": False},
    "bundesliga":     {"id": 78,  "name": "Bundesliga",       "country": "Germany", "type": "league",
                       "international": False},
    "ligue_1":        {"id": 61,  "name": "Ligue 1",          "country": "France",  "type": "league",
                       "international": False},
    # Coppe europee per club
    "champions":      {"id": 2,   "name": "Champions League", "country": "World",   "type": "cup",
                       "international": False},
    "europa":         {"id": 3,   "name": "Europa League",    "country": "World",   "type": "cup",
                       "international": False},
    "conference":     {"id": 848, "name": "Conference League","country": "World",   "type": "cup",
                       "international": False},
    # Coppe nazionali
    "fa_cup":         {"id": 45,  "name": "FA Cup",           "country": "England", "type": "cup",
                       "international": False},
    "coppa_italia":   {"id": 137, "name": "Coppa Italia",     "country": "Italy",   "type": "cup",
                       "international": False},
    "copa_del_rey":   {"id": 143, "name": "Copa del Rey",     "country": "Spain",   "type": "cup",
                       "international": False},
    # ---------------------------------------------------------------
    # Tornei internazionali per nazionali
    # NOTA: quando questi tornei sono in corso, i campionati nazionali
    # sono sospesi -> il budget call rimane invariato (non si sommano).
    # Il sistema attiva automaticamente solo le competizioni con
    # partite nel weekend corrente (le fixtures vuote vengono skippate).
    # ---------------------------------------------------------------
    "world_cup":      {"id": 1,   "name": "FIFA World Cup",   "country": "World",   "type": "cup",
                       "international": True,
                       # ID confermato dalla guida ufficiale API-Football (aprile 2026)
                       # season: anno di svolgimento (es. 2026 per i Mondiali 2026)
                       },
    "euro":           {"id": 4,   "name": "UEFA Euro",        "country": "Europe",  "type": "cup",
                       "international": True,
                       # ID da verificare nel dashboard API-Football prima del deploy
                       # https://dashboard.api-football.com/soccer/ids/leagues
                       },
    "nations_league": {"id": 5,   "name": "UEFA Nations League", "country": "Europe", "type": "cup",
                       "international": True,
                       # ID da verificare nel dashboard API-Football prima del deploy
                       },
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
LLM_PRIMARY   = "qwen/qwen3-next-80b-a3b-instruct:free"
LLM_FALLBACK  = "qwen/qwen3-coder:free"
LLM_MAX_TOKENS = 1200

# --- Budget API calls ---
# Limite: 100 call/giorno. Venerdi: fetch completo. Sab/dom: solo delta.
DAILY_CALL_LIMIT  = 100
CALL_SAFETY_BUFFER = 8   # call riservate per retry ed errori

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
    "europa":         "\U0001F7E0 Europa League",
    "conference":     "\U0001F7E2 Conference League",
    # Coppe nazionali
    "fa_cup":         "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F FA Cup",
    "coppa_italia":   "\U0001F1EE\U0001F1F9 Coppa Italia",
    "copa_del_rey":   "\U0001F1EA\U0001F1F8 Copa del Rey",
    # Tornei internazionali
    "world_cup":      "\U0001F30D FIFA World Cup",
    "euro":           "\U0001F3C6 UEFA Euro",
    "nations_league": "\U0001F535 Nations League",
}

# Gruppi per la UI onboarding (mostra sezioni separate)
COMPETITION_GROUPS = {
    "Campionati":            ["premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"],
    "Coppe europee":         ["champions", "europa", "conference"],
    "Coppe nazionali":       ["fa_cup", "coppa_italia", "copa_del_rey"],
    "Tornei internazionali": ["world_cup", "euro", "nations_league"],
}
