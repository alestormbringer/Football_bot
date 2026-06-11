# Football AI Bot — Build Specification
> Documento di riferimento per Claude Code. Contiene tutto il necessario per costruire il progetto da zero senza ambiguità.

> **NOTA (migrazione dati):** questo documento descrive la versione iniziale
> del progetto basata su API-Football v3. La fonte dati è stata sostituita
> con **football-data.org v4** (vedi [`docs/API_REFERENCE.md`](API_REFERENCE.md))
> perché il piano Free di API-Football non copre le stagioni 2025/26 e il
> Mondiale 2026. I riferimenti ad API-Football, `CURRENT_SEASON`, al budget
> di 100 call/giorno e alle competizioni non disponibili su football-data.org
> (Europa League, Conference League, coppe nazionali, Nations League, infortuni)
> sono superati: fare riferimento a `config/settings.py`,
> `modules/api_client.py` e `scheduler/cron_runner.py` per l'implementazione
> attuale.

---

## 1. Panoramica del progetto

Bot Telegram che fornisce pronostici calcistici settimanali basati su dati reali + modello ML + generazione LLM. Gira su VPS OVH (Ubuntu, 4 vCore, 8 GB RAM). Completamente automatizzato: nessun intervento manuale dopo il deploy.

**Stack tecnologico:**
- Python 3.11+
- Supabase (PostgreSQL hosted) — database centrale
- API-Football v3 — fonte dati calcistici
- OpenRouter — LLM routing (primario: `google/gemini-2.0-flash-exp:free`, fallback: `qwen/qwen3-8b:free`)
- python-telegram-bot v20+ — interfaccia utente
- APScheduler — cron jobs interni al processo Python
- scikit-learn / scipy — modello ML (distribuzione di Poisson + regressione)

---

## 2. Struttura cartelle

```
football-ai-bot/
│
├── config/
│   ├── settings.py          # Tutte le costanti, ID leghe, credenziali env
│   └── database.py          # Client Supabase singleton
│
├── modules/
│   ├── api_client.py        # Wrapper API-Football con rate limiting
│   ├── scraper.py           # RSS scraping notizie calcistiche
│   ├── predictor_ml.py      # Modello Poisson + feature engineering
│   └── report_generator.py  # Costruzione prompt + chiamata OpenRouter
│
├── bot/
│   └── telegram_handler.py  # Handler comandi Telegram, InlineKeyboard
│
├── scheduler/
│   └── cron_runner.py       # APScheduler jobs (venerdì, sabato, domenica)
│
├── main.py                  # Entry point — avvia bot + scheduler
├── requirements.txt
├── .env                     # Non committare mai
└── .env.example
```

---

## 3. Variabili d'ambiente (.env)

```env
# API-Football
API_FOOTBALL_KEY=your_key_here

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_anon_key_here

# OpenRouter
OPENROUTER_API_KEY=your_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_token_here

# Stagione corrente (aggiornare a inizio stagione)
CURRENT_SEASON=2025
```

---

## 4. config/settings.py — costanti complete

```python
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
    # sono sospesi → il budget call rimane invariato (non si sommano).
    # Il sistema attiva automaticamente solo le competizioni con
    # partite nel weekend corrente (controlled by active_this_week).
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

# Mappa id → chiave stringa (utile per lookup inverso)
LEAGUE_ID_MAP = {v["id"]: k for k, v in LEAGUES.items()}

# Competizioni internazionali per nazionali (attive solo durante le loro finestre)
INTERNATIONAL_LEAGUE_KEYS = [k for k, v in LEAGUES.items() if v.get("international")]

# Competizioni di club (attive durante la stagione regolare)
CLUB_LEAGUE_KEYS = [k for k, v in LEAGUES.items() if not v.get("international")]

# --- OpenRouter ---
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_PRIMARY   = "google/gemini-2.0-flash-exp:free"
LLM_FALLBACK  = "qwen/qwen3-8b:free"
LLM_MAX_TOKENS = 1200

# --- Budget API calls ---
# Limite: 100 call/giorno. Venerdì: fetch completo. Sab/dom: solo delta.
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
    "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    "la_liga":        "🇪🇸 La Liga",
    "serie_a":        "🇮🇹 Serie A",
    "bundesliga":     "🇩🇪 Bundesliga",
    "ligue_1":        "🇫🇷 Ligue 1",
    # Coppe europee per club
    "champions":      "⭐ Champions League",
    "europa":         "🟠 Europa League",
    "conference":     "🟢 Conference League",
    # Coppe nazionali
    "fa_cup":         "🏴󠁧󠁢󠁥󠁮󠁧󠁿 FA Cup",
    "coppa_italia":   "🇮🇹 Coppa Italia",
    "copa_del_rey":   "🇪🇸 Copa del Rey",
    # Tornei internazionali
    "world_cup":      "🌍 FIFA World Cup",
    "euro":           "🏆 UEFA Euro",
    "nations_league": "🔵 Nations League",
}

# Gruppi per la UI onboarding (mostra sezioni separate)
COMPETITION_GROUPS = {
    "Campionati":           ["premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"],
    "Coppe europee":        ["champions", "europa", "conference"],
    "Coppe nazionali":      ["fa_cup", "coppa_italia", "copa_del_rey"],
    "Tornei internazionali":["world_cup", "euro", "nations_league"],
}
```

---

## 5. Schema database Supabase (SQL)

Eseguire nell'editor SQL di Supabase nell'ordine indicato.

