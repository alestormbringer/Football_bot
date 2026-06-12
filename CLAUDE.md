# Football AI Bot — CLAUDE.md

Guida di riferimento per Claude Code (e per chiunque riprenda il progetto) con
lo stato attuale, le decisioni prese e i comandi utili.

## Cos'è il progetto

Bot Telegram che invia pronostici calcistici settimanali generati da:
1. Dati reali (fixtures, classifiche, scontri diretti) da **football-data.org v4**
2. Un modello statistico **Poisson** (probabilità 1X2, gol attesi, Over 2.5)
3. Un report testuale in italiano generato via **LLM** (OpenRouter, modelli `:free`)

Gira in autonomia su un VPS (Ubuntu) tramite **APScheduler** (cron interni) +
**python-telegram-bot** (polling).

## Stack

- Python 3.11+
- [Supabase](https://supabase.com) (PostgreSQL hosted) — `config/database.py`, schema in `SUPABASE_SCHEMA.sql`
- [football-data.org v4](https://www.football-data.org/) — piano Free, 10 richieste/minuto
- [OpenRouter](https://openrouter.ai/) — LLM, vedi sezione "Modelli LLM"
- [python-telegram-bot](https://docs.python-telegram-bot.org/) v21
- APScheduler — job pianificati
- scipy / numpy — modello Poisson (`modules/predictor_ml.py`)

## Struttura del progetto

```
config/
├── settings.py        # costanti, ID leghe, credenziali da .env
└── database.py         # client Supabase singleton

modules/
├── api_client.py        # FootballDataClient — wrapper football-data.org con rate limit locale
├── predictor_ml.py       # modello Poisson + feature engineering (puro, testato)
├── report_generator.py    # prompt building + chiamata OpenRouter (retry su 429, log uso LLM)
└── scraper.py             # scraping RSS news calcio — integrato nel prompt (get_match_news_summary)

bot/
├── telegram_handler.py     # comandi Telegram: /start, /pronostici, /help
└── notifier.py              # invio automatico report agli iscritti + alert admin (job falliti, quota OpenRouter)

scheduler/
└── cron_runner.py           # job APScheduler (vedi sezione "Job pianificati")

main.py                       # entry point — avvia scheduler + bot Telegram (polling)
SUPABASE_SCHEMA.sql            # schema DB da eseguire su Supabase (idempotente)
deploy/
└── football-bot.service       # unit systemd (Restart=always) per il deploy in produzione
docs/
├── BUILD_SPEC.md             # spec di build originale (ora con nota di migrazione in testa)
├── API_REFERENCE.md          # reference endpoint football-data.org v4 usati
└── SETUP_VPS.md              # comandi di deploy/test sul VPS (incl. systemd)
tests/
├── conftest.py               # env fittizie per import moduli che istanziano client Supabase/Telegram
├── test_predictor_ml.py      # unit test del modello ML (10 test)
├── test_scraper.py            # RSS news + get_match_news_summary
├── test_report_generator.py   # prompt, retry/fallback OpenRouter, log uso LLM, alert quota
├── test_notifier.py           # broadcast report agli iscritti, alert admin
├── test_cron_runner.py        # helper normalizzazione fixture/standings/H2H, _process_fixture
└── test_telegram_handler.py   # tastiera onboarding raggruppata (COMPETITION_GROUPS)
```

> I documenti originali di specifica caricati a inizio progetto (`BUILD_SPEC.md`,
> `API_REFERENCE.md`, `SETUP_VPS.md`, `.env.example`, `SUPABASE_SCHEMA.sql`)
> sono confluiti e mantenuti aggiornati nelle stesse posizioni dentro `docs/`
> e nella root del repo — non esiste una copia separata da consultare.

## Competizioni configurate (`config/settings.py` → `LEAGUES`)

Piano Free football-data.org, 8 competizioni:

| Chiave            | Codice | ID   | Tipo   | Internazionale |
|-------------------|--------|------|--------|-----------------|
| `premier_league`  | PL     | 2021 | league | no              |
| `la_liga`         | PD     | 2014 | league | no              |
| `serie_a`         | SA     | 2019 | league | no              |
| `bundesliga`      | BL1    | 2002 | league | no              |
| `ligue_1`         | FL1    | 2015 | league | no              |
| `champions`       | CL     | 2001 | cup    | no              |
| `world_cup`       | WC     | 2000 | cup    | **sì**          |
| `euro`            | EC     | 2018 | cup    | **sì**          |

**Non disponibili** sul piano Free (rimosse dal progetto): Europa League,
Conference League, FA Cup, Coppa Italia, Copa del Rey, Nations League.
**Non disponibili su nessun piano**: infortuni e formazioni (lineups) — la
sezione "infortuni" del report è quindi sempre "nessun infortunio noto".

## Job pianificati (`scheduler/cron_runner.py` → `setup_scheduler`)

Tutti gli orari sono **UTC**.

| Job                          | Quando            | Cosa fa |
|-------------------------------|--------------------|---------|
| `friday_full_fetch`            | Venerdì 06:00      | Fixtures venerdì→lunedì per tutte le 8 competizioni, classifiche, H2H, calcolo ML, generazione report LLM |
| `saturday_refresh` / `sunday_refresh` (= `daily_refresh`) | Sabato/Domenica 08:00 | Riscarica le classifiche delle leghe con partite quel giorno; se forma/posizione di una squadra sono cambiate, ricalcola ML e rigenera il report con `is_updated=True` |
| `international_daily_fetch`    | Lunedì-Giovedì 06:00 | Per i tornei internazionali attivi (`world_cup`, `euro`): fixtures di OGGI, classifiche, H2H, ML, report. Copre i giorni infrasettimanali dei Mondiali/Europei (il weekend è già coperto da `friday_full_fetch`) |

Ogni job logga durata totale a fine esecuzione e registra un listener
APScheduler (`_on_job_error`, `EVENT_JOB_ERROR`) che notifica l'admin via
Telegram se un job solleva un'eccezione non gestita.

### Invio automatico dei pronostici

Ogni volta che `_process_fixture`/`daily_refresh` genera o aggiorna un
report, `bot/notifier.py::broadcast_report` lo invia subito a tutti gli
utenti che seguono quella competizione (`user_preferences`), con prefisso
"🔄 Aggiornamento pronostico" per i report rigenerati nel weekend.
`/pronostici` resta disponibile per consultare on-demand i report già
generati (es. dopo un `/start` tardivo).

### News RSS nel prompt

`modules/scraper.py::get_match_news_summary(home_team, away_team)` recupera
i titoli più recenti dai feed RSS per le due squadre e viene passato come
`news_summary` a `build_match_prompt` (sezione "Notizie recenti" del prompt;
"nessuna novità rilevante" se vuoto o in caso di errore di rete — non blocca
mai la generazione del report).

## Modelli LLM (`config/settings.py`)

```python
LLM_PRIMARY   = "openrouter/free"        # router automatico tra modelli :free disponibili
LLM_FALLBACK  = "qwen/qwen3-coder:free"
LLM_MAX_TOKENS = 1200
```

`modules/report_generator.py::generate_report` ritenta su 429 rispettando
`Retry-After` (header o `error.metadata.retry_after_seconds`, formato
OpenRouter), fino a 2 tentativi, poi passa al fallback.

**Limite piano Free OpenRouter**: 50 richieste/giorno su modelli `:free` senza
almeno $10 di credito sull'account; con $10+ di credito sale a 1000/giorno.
Se in produzione iniziano a comparire molti "Report fallito per fixture N" nel
weekend (tante partite = tante chiamate), valutare di aggiungere credito.

Ogni chiamata (primary o fallback, successo o fallimento) viene loggata in
`llm_usage_log` (vista `llm_calls_today`). Al raggiungimento di
`OPENROUTER_DAILY_WARN_LIMIT` (45, in `config/settings.py`) chiamate nello
stesso giorno, `_warn_if_quota_near_limit` invia un avviso una tantum
all'admin via `notify_admin`.

## Database (Supabase)

Schema completo in `SUPABASE_SCHEMA.sql` (idempotente, usa `IF NOT EXISTS` /
`ON CONFLICT DO NOTHING`). Tabelle principali:

- `competitions` — seed con le 8 competizioni football-data.org (id = ID football-data.org)
- `fixtures` — partite (PK = id football-data.org)
- `fixture_stats` — statistiche/probabilità ML per fixture (`fixture_id` UNIQUE, **non** PK)
- `reports` — report LLM per fixture (`fixture_id` UNIQUE, **non** PK)
- `users` / `user_preferences` — utenti Telegram e competizioni seguite
- `api_usage_log` — log chiamate football-data.org (monitoring, nessun limite giornaliero applicato)
- `llm_usage_log` — log chiamate OpenRouter (model, success), vista `llm_calls_today` per monitorare la quota giornaliera

> ⚠️ **Importante per gli upsert**: `fixture_stats` e `reports` hanno `id`
> SERIAL come PK ma il vincolo di unicità reale è su `fixture_id`. Gli upsert
> in `cron_runner.py` usano `on_conflict="fixture_id"` — se si aggiungono
> nuovi upsert su queste tabelle, ricordarsi di specificarlo, altrimenti
> Postgres tenta un INSERT e fallisce con `duplicate key value violates
> unique constraint "..._fixture_id_key"`.

## Variabili d'ambiente (`.env`, vedi `.env.example`)

```
FOOTBALL_DATA_API_KEY   # https://www.football-data.org/client/register
SUPABASE_URL            # https://xxxxx.supabase.co
SUPABASE_KEY            # service/secret key (formato sb_secret_...)
OPENROUTER_API_KEY      # https://openrouter.ai/keys
TELEGRAM_BOT_TOKEN      # da @BotFather
ADMIN_TELEGRAM_ID       # opzionale — ID Telegram admin per alert job falliti / quota OpenRouter
```

`API_FOOTBALL_KEY` (vecchia integrazione) **non è più usata** — può essere
rimossa da `.env`.

## Storia recente / decisioni prese

1. **Upgrade supabase-py 2.4.6 → 2.31.0** (+ `httpx==0.27.2`): le nuove
   chiavi Supabase (`sb_secret_...`/`sb_publishable_...`) non passano la
   regex JWT validata da supabase-py < 2.x → "Invalid API key". Risolto
   aggiornando la dipendenza (commit `16266c9`).
2. **Migrazione completa da API-Football v3 a football-data.org v4** (commit
   `511bb63`): il piano Free di API-Football non copre le stagioni 2025/26 né
   il Mondiale 2026 (`"Free plans do not have access to this season, try from
   2022 to 2024"`). Nuovo `FootballDataClient` con rate limit a sliding
   window (10 req/min, nessun tetto giornaliero), `LEAGUES` ridotto alle 8
   competizioni disponibili sul Free, rimossa la feature infortuni,
   `cron_runner.py` riscritto per il nuovo formato risposte e per il fallback
   classifiche TOTAL→HOME/AWAY (gironi Mondiale).
3. **Retry con backoff per OpenRouter** (commit `e1dd49b`): i modelli `:free`
   vanno spesso in 429 upstream (provider condiviso, es. "Venice" per Qwen).
4. **Fix upsert `fixture_stats`/`reports`** (commit `d41512c`): vedi nota sopra
   su `on_conflict="fixture_id"`.
5. **`LLM_PRIMARY` → `openrouter/free`** (commit `1474e2f`): router automatico
   tra modelli `:free` disponibili, per evitare congestione su un singolo
   provider.
6. **Invio automatico, news RSS, monitoring e alerting** (sessione
   2026-06-12): `bot/notifier.py` invia subito ogni report agli iscritti
   (`broadcast_report`) invece di affidarsi solo a `/pronostici`;
   `modules/scraper.py` ora è collegato al prompt via
   `get_match_news_summary`; tastiera onboarding raggruppata per
   `COMPETITION_GROUPS`; nuova tabella `llm_usage_log` + avviso admin a 45
   chiamate OpenRouter/giorno; listener APScheduler che notifica l'admin sui
   job falliti; nuovo unit systemd (`deploy/football-bot.service`,
   `Restart=always`) consigliato al posto di `nohup`; aggiunta suite di test
   per `scraper`, `report_generator`, `notifier`, `cron_runner` e
   `telegram_handler` (52 test totali).

**Stato verificato (2026-06-11, giorno di inizio Mondiale 2026)**:
end-to-end testato con successo sul VPS — `international_daily_fetch()` ha
scaricato la partita Mexico vs South Africa (Gruppo A), calcolato classifiche
+ probabilità ML, generato il report via `openrouter/free` e salvato tutto su
Supabase. Bot Telegram avviato in produzione con `nohup` (polling attivo,
scheduler con 4 job).

## Sviluppo

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt + pytest

cp .env.example .env   # compilare con credenziali reali, MAI committare .env

pytest   # 52 test (predictor_ml, scraper, report_generator, notifier,
         # cron_runner, telegram_handler). tests/conftest.py imposta env
         # fittizie: non servono credenziali reali né accesso di rete.
```

## Branch e workflow git

- Sviluppo su `claude/hopeful-ride-txfs91`, poi fast-forward merge su `main`
  e push di entrambi.
- **Mai committare `.env`**, mai incollare chiavi/token reali in chat — se
  esposte per errore, vanno rigenerate (Supabase, football-data.org,
  OpenRouter, BotFather per il token Telegram).

## Deploy VPS

Vedi [`docs/SETUP_VPS.md`](docs/SETUP_VPS.md) per i comandi completi (setup
ambiente, test connessioni, deploy come servizio **systemd**
(`deploy/football-bot.service`, `Restart=always` — riavvio automatico dopo
crash/reboot), monitoraggio log e report su Supabase).

## Da fare / possibili prossimi passi

- Verificare in produzione che l'invio automatico dei report
  (`broadcast_report`) non saturi i limiti dell'API Telegram con molti
  iscritti contemporanei (attualmente 0.05s di pausa tra un invio e l'altro).
- Se si configura `ADMIN_TELEGRAM_ID`, verificare che l'admin riceva
  correttamente gli alert (job falliti, quota OpenRouter) dopo il primo
  deploy.
- Valutare se aggiungere un comando `/stop` (rimozione rapida di tutte le
  preferenze) ora che i pronostici arrivano in automatico.
