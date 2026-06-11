-- ================================================================
-- Football AI Bot — Schema Supabase
-- Eseguire nell'ordine indicato (rispettare le foreign key)
-- ================================================================

-- 1. competitions
CREATE TABLE IF NOT EXISTS competitions (
    id            INTEGER PRIMARY KEY,
    key           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    country       TEXT,
    type          TEXT CHECK (type IN ('league','cup')),
    season        INTEGER NOT NULL,
    international BOOLEAN DEFAULT FALSE,  -- TRUE = torneo per nazionali
    active        BOOLEAN DEFAULT TRUE,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Seed dati competizioni
INSERT INTO competitions (id, key, name, country, type, season, international) VALUES
-- Campionati nazionali
(39,  'premier_league', 'Premier League',     'England', 'league', 2025, false),
(140, 'la_liga',        'La Liga',             'Spain',   'league', 2025, false),
(135, 'serie_a',        'Serie A',             'Italy',   'league', 2025, false),
(78,  'bundesliga',     'Bundesliga',          'Germany', 'league', 2025, false),
(61,  'ligue_1',        'Ligue 1',             'France',  'league', 2025, false),
-- Coppe europee per club
(2,   'champions',      'Champions League',    'World',   'cup',    2025, false),
(3,   'europa',         'Europa League',       'World',   'cup',    2025, false),
(848, 'conference',     'Conference League',   'World',   'cup',    2025, false),
-- Coppe nazionali
(45,  'fa_cup',         'FA Cup',              'England', 'cup',    2025, false),
(137, 'coppa_italia',   'Coppa Italia',        'Italy',   'cup',    2025, false),
(143, 'copa_del_rey',   'Copa del Rey',        'Spain',   'cup',    2025, false),
-- Tornei internazionali per nazionali
-- NOTA: season per questi viene aggiornata automaticamente dal codice (anno solare).
-- I valori qui sotto sono placeholder; il cron_runner usa date.today().year.
-- I Mondiali/Euro/Nations League non si sovrappongono mai ai campionati.
(1,   'world_cup',      'FIFA World Cup',      'World',   'cup',    2026, true),
(4,   'euro',           'UEFA Euro',           'Europe',  'cup',    2028, true),
-- ID 4 = UEFA Euro su API-Football: verificare nel dashboard prima del deploy
-- https://dashboard.api-football.com/soccer/ids/leagues
(5,   'nations_league', 'UEFA Nations League', 'Europe',  'cup',    2026, true)
-- ID 5 = Nations League su API-Football: verificare nel dashboard prima del deploy
ON CONFLICT (id) DO NOTHING;

-- 2. fixtures
CREATE TABLE IF NOT EXISTS fixtures (
    id              INTEGER PRIMARY KEY,
    competition_id  INTEGER REFERENCES competitions(id),
    home_team_id    INTEGER NOT NULL,
    home_team_name  TEXT NOT NULL,
    away_team_id    INTEGER NOT NULL,
    away_team_name  TEXT NOT NULL,
    match_date      TIMESTAMPTZ NOT NULL,
    round           TEXT,
    status          TEXT DEFAULT 'NS',
    week_start      DATE NOT NULL,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fixtures_week   ON fixtures(week_start);
CREATE INDEX IF NOT EXISTS idx_fixtures_comp   ON fixtures(competition_id);
CREATE INDEX IF NOT EXISTS idx_fixtures_date   ON fixtures(match_date);
CREATE INDEX IF NOT EXISTS idx_fixtures_status ON fixtures(status);

-- 3. fixture_stats
CREATE TABLE IF NOT EXISTS fixture_stats (
    id                      SERIAL PRIMARY KEY,
    fixture_id              INTEGER REFERENCES fixtures(id) UNIQUE,
    home_form               TEXT,
    away_form               TEXT,
    home_position           INTEGER,
    away_position           INTEGER,
    home_goals_avg          NUMERIC(4,2),
    away_goals_avg          NUMERIC(4,2),
    home_conceded_avg       NUMERIC(4,2),
    away_conceded_avg       NUMERIC(4,2),
    h2h_data                JSONB,
    injuries_home           JSONB DEFAULT '[]',
    injuries_away           JSONB DEFAULT '[]',
    ml_home_prob            NUMERIC(5,4),
    ml_draw_prob            NUMERIC(5,4),
    ml_away_prob            NUMERIC(5,4),
    ml_expected_goals_home  NUMERIC(4,2),
    ml_expected_goals_away  NUMERIC(4,2),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 4. reports
CREATE TABLE IF NOT EXISTS reports (
    id              SERIAL PRIMARY KEY,
    fixture_id      INTEGER REFERENCES fixtures(id) UNIQUE,
    report_text     TEXT NOT NULL,
    advice          TEXT,
    confidence      TEXT CHECK (confidence IN ('alta','media','bassa')),
    llm_model_used  TEXT,
    generated_at    TIMESTAMPTZ DEFAULT NOW(),
    is_updated      BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_reports_fixture ON reports(fixture_id);

-- 5. users
CREATE TABLE IF NOT EXISTS users (
    telegram_id     BIGINT PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    language_code   TEXT DEFAULT 'it',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 6. user_preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    competition_key TEXT NOT NULL,
    UNIQUE (telegram_id, competition_key)
);
CREATE INDEX IF NOT EXISTS idx_user_prefs_user ON user_preferences(telegram_id);

-- 7. api_usage_log
CREATE TABLE IF NOT EXISTS api_usage_log (
    id          SERIAL PRIMARY KEY,
    log_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    endpoint    TEXT NOT NULL,
    calls_made  INTEGER DEFAULT 1,
    logged_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_log_date ON api_usage_log(log_date);

-- ================================================================
-- View utile: call API per giorno (monitoring)
-- ================================================================
CREATE OR REPLACE VIEW api_calls_today AS
SELECT
    endpoint,
    COUNT(*) AS calls,
    MIN(logged_at) AS first_call,
    MAX(logged_at) AS last_call
FROM api_usage_log
WHERE log_date = CURRENT_DATE
GROUP BY endpoint
ORDER BY calls DESC;

-- ================================================================
-- View utile: report pronti per la settimana corrente
-- ================================================================
CREATE OR REPLACE VIEW weekly_reports AS
SELECT
    f.id AS fixture_id,
    c.name AS competition,
    f.home_team_name,
    f.away_team_name,
    f.match_date,
    f.status,
    r.report_text,
    r.is_updated,
    r.llm_model_used,
    r.generated_at
FROM fixtures f
JOIN competitions c ON c.id = f.competition_id
LEFT JOIN reports r ON r.fixture_id = f.id
WHERE f.week_start >= date_trunc('week', CURRENT_DATE)::date
ORDER BY f.match_date;