```sql
-- =============================================
-- TABELLA: competitions
-- Cache delle competizioni supportate
-- =============================================
CREATE TABLE competitions (
    id            INTEGER PRIMARY KEY,   -- id API-Football
    key           TEXT NOT NULL UNIQUE,  -- es. "serie_a"
    name          TEXT NOT NULL,
    country       TEXT,
    type          TEXT CHECK (type IN ('league','cup')),
    season        INTEGER NOT NULL,
    international BOOLEAN DEFAULT FALSE, -- TRUE = torneo nazionale (Mondiali, Euro, Nations)
    active        BOOLEAN DEFAULT TRUE,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- NOTA sul ciclo internazionale:
-- Mondiali ed Europei si svolgono durante la pausa estiva dei campionati nazionali
-- (giugno-luglio). Non si sovrappongono mai alle giornate di campionato.
-- La Nations League si gioca nelle finestre internazionali di settembre/ottobre/novembre,
-- nelle stesse settimane in cui i campionati si fermano per le nazionali.
-- Il budget di 100 call/giorno NON viene mai "doppiato":
-- quando ci sono tornei internazionali, i campionati non hanno partite da scaricare.
-- Il sistema lo gestisce automaticamente: /fixtures?league=X per le date del weekend
-- restituisce lista vuota se non ci sono partite → nessuna call sprecata.

-- =============================================
-- TABELLA: fixtures
-- Partite del weekend scaricate ogni venerdì
-- =============================================
CREATE TABLE fixtures (
    id              INTEGER PRIMARY KEY,   -- id API-Football
    competition_id  INTEGER REFERENCES competitions(id),
    home_team_id    INTEGER NOT NULL,
    home_team_name  TEXT NOT NULL,
    away_team_id    INTEGER NOT NULL,
    away_team_name  TEXT NOT NULL,
    match_date      TIMESTAMPTZ NOT NULL,
    round           TEXT,
    status          TEXT DEFAULT 'NS',    -- NS / FT / PST / CANC …
    week_start      DATE NOT NULL,        -- lunedì della settimana (per raggruppamento)
    raw_data        JSONB,                -- payload completo dall'API
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fixtures_week      ON fixtures(week_start);
CREATE INDEX idx_fixtures_comp      ON fixtures(competition_id);
CREATE INDEX idx_fixtures_date      ON fixtures(match_date);
CREATE INDEX idx_fixtures_status    ON fixtures(status);

-- =============================================
-- TABELLA: fixture_stats
-- Dati ML per ogni partita (H2H, form, standings)
-- =============================================
CREATE TABLE fixture_stats (
    id              SERIAL PRIMARY KEY,
    fixture_id      INTEGER REFERENCES fixtures(id) UNIQUE,
    home_form       TEXT,                 -- es. "WWDLW" (ultimi 5)
    away_form       TEXT,
    home_position   INTEGER,              -- posizione in classifica
    away_position   INTEGER,
    home_goals_avg  NUMERIC(4,2),         -- media gol segnati
    away_goals_avg  NUMERIC(4,2),
    home_conceded_avg NUMERIC(4,2),
    away_conceded_avg NUMERIC(4,2),
    h2h_data        JSONB,                -- ultimi 5 H2H
    injuries_home   JSONB,                -- lista infortuni squadra casa
    injuries_away   JSONB,
    ml_home_prob    NUMERIC(5,4),         -- probabilità calcolate dal modello
    ml_draw_prob    NUMERIC(5,4),
    ml_away_prob    NUMERIC(5,4),
    ml_expected_goals_home NUMERIC(4,2),
    ml_expected_goals_away NUMERIC(4,2),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- TABELLA: reports
-- Report testuali generati dall'LLM, pronti per Telegram
-- =============================================
CREATE TABLE reports (
    id              SERIAL PRIMARY KEY,
    fixture_id      INTEGER REFERENCES fixtures(id) UNIQUE,
    report_text     TEXT NOT NULL,        -- testo formattato Markdown Telegram
    advice          TEXT,                 -- consiglio breve (1 riga)
    confidence      TEXT CHECK (confidence IN ('alta','media','bassa')),
    llm_model_used  TEXT,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    is_updated      BOOLEAN DEFAULT FALSE -- TRUE se rigenerato sab/dom
);

CREATE INDEX idx_reports_fixture ON reports(fixture_id);

-- =============================================
-- TABELLA: users
-- Utenti Telegram registrati
-- =============================================
CREATE TABLE users (
    telegram_id     BIGINT PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    language_code   TEXT DEFAULT 'it',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- TABELLA: user_preferences
-- Competizioni seguite per ogni utente
-- =============================================
CREATE TABLE user_preferences (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    competition_key TEXT NOT NULL,        -- es. "serie_a"
    UNIQUE (telegram_id, competition_key)
);

CREATE INDEX idx_user_prefs_user ON user_preferences(telegram_id);

-- =============================================
-- TABELLA: api_usage_log
-- Monitoraggio consumo chiamate API
-- =============================================
CREATE TABLE api_usage_log (
    id          SERIAL PRIMARY KEY,
    log_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    endpoint    TEXT NOT NULL,
    calls_made  INTEGER DEFAULT 1,
    logged_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_log_date ON api_usage_log(log_date);
```

---

## 6. modules/api_client.py

Wrapper completo con rate limiting, retry, budget guard e logging automatico.

