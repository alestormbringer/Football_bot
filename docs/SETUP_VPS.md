# Setup VPS & Deploy

## Prerequisiti sul VPS OVH (Ubuntu 24.04)

```bash
# Aggiorna sistema
sudo apt update && sudo apt upgrade -y

# Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# Strumenti utili
sudo apt install -y git curl nano screen

# Crea cartella progetto
mkdir -p ~/football-ai-bot/logs
cd ~/football-ai-bot
```

## Setup ambiente Python

```bash
python3.11 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

## File .env

```bash
cp .env.example .env
nano .env  # Inserisci le credenziali reali
```

## Primo avvio — test manuale

```bash
# Attiva venv
source venv/bin/activate

# Test connessione football-data.org
python3 -c "
from modules.api_client import FootballDataClient
api = FootballDataClient()
data = api.get_matches('WC', '2026-06-11', '2026-06-11')
print(f'Partite Mondiale oggi: {len(data)}')
"

# Test connessione Supabase
python3 -c "
from config.database import get_client
db = get_client()
result = db.table('competitions').select('name').execute()
print([r['name'] for r in result.data])
"

# Test fetch giornaliero tornei internazionali (Mondiale/Europei)
python3 -c "
from scheduler.cron_runner import international_daily_fetch
international_daily_fetch()
"

# Test fetch manuale weekend (senza aspettare venerdì)
python3 -c "
from scheduler.cron_runner import friday_full_fetch
friday_full_fetch()
"
```

## Avvio in produzione (consigliato: systemd)

`Restart=always` fa ripartire automaticamente il bot dopo un crash, un
errore non gestito o un reboot del VPS — niente `nohup`/`screen` da
tenere d'occhio manualmente.

```bash
# Adatta User= e i percorsi se necessario, poi installa l'unit
sudo cp deploy/football-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/football-bot.service

sudo systemctl daemon-reload
sudo systemctl enable --now football-bot

# Verifica stato e log
sudo systemctl status football-bot
journalctl -u football-bot -f
# oppure, dato che lo unit scrive anche su file:
tail -f ~/football-ai-bot/logs/bot.log

# Riavvio manuale dopo un deploy/aggiornamento codice
sudo systemctl restart football-bot

# Fermare il bot
sudo systemctl stop football-bot
```

## Avvio alternativo (nohup, solo per test rapidi)

```bash
# Con nohup (sopravvive alla disconnessione SSH, ma NON riparte da sola dopo un crash)
nohup python3 main.py > logs/bot.log 2>&1 &
echo $! > logs/bot.pid

# Verifica avvio
tail -f logs/bot.log

# Fermare il bot
kill $(cat logs/bot.pid)
```

## Monitoraggio

```bash
# Log in tempo reale
tail -f ~/football-ai-bot/logs/bot.log

# Controlla chiamate API loggate da Supabase (SQL editor)
SELECT * FROM api_calls_today;

# Controlla consumo OpenRouter (limite Free: 50/giorno senza credito)
SELECT * FROM llm_calls_today;

# Controlla report della settimana
SELECT competition, home_team_name, away_team_name, match_date,
       is_updated, llm_model_used
FROM weekly_reports
ORDER BY match_date;
```

Se `ADMIN_TELEGRAM_ID` è configurato in `.env`, l'amministratore riceve un
messaggio Telegram automatico quando:
- un job pianificato (`friday_full_fetch`, `daily_refresh`,
  `international_daily_fetch`) solleva un'eccezione non gestita;
- si raggiungono 45 chiamate OpenRouter nella giornata (soglia di avviso
  prima del limite di 50/giorno del piano Free).

Il piano Free di football-data.org non ha un tetto giornaliero, solo il
limite di 10 richieste/minuto gestito automaticamente dal client — non serve
nessun controllo di "budget residuo" come con la vecchia integrazione
API-Football.

## Aggiornare la stagione (ogni anno ad agosto)

Aggiornare il campo `season` nella tabella `competitions` su Supabase (a
scopo informativo — football-data.org restituisce sempre la stagione
corrente senza bisogno di specificarla):
```sql
UPDATE competitions SET season = 2026 WHERE season = 2025;
```

## Struttura log attesa (avvio corretto)

```
2026-06-08 06:00:01 [INFO] __main__: Avvio Football AI Bot...
2026-06-08 06:00:01 [INFO] __main__: Scheduler avviato. Jobs: ['friday_fetch', 'saturday_refresh', 'sunday_refresh', 'international_daily_fetch']
2026-06-08 06:00:01 [INFO] __main__: Bot Telegram in polling...
# ... silenzio fino al prossimo job pianificato ...
2026-06-08 06:00:00 [INFO] cron_runner: === FRIDAY FETCH START ===
2026-06-08 06:00:05 [INFO] cron_runner: Lega premier_league: 10 partite scaricate
...
2026-06-11 06:00:00 [INFO] cron_runner: === INTERNATIONAL DAILY FETCH START ===
2026-06-11 06:00:02 [INFO] cron_runner: Torneo world_cup: 2 partite oggi
...
```
