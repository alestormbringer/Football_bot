# Football AI Bot

Bot Telegram che fornisce pronostici calcistici settimanali basati su dati reali
(football-data.org v4), un modello statistico (Poisson) e generazione testuale via LLM
(OpenRouter). Pensato per girare in autonomia su un VPS (cron interni via APScheduler).

## Stack

- Python 3.11+
- [Supabase](https://supabase.com) (PostgreSQL hosted) — database centrale
- [football-data.org v4](https://www.football-data.org/) — dati calcistici (piano Free,
  10 richieste/minuto)
- [OpenRouter](https://openrouter.ai/) — LLM (primario `qwen/qwen3-next-80b-a3b-instruct:free`,
  fallback `qwen/qwen3-coder:free`)
- [python-telegram-bot](https://docs.python-telegram-bot.org/) v21+
- APScheduler — job venerdì/sabato/domenica + fetch giornaliero tornei internazionali
- scipy / numpy — modello Poisson per le probabilità 1X2

## Struttura del progetto

```
config/
├── settings.py      # costanti, ID leghe, credenziali da .env
└── database.py       # client Supabase singleton

modules/
├── api_client.py      # wrapper football-data.org con rate limiting locale (10 req/min)
├── scraper.py          # scraping RSS news calcio (opzionale, non usa quota API)
├── predictor_ml.py     # modello Poisson + feature engineering
└── report_generator.py # prompt building + chiamata OpenRouter

bot/
└── telegram_handler.py  # comandi Telegram (/start, /pronostici, /help)

scheduler/
└── cron_runner.py        # job APScheduler (venerdì fetch, sab/dom refresh, fetch
                           # giornaliero tornei internazionali lun-gio)

main.py                    # entry point — avvia bot + scheduler
SUPABASE_SCHEMA.sql         # schema DB da eseguire su Supabase
docs/                       # documentazione di riferimento (build spec, API, deploy)
tests/                       # unit test (modello ML)
```

## Setup locale

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt   # include requirements.txt + pytest

cp .env.example .env
# Compila .env con le tue credenziali (football-data.org, Supabase, OpenRouter, Telegram)
```

Esegui lo schema `SUPABASE_SCHEMA.sql` nell'editor SQL di Supabase (rispetta l'ordine
delle tabelle, le foreign key dipendono da esso).

## Test

```bash
pytest
```

I test coprono il modello ML (`modules/predictor_ml.py`), che è puro e non richiede
credenziali esterne.

## Avvio

```bash
python main.py
```

Lo scheduler esegue automaticamente:
- **Venerdì 06:00 UTC** — fetch completo (fixtures, classifiche, H2H,
  calcolo probabilità ML, generazione report LLM)
- **Sabato/Domenica 08:00 UTC** — refresh leggero (classifiche aggiornate,
  rigenerazione report se cambiano forma/posizione delle squadre)
- **Lunedì-Giovedì 06:00 UTC** — fetch giornaliero per i tornei internazionali
  (Mondiali, Europei) attivi, che giocano anche infrasettimanalmente

## Comandi Telegram

- `/start` — registra l'utente e mostra la selezione delle competizioni da seguire
- `/pronostici` — invia i pronostici della settimana per le competizioni seguite
- `/help` — elenco comandi

## Documentazione

- [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) — specifica completa di build
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — endpoint football-data.org usati
- [`docs/SETUP_VPS.md`](docs/SETUP_VPS.md) — deploy su VPS Ubuntu (OVH)

## Limiti API

Il piano gratuito di football-data.org è limitato a 10 richieste/minuto (nessun
tetto giornaliero). Il client (`modules/api_client.py`) applica una sliding
window locale e attende automaticamente se il limite viene raggiunto. Il piano
Free copre: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions
League, FIFA World Cup e UEFA Euro. Non copre infortuni/lineup né altre coppe
(Europa League, Conference League, coppe nazionali, Nations League).