```python
import time
import logging
import requests
from datetime import date
from config.settings import API_BASE_URL, API_HEADERS, DAILY_CALL_LIMIT, CALL_SAFETY_BUFFER
from config.database import get_client

logger = logging.getLogger(__name__)

class APIFootballClient:
    """
    Wrapper per API-Football v3.
    - Rispetta il limite di 100 call/giorno
    - Retry automatico su 499/500
    - Logging di ogni call su Supabase
    - /status non conta sulla quota (chiamato gratis per monitoraggio)
    """

    def __init__(self):
        self.base_url = API_BASE_URL
        self.headers  = API_HEADERS
        self.session  = requests.Session()
        self.session.headers.update(self.headers)
        self._calls_today = None

    # ------------------------------------------------------------------
    # Quota management
    # ------------------------------------------------------------------

    def get_remaining_calls(self) -> int:
        """Chiama /status (non quota) per sapere le call rimanenti oggi."""
        resp = self.session.get(f"{self.base_url}/status", timeout=10)
        data = resp.json()
        if data.get("errors"):
            logger.warning("Errore /status: %s", data["errors"])
            return 0
        req = data["response"]["requests"]
        used  = req["current"]
        limit = req["limit_day"]
        return limit - used

    def _budget_ok(self, needed: int = 1) -> bool:
        remaining = self.get_remaining_calls()
        ok = remaining >= (needed + CALL_SAFETY_BUFFER)
        if not ok:
            logger.error(
                "Budget esaurito: rimangono %d call, servono %d + %d buffer",
                remaining, needed, CALL_SAFETY_BUFFER
            )
        return ok

    def _log_call(self, endpoint: str):
        """Registra la call su Supabase per tracciamento."""
        try:
            get_client().table("api_usage_log").insert({
                "log_date": date.today().isoformat(),
                "endpoint": endpoint,
            }).execute()
        except Exception as e:
            logger.warning("Log call fallito: %s", e)

    # ------------------------------------------------------------------
    # Metodo base
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: dict, retries: int = 2) -> dict | None:
        """
        GET generico con retry su 499/500.
        Restituisce response[] o None in caso di errore.
        """
        if not self._budget_ok():
            return None

        url = f"{self.base_url}/{endpoint}"
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                self._log_call(endpoint)

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("errors"):
                        logger.warning("[%s] Errori API: %s", endpoint, data["errors"])
                        return None
                    return data.get("response", [])

                elif resp.status_code in (499, 500):
                    logger.warning("[%s] Status %d, retry %d/%d",
                                   endpoint, resp.status_code, attempt + 1, retries)
                    time.sleep(2 ** attempt)  # backoff esponenziale

                elif resp.status_code == 429:
                    logger.error("[%s] Rate limit (429) — aspetto 60s", endpoint)
                    time.sleep(60)

                else:
                    logger.error("[%s] HTTP %d", endpoint, resp.status_code)
                    return None

            except requests.RequestException as e:
                logger.error("[%s] Eccezione request: %s", endpoint, e)
                if attempt == retries:
                    return None
                time.sleep(2)

        return None

    # ------------------------------------------------------------------
    # Endpoint specifici
    # ------------------------------------------------------------------

    def get_fixtures_by_league(self, league_id: int, season: int,
                                from_date: str, to_date: str) -> list:
        """
        Scarica tutte le partite di una lega in un intervallo di date.
        1 call → tutti i match del weekend.
        Esempio: from_date="2025-08-22", to_date="2025-08-25"
        """
        return self._get("fixtures", {
            "league": league_id,
            "season": season,
            "from": from_date,
            "to": to_date,
            "timezone": "Europe/Rome",
        }) or []

    def get_fixtures_batch(self, fixture_ids: list[int]) -> list:
        """
        Batch fetch: max 20 fixture IDs in una sola call.
        Restituisce eventi + lineups + statistics + players.
        Usato per refresh sab/dom.
        """
        if not fixture_ids:
            return []
        # L'API accetta max 20 ids separati da "-"
        chunks = [fixture_ids[i:i+20] for i in range(0, len(fixture_ids), 20)]
        results = []
        for chunk in chunks:
            ids_str = "-".join(str(fid) for fid in chunk)
            data = self._get("fixtures", {"ids": ids_str}) or []
            results.extend(data)
        return results

    def get_standings(self, league_id: int, season: int) -> list:
        """Classifica completa di una lega. 1 call."""
        return self._get("standings", {
            "league": league_id,
            "season": season,
        }) or []

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 5) -> list:
        """
        Ultimi N scontri diretti tra due squadre.
        1 call per coppia. Usato nel fetch venerdì.
        """
        return self._get("fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}",
            "last": last,
        }) or []

    def get_injuries(self, league_id: int, season: int, fixture_ids: list[int] = None) -> list:
        """
        Infortuni per lega (fetch completo venerdì) oppure
        per fixture specifici batch (refresh sab/dom).
        1 call per lega in modalità venerdì.
        In modalità refresh: usa il parametro ids (max 20).
        """
        if fixture_ids:
            ids_str = "-".join(str(fid) for fid in fixture_ids[:20])
            return self._get("injuries", {"ids": ids_str}) or []
        else:
            return self._get("injuries", {
                "league": league_id,
                "season": season,
            }) or []

    def get_lineups(self, fixture_id: int) -> list:
        """
        Formazioni ufficiali (disponibili ~60 min prima del match).
        Usato solo nel refresh sab/dom per partite imminenti.
        """
        return self._get("fixtures/lineups", {"fixture": fixture_id}) or []

    def get_teams_statistics(self, league_id: int, team_id: int, season: int) -> dict:
        """
        Statistiche stagionali di una squadra in una lega.
        Opzionale: usato per arricchire il prompt LLM se il budget lo permette.
        """
        result = self._get("teams/statistics", {
            "league": league_id,
            "team": team_id,
            "season": season,
        })
        return result[0] if result else {}
```

