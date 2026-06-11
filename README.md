# Football AI Bot

Bot Telegram che fornisce pronostici calcistici settimanali basati su dati reali
(API-Football v3), un modello statistico (Poisson) e generazione testuale via LLM
(OpenRouter). Pensato per girare in autonomia su un VPS (cron interni via APScheduler).

## Stack

- Python 3.11+
- [Supabase](https://supabase.com) (PostgreSQL hosted) — database centrale
- [API-Football v3](https://www.api-football.com/) — dati calcistici
- [OpenRouter](https://openrouter.ai/) — LLM (primario `google/gemini-2.0-flash-exp:free`,
  fallback `qwen/qwen3-8b:free`)
- [python-telegram-bot](https://docs.python-telegram-bot.org/) v20+
- APScheduler — job venerdì/sabato/domenica
- scipy / numpy — modello Poisson per le probabilità 1X2

## Struttura del progetto

```
config/
├── settings.py      # costanti, ID leghe, credenziali da .env
└── database.py       # client Supabase singleton

modules/
├── api_client.py      # wrapper API-Football con rate limiting e budget guard
├── scraper.py          # scraping RSS news calcio (opzionale, non usa budget API)
├── predictor_ml.py     # modello Poisson + feature engineering
└── report_generator.py # prompt building + chiamata OpenRouter

bot/
└── telegram_handler.py  # comandi Telegram (/start, /pronostici, /help)

scheduler/
└── cron_runner.py        # job APScheduler (venerdì fetch, sab/dom refresh)

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
# Compila .env con le tue credenziali (API-Football, Supabase, OpenRouter, Telegram)
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
- **Venerdì 06:00 UTC** — fetch completo (fixtures, classifiche, infortuni, H2H,
  calcolo probabilità ML, generazione report LLM)
- **Sabato/Domenica 08:00 UTC** — refresh leggero (infortuni aggiornati,
  rigenerazione report se cambia qualcosa)

## Comandi Telegram

- `/start` — registra l'utente e mostra la selezione delle competizioni da seguire
- `/pronostici` — invia i pronostici della settimana per le competizioni seguite
- `/help` — elenco comandi

## Documentazione

- [`docs/BUILD_SPEC.md`](docs/BUILD_SPEC.md) — specifica completa di build
- [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) — endpoint API-Football usati
- [`docs/SETUP_VPS.md`](docs/SETUP_VPS.md) — deploy su VPS Ubuntu (OVH)

## Budget API

Il piano gratuito API-Football è limitato a 100 call/giorno. Il client
(`modules/api_client.py`) controlla `/status` (gratuito) prima di ogni chiamata e
si ferma se restano meno di `CALL_SAFETY_BUFFER` call di margine. Il job di
venerdì usa al massimo ~90 call (fixtures + standings + injuries per lega +
H2H per partita); sabato/domenica usano solo poche call per gli infortuni in batch.