---

## 7. modules/predictor_ml.py

Modello Poisson per calcolo probabilità. Non usa sklearn per il cuore del calcolo (Poisson è analitico), ma scipy per la distribuzione.

```python
import logging
import numpy as np
from scipy.stats import poisson

logger = logging.getLogger(__name__)

def parse_form(form_string: str, last_n: int = 5) -> float:
    """
    Converte stringa form (es. 'WWDLW') in percentuale vittorie.
    Considera solo gli ultimi N risultati.
    """
    if not form_string:
        return 0.5
    recent = form_string[-last_n:].upper()
    wins   = recent.count('W')
    return wins / len(recent) if recent else 0.5

def compute_poisson_probs(
    home_attack: float,
    home_defense: float,
    away_attack: float,
    away_defense: float,
    home_advantage: float = 1.1,
    max_goals: int = 6,
) -> dict:
    """
    Calcola probabilità 1X2 usando distribuzione di Poisson bivariata.

    Parametri:
    - home_attack:   media gol segnati in casa (stagione corrente)
    - home_defense:  media gol subiti in casa
    - away_attack:   media gol segnati in trasferta
    - away_defense:  media gol subiti in trasferta
    - home_advantage: fattore moltiplicativo per il vantaggio casalingo

    Restituisce:
    {
        "home_win": 0.45,
        "draw": 0.28,
        "away_win": 0.27,
        "expected_home": 1.62,
        "expected_away": 1.14,
        "over_25": 0.52,   # probabilità Over 2.5 gol
    }
    """
    # Expected goals (xG semplificato da statistiche)
    lambda_home = home_attack * away_defense * home_advantage
    lambda_away = away_attack * home_defense

    # Clip ragionevole
    lambda_home = max(0.3, min(lambda_home, 5.0))
    lambda_away = max(0.3, min(lambda_away, 5.0))

    # Matrice di probabilità risultati esatti
    score_matrix = np.zeros((max_goals + 1, max_goals + 1))
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            score_matrix[h, a] = (
                poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
            )

    # Normalizza (la matrice troncata non somma esattamente a 1)
    score_matrix /= score_matrix.sum()

    home_win = float(np.tril(score_matrix, -1).sum())  # h > a
    draw     = float(np.trace(score_matrix))
    away_win = float(np.triu(score_matrix, 1).sum())   # a > h

    # Over 2.5
    over_25 = float(sum(
        score_matrix[h, a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
        if h + a > 2
    ))

    return {
        "home_win":      round(home_win, 4),
        "draw":          round(draw,     4),
        "away_win":      round(away_win, 4),
        "expected_home": round(lambda_home, 2),
        "expected_away": round(lambda_away, 2),
        "over_25":       round(over_25, 4),
    }

def build_match_stats(fixture_stats_row: dict) -> dict:
    """
    Prende una riga di fixture_stats e restituisce i parametri
    pronti per compute_poisson_probs.
    """
    return {
        "home_attack":  fixture_stats_row.get("home_goals_avg", 1.2),
        "home_defense": fixture_stats_row.get("home_conceded_avg", 1.0),
        "away_attack":  fixture_stats_row.get("away_goals_avg", 1.0),
        "away_defense": fixture_stats_row.get("away_conceded_avg", 1.2),
    }

def adjust_for_injuries(probs: dict, home_injury_count: int, away_injury_count: int) -> dict:
    """
    Aggiustamento euristico delle probabilità in base agli infortuni.
    Ogni infortunio pesante (tipo "Missing Fixture") riduce leggermente
    la forza offensiva della squadra colpita.
    """
    penalty = 0.02  # per ogni infortuno "Missing Fixture"

    home_penalty = min(home_injury_count * penalty, 0.10)
    away_penalty = min(away_injury_count * penalty, 0.10)

    home_win = probs["home_win"] - home_penalty + away_penalty * 0.5
    away_win = probs["away_win"] - away_penalty + home_penalty * 0.5
    draw     = 1.0 - home_win - away_win

    # Mantieni valori nel range [0.05, 0.90]
    home_win = max(0.05, min(0.90, home_win))
    away_win = max(0.05, min(0.90, away_win))
    draw     = max(0.05, min(0.80, draw))

    # Rinormalizza
    total = home_win + draw + away_win
    return {
        **probs,
        "home_win": round(home_win / total, 4),
        "draw":     round(draw     / total, 4),
        "away_win": round(away_win / total, 4),
    }
```

---

## 8. modules/report_generator.py

Costruisce il prompt e chiama OpenRouter con fallback automatico.

```python
import logging
import requests
from config.settings import OPENROUTER_BASE_URL, OPENROUTER_KEY, LLM_PRIMARY, LLM_FALLBACK, LLM_MAX_TOKENS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sei un analista sportivo esperto in pronostici calcistici.
Scrivi report concisi, diretti e informativi in italiano.
Usa il formato Markdown compatibile con Telegram (grassetto con *, corsivo con _, codice con `).
Non inventare mai dati. Se un dato è assente, omettilo.
Non usare emoji eccessive. Massimo 3-4 per report."""

def build_match_prompt(
    home_team: str,
    away_team: str,
    competition: str,
    match_date: str,
    home_form: str,
    away_form: str,
    home_position: int,
    away_position: int,
    ml_probs: dict,
    h2h_summary: str,
    injuries_home: list,
    injuries_away: list,
) -> str:
    """
    Costruisce il prompt per la generazione del report.
    Tutti i parametri numerici vengono dal modello ML — l'LLM
    deve SOLO trasformarli in testo, non ricalcolarli.
    """

    injuries_home_text = ", ".join(
        f"{p['name']} ({p['reason']})" for p in injuries_home[:3]
    ) if injuries_home else "nessun infortunio noto"

    injuries_away_text = ", ".join(
        f"{p['name']} ({p['reason']})" for p in injuries_away[:3]
    ) if injuries_away else "nessun infortunio noto"

    prompt = f"""Genera un report di pronostico per questa partita:

**Partita:** {home_team} vs {away_team}
**Competizione:** {competition}
**Data:** {match_date}

**Dati statistici (già calcolati, usa questi):**
- Forma recente {home_team}: {home_form} (posizione: {home_position}°)
- Forma recente {away_team}: {away_form} (posizione: {away_position}°)
- Probabilità ML: {home_team} {ml_probs['home_win']*100:.1f}% | Pareggio {ml_probs['draw']*100:.1f}% | {away_team} {ml_probs['away_win']*100:.1f}%
- Gol attesi: {home_team} {ml_probs['expected_home']} | {away_team} {ml_probs['expected_away']}
- Probabilità Over 2.5: {ml_probs['over_25']*100:.1f}%
- H2H (ultimi 5): {h2h_summary}
- Infortuni {home_team}: {injuries_home_text}
- Infortuni {away_team}: {injuries_away_text}

**Struttura richiesta (rispetta questa struttura esatta):**

*{home_team} vs {away_team}*
📊 _Analisi_
[2-3 righe di analisi qualitativa basata sui dati]

🎯 _Pronostico_
[1 riga: consiglio specifico es. "1X + Under 3.5"]

📈 _Probabilità_
`{home_team}: XX% | X: XX% | {away_team}: XX%`

⚠️ _Da tenere d'occhio_
[infortuni rilevanti o fattori di rischio, max 1 riga]

Lunghezza massima: 200 parole. Scrivi in italiano."""

    return prompt

def generate_report(prompt: str, model: str = LLM_PRIMARY) -> str | None:
    """
    Chiama OpenRouter con il modello specificato.
    Restituisce il testo generato o None in caso di errore.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/football-ai-bot",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.7,
    }
    try:
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("Errore OpenRouter [%s]: %s", model, e)
        return None

def generate_report_with_fallback(prompt: str) -> tuple[str | None, str]:
    """
    Tenta LLM_PRIMARY, poi LLM_FALLBACK.
    Restituisce (testo, modello_usato).
    """
    text = generate_report(prompt, LLM_PRIMARY)
    if text:
        return text, LLM_PRIMARY

    logger.warning("Primary LLM fallito, provo fallback %s", LLM_FALLBACK)
    text = generate_report(prompt, LLM_FALLBACK)
    if text:
        return text, LLM_FALLBACK

    return None, "none"
```

---

## 9. scheduler/cron_runner.py

Pipeline completa con i tre job settimanali.

```python
import logging
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import (
    LEAGUES, CURRENT_SEASON, INTERNATIONAL_LEAGUE_KEYS,
    FRIDAY_FETCH_HOUR, SATURDAY_FETCH_HOUR, SUNDAY_FETCH_HOUR
)
from config.database import get_client
from modules.api_client import APIFootballClient
from modules.predictor_ml import compute_poisson_probs, adjust_for_injuries, build_match_stats
from modules.report_generator import build_match_prompt, generate_report_with_fallback

logger = logging.getLogger(__name__)
api    = APIFootballClient()
db     = get_client()


def get_weekend_range() -> tuple[str, str]:
    """Restituisce (venerdì, lunedì) della settimana corrente."""
    today    = date.today()
    friday   = today + timedelta(days=(4 - today.weekday()) % 7)
    monday   = friday + timedelta(days=3)
    return friday.isoformat(), monday.isoformat()

def get_week_start() -> date:
    """Lunedì della settimana corrente."""
    today = date.today()
    return today - timedelta(days=today.weekday())

def get_season_for_competition(league_key: str) -> int:
    """
    Stagione corretta per ogni competizione.

    - Campionati e coppe club → CURRENT_SEASON (anno di inizio, es. 2025 = 25/26)
    - Tornei internazionali   → anno solare corrente (es. 2026 per i Mondiali 2026)

    I campionati nazionali sono SEMPRE sospesi durante i tornei internazionali,
    quindi il budget 100 call/giorno non si somma mai: quando i tornei
    internazionali hanno partite, i campionati restituiscono lista vuota.
    """
    if league_key in INTERNATIONAL_LEAGUE_KEYS:
        return date.today().year
    return CURRENT_SEASON


# ==============================================================
# JOB 1 — VENERDÌ: fetch completo
# ==============================================================
def friday_full_fetch():
    """
    Scarica tutto il necessario per il weekend:
    1. Fixtures per ogni competizione
    2. Standings per ogni lega
    3. H2H per ogni partita
    4. Injuries per ogni competizione
    5. Calcola probabilità ML
    6. Genera report LLM per ogni partita
    """
    logger.info("=== FRIDAY FETCH START ===")
    from_date, to_date = get_weekend_range()
    week_start = get_week_start()

    remaining = api.get_remaining_calls()
    logger.info("Call rimanenti prima del fetch: %d", remaining)

    # --- Step 1: Fixtures ---
    all_fixtures = []
    for key, league in LEAGUES.items():
        season = get_season_for_competition(key)
        fixtures = api.get_fixtures_by_league(
            league_id=league["id"],
            season=season,
            from_date=from_date,
            to_date=to_date,
        )
        if not fixtures:
            # Lista vuota = nessuna partita questa settimana per questa competizione.
            # Normale durante pause internazionali (campionati) o fuori stagione (coppe).
            logger.debug("Lega %s: nessuna partita nel weekend, skip.", key)
            continue

        for f in fixtures:
            fixture_row = {
                "id":             f["fixture"]["id"],
                "competition_id": league["id"],
                "home_team_id":   f["teams"]["home"]["id"],
                "home_team_name": f["teams"]["home"]["name"],
                "away_team_id":   f["teams"]["away"]["id"],
                "away_team_name": f["teams"]["away"]["name"],
                "match_date":     f["fixture"]["date"],
                "round":          f["league"].get("round"),
                "status":         f["fixture"]["status"]["short"],
                "week_start":     week_start.isoformat(),
                "raw_data":       f,
            }
            db.table("fixtures").upsert(fixture_row).execute()
            all_fixtures.append(fixture_row)

        logger.info("Lega %s (season %s): %d partite scaricate", key, season, len(fixtures))

    # --- Step 2: Standings ---
    # Per campionati nazionali: classifica normale a 1 gruppo.
    # Per tornei internazionali (Mondiali, Euro): ci sono più gironi →
    # standings[0]["league"]["standings"] è una lista di liste (una per girone).
    # Il codice gestisce entrambi i casi appiattendo tutti i gironi.
    standings_cache = {}
    for key, league in LEAGUES.items():
        season = get_season_for_competition(key)
        standings = api.get_standings(league["id"], season)
        if not standings:
            continue
        try:
            all_groups = standings[0]["league"]["standings"]  # lista di gironi
            merged = {}
            for group in all_groups:
                for t in group:
                    merged[t["team"]["id"]] = t["rank"]
            standings_cache[league["id"]] = merged
        except (KeyError, IndexError):
            pass

    # --- Step 3 & 4: H2H + Injuries per partita ---
    for f in all_fixtures:
        home_id  = f["home_team_id"]
        away_id  = f["away_team_id"]
        fixture_id = f["id"]

        # H2H
        h2h = api.get_h2h(home_id, away_id, last=5)

        # Injuries (già scaricate per lega in bulk — usa cache se disponibile)
        # In questa versione semplificata chiamiamo per fixture
        injuries = api.get_injuries(
            league_id=f["competition_id"],
            season=CURRENT_SEASON,
            fixture_ids=[fixture_id],
        )
        injuries_home = [
            {"name": i["player"]["name"], "reason": i["player"].get("reason", "?")}
            for i in injuries if i["team"]["id"] == home_id
            and i["player"].get("type") == "Missing Fixture"
        ]
        injuries_away = [
            {"name": i["player"]["name"], "reason": i["player"].get("reason", "?")}
            for i in injuries if i["team"]["id"] == away_id
            and i["player"].get("type") == "Missing Fixture"
        ]

        # --- Step 5: ML ---
        # Recupera stats dalla tabella (già popolata in precedenza)
        # Per ora usiamo valori di default ragionevoli
        # TODO: arricchire con teams/statistics se il budget lo permette
        ml_input = {
            "home_attack": 1.4, "home_defense": 1.1,
            "away_attack": 1.1, "away_defense": 1.2,
        }
        probs = compute_poisson_probs(**ml_input)
        probs = adjust_for_injuries(probs, len(injuries_home), len(injuries_away))

        # H2H summary (ultimi 5)
        h2h_summary = _summarize_h2h(h2h, home_id)

        # Salva fixture_stats
        db.table("fixture_stats").upsert({
            "fixture_id":     fixture_id,
            "injuries_home":  injuries_home,
            "injuries_away":  injuries_away,
            "h2h_data":       h2h,
            "ml_home_prob":   probs["home_win"],
            "ml_draw_prob":   probs["draw"],
            "ml_away_prob":   probs["away_win"],
            "ml_expected_goals_home": probs["expected_home"],
            "ml_expected_goals_away": probs["expected_away"],
        }).execute()

        # --- Step 6: LLM report ---
        prompt = build_match_prompt(
            home_team=f["home_team_name"],
            away_team=f["away_team_name"],
            competition=_get_league_name(f["competition_id"]),
            match_date=f["match_date"][:10],
            home_form="N/A",
            away_form="N/A",
            home_position=standings_cache.get(f["competition_id"], {}).get(home_id, 0),
            away_position=standings_cache.get(f["competition_id"], {}).get(away_id, 0),
            ml_probs=probs,
            h2h_summary=h2h_summary,
            injuries_home=injuries_home,
            injuries_away=injuries_away,
        )
        text, model_used = generate_report_with_fallback(prompt)
        if text:
            db.table("reports").upsert({
                "fixture_id":     fixture_id,
                "report_text":    text,
                "llm_model_used": model_used,
                "is_updated":     False,
            }).execute()
            logger.info("Report generato per fixture %d [%s]", fixture_id, model_used)
        else:
            logger.error("Report fallito per fixture %d", fixture_id)

    logger.info("=== FRIDAY FETCH END — %d partite elaborate ===", len(all_fixtures))


# ==============================================================
# JOB 2 — SABATO / DOMENICA: refresh delta
# ==============================================================
def daily_refresh(day_name: str = "saturday"):
    """
    Refresh leggero: solo infortuni aggiornati + lineups ufficiali
    per le partite in programma oggi. Rigenera il report se ci sono novità.
    """
    logger.info("=== %s REFRESH START ===", day_name.upper())
    today = date.today().isoformat()

    # Partite di oggi dal DB
    result = db.table("fixtures")\
        .select("id, home_team_id, away_team_id, home_team_name, away_team_name, competition_id")\
        .eq("status", "NS")\
        .gte("match_date", f"{today}T00:00:00")\
        .lte("match_date", f"{today}T23:59:59")\
        .execute()

    today_fixtures = result.data or []
    if not today_fixtures:
        logger.info("Nessuna partita oggi, refresh saltato.")
        return

    fixture_ids = [f["id"] for f in today_fixtures]
    logger.info("Partite oggi: %d", len(fixture_ids))

    # Fetch injuries in batch (max 20 per call)
    injuries_raw = api.get_injuries(
        league_id=0, season=0,  # non usati se fixture_ids è fornito
        fixture_ids=fixture_ids[:20],
    )

    # Raggruppa infortuni per fixture
    injuries_by_fixture = {}
    for inj in injuries_raw:
        fid = inj.get("fixture", {}).get("id")
        if fid:
            injuries_by_fixture.setdefault(fid, []).append(inj)

    # Rigenera report solo se ci sono infortuni nuovi
    for f in today_fixtures:
        fid = f["id"]
        new_injuries = injuries_by_fixture.get(fid, [])
        if not new_injuries:
            continue

        # Recupera stats esistenti
        stats_res = db.table("fixture_stats").select("*").eq("fixture_id", fid).execute()
        stats = stats_res.data[0] if stats_res.data else {}

        probs = {
            "home_win":      stats.get("ml_home_prob", 0.45),
            "draw":          stats.get("ml_draw_prob", 0.28),
            "away_win":      stats.get("ml_away_prob", 0.27),
            "expected_home": stats.get("ml_expected_goals_home", 1.4),
            "expected_away": stats.get("ml_expected_goals_away", 1.1),
            "over_25":       0.50,
        }
        injuries_home = [
            {"name": i["player"]["name"], "reason": i["player"].get("reason", "?")}
            for i in new_injuries if i["team"]["id"] == f["home_team_id"]
        ]
        injuries_away = [
            {"name": i["player"]["name"], "reason": i["player"].get("reason", "?")}
            for i in new_injuries if i["team"]["id"] == f["away_team_id"]
        ]
        probs = adjust_for_injuries(probs, len(injuries_home), len(injuries_away))

        prompt = build_match_prompt(
            home_team=f["home_team_name"], away_team=f["away_team_name"],
            competition=_get_league_name(f["competition_id"]),
            match_date=today,
            home_form="N/A", away_form="N/A",
            home_position=0, away_position=0,
            ml_probs=probs, h2h_summary="aggiornamento",
            injuries_home=injuries_home, injuries_away=injuries_away,
        )
        text, model_used = generate_report_with_fallback(prompt)
        if text:
            db.table("reports").upsert({
                "fixture_id":     fid,
                "report_text":    text,
                "llm_model_used": model_used,
                "is_updated":     True,
            }).execute()
            logger.info("Report aggiornato fixture %d", fid)

    logger.info("=== %s REFRESH END ===", day_name.upper())


# ==============================================================
# Helpers
# ==============================================================
def _summarize_h2h(h2h_data: list, home_id: int) -> str:
    """Produce stringa leggibile dagli ultimi 5 H2H."""
    if not h2h_data:
        return "nessun precedente"
    results = []
    for match in h2h_data[:5]:
        teams  = match.get("teams", {})
        goals  = match.get("goals", {})
        winner = teams.get("home", {}).get("winner")
        h_name = teams.get("home", {}).get("name", "?")
        a_name = teams.get("away", {}).get("name", "?")
        h_gol  = goals.get("home", "?")
        a_gol  = goals.get("away", "?")
        results.append(f"{h_name} {h_gol}-{a_gol} {a_name}")
    return " | ".join(results)

def _get_league_name(league_id: int) -> str:
    from config.settings import LEAGUE_ID_MAP, LEAGUES
    key = LEAGUE_ID_MAP.get(league_id, "")
    return LEAGUES.get(key, {}).get("name", str(league_id))


# ==============================================================
# Setup scheduler
# ==============================================================
def setup_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        friday_full_fetch,
        CronTrigger(day_of_week="fri", hour=FRIDAY_FETCH_HOUR, minute=0),
        id="friday_fetch", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_refresh("saturday"),
        CronTrigger(day_of_week="sat", hour=SATURDAY_FETCH_HOUR, minute=0),
        id="saturday_refresh", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_refresh("sunday"),
        CronTrigger(day_of_week="sun", hour=SUNDAY_FETCH_HOUR, minute=0),
        id="sunday_refresh", replace_existing=True,
    )
    return scheduler
```

---

## 10. bot/telegram_handler.py

```python
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from config.settings import TELEGRAM_TOKEN, COMPETITION_DISPLAY_NAMES
from config.database import get_client

logger = logging.getLogger(__name__)
db = get_client()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start — registra utente e mostra selezione competizioni."""
    user = update.effective_user
    db.table("users").upsert({
        "telegram_id":  user.id,
        "username":     user.username,
        "first_name":   user.first_name,
        "language_code": user.language_code or "it",
    }).execute()

    await update.message.reply_text(
        f"👋 Ciao {user.first_name}! Seleziona le competizioni che vuoi seguire:",
        reply_markup=_build_competition_keyboard(user.id),
    )

async def cmd_pronostici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /pronostici — invia i report della settimana filtrati per preferenze."""
    user_id = update.effective_user.id

    prefs_res = db.table("user_preferences")\
        .select("competition_key")\
        .eq("telegram_id", user_id)\
        .execute()
    prefs = [p["competition_key"] for p in (prefs_res.data or [])]

    if not prefs:
        await update.message.reply_text(
            "⚙️ Non hai ancora scelto le competizioni. Usa /start per configurarle."
        )
        return

    from config.settings import LEAGUES
    league_ids = [LEAGUES[k]["id"] for k in prefs if k in LEAGUES]

    if not league_ids:
        await update.message.reply_text("Nessuna competizione trovata.")
        return

    # Recupera report della settimana
    from datetime import date, timedelta
    today      = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    fixtures_res = db.table("fixtures")\
        .select("id, home_team_name, away_team_name, match_date")\
        .in_("competition_id", league_ids)\
        .gte("week_start", week_start)\
        .eq("status", "NS")\
        .order("match_date")\
        .execute()

    fixtures = fixtures_res.data or []
    if not fixtures:
        await update.message.reply_text("📭 Nessuna partita in programma questa settimana.")
        return

    sent = 0
    for f in fixtures:
        report_res = db.table("reports")\
            .select("report_text")\
            .eq("fixture_id", f["id"])\
            .execute()
        if not report_res.data:
            continue
        text = report_res.data[0]["report_text"]
        await update.message.reply_text(text, parse_mode="Markdown")
        sent += 1

    if sent == 0:
        await update.message.reply_text("⏳ Report in elaborazione, riprova più tardi.")

async def callback_competition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pulsanti selezione competizioni."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    data = query.data  # formato: "comp_toggle:serie_a" o "comp_save"

    if data.startswith("comp_toggle:"):
        key = data.split(":", 1)[1]
        # Verifica se già presente
        existing = db.table("user_preferences")\
            .select("id")\
            .eq("telegram_id", user_id)\
            .eq("competition_key", key)\
            .execute()
        if existing.data:
            db.table("user_preferences")\
                .delete()\
                .eq("telegram_id", user_id)\
                .eq("competition_key", key)\
                .execute()
        else:
            db.table("user_preferences")\
                .insert({"telegram_id": user_id, "competition_key": key})\
                .execute()
        # Aggiorna tastiera
        await query.edit_message_reply_markup(
            reply_markup=_build_competition_keyboard(user_id)
        )

    elif data == "comp_save":
        prefs_res = db.table("user_preferences")\
            .select("competition_key")\
            .eq("telegram_id", user_id)\
            .execute()
        count = len(prefs_res.data or [])
        await query.edit_message_text(
            f"✅ Preferenze salvate! Segui {count} competizioni.\n"
            f"Usa /pronostici per vedere i report del weekend."
        )

def _build_competition_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Costruisce la tastiera con stato attivo/inattivo per ogni competizione."""
    prefs_res = db.table("user_preferences")\
        .select("competition_key")\
        .eq("telegram_id", user_id)\
        .execute()
    active = {p["competition_key"] for p in (prefs_res.data or [])}

    buttons = []
    for key, label in COMPETITION_DISPLAY_NAMES.items():
        tick = "✅" if key in active else "⬜"
        buttons.append([InlineKeyboardButton(
            f"{tick} {label}",
            callback_data=f"comp_toggle:{key}"
        )])
    buttons.append([InlineKeyboardButton("💾 Salva", callback_data="comp_save")])
    return InlineKeyboardMarkup(buttons)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("pronostici",  cmd_pronostici))
    app.add_handler(CallbackQueryHandler(callback_competition))
    return app
```

---

## 11. config/database.py

```python
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY

_client: Client | None = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client
```

---

## 12. main.py

```python
import logging
import asyncio
from scheduler.cron_runner import setup_scheduler
from bot.telegram_handler import build_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Avvio Football AI Bot...")

    # Scheduler background (venerdì/sabato/domenica)
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler avviato. Jobs: %s", [j.id for j in scheduler.get_jobs()])

    # Bot Telegram (polling bloccante)
    app = build_application()
    logger.info("Bot Telegram in polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
```

---

## 13. requirements.txt

```
python-telegram-bot==20.7
supabase==2.3.0
requests==2.31.0
apscheduler==3.10.4
scipy==1.12.0
numpy==1.26.4
python-dotenv==1.0.0
```

---

## 14. Regole di sviluppo per Claude Code

### Non fare mai
- Non usare `/predictions` di API-Football (1 call per partita, budget esaurito)
- Non committare `.env`
- Non fare chiamate API in loop senza controllare il budget residuo
- Non usare `time.sleep()` per aspettare il rate limit — usa backoff esponenziale

### Sempre fare
- Chiamare `/status` all'inizio di ogni job per monitorare le call rimanenti
- Usare `upsert` invece di `insert` per evitare duplicati su runs ripetute
- Loggare ogni call API con livello INFO
- Gestire il caso in cui l'API restituisce lista vuota (fixture non ancora disponibili)

### Ordine di implementazione consigliato
1. `config/` — settings + database
2. Schema SQL su Supabase
3. `modules/api_client.py` — testare manualmente con `/status`
4. `modules/predictor_ml.py` — testare con dati mock
5. `modules/report_generator.py` — testare con prompt hardcoded
6. `scheduler/cron_runner.py` — testare con `friday_full_fetch()` in modo sincrono
7. `bot/telegram_handler.py` — testare con bot di test separato
8. `main.py` — integrazione finale

### Comandi utili sul VPS
```bash
# Avvio in background
nohup python main.py > logs/bot.log 2>&1 &

# Tail log in tempo reale
tail -f logs/bot.log

# Controllare il consumo API (senza sprecare call)
curl -s https://v3.football.api-sports.io/status \
  -H "x-apisports-key: YOUR_KEY" | python3 -m json.tool
```
