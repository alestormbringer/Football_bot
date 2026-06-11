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

# Test connessione API-Football
python3 -c "
from modules.api_client import APIFootballClient
api = APIFootballClient()
rem = api.get_remaining_calls()
print(f'Call rimanenti oggi: {rem}')
"

# Test connessione Supabase
python3 -c "
from config.database import get_client
db = get_client()
result = db.table('competitions').select('name').execute()
print([r['name'] for r in result.data])
"

# Test fetch manuale (senza aspettare venerdì)
python3 -c "
from scheduler.cron_runner import friday_full_fetch
friday_full_fetch()
"
```

## Avvio in produzione

```bash
# Con nohup (sopravvive alla disconnessione SSH)
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

# Controlla call API usate oggi (da terminale)
curl -s https://v3.football.api-sports.io/status \
  -H "x-apisports-key: $API_FOOTBALL_KEY" | python3 -m json.tool

# Controlla uso call da Supabase (SQL editor)
SELECT * FROM api_calls_today;

# Controlla report della settimana
SELECT competition, home_team_name, away_team_name, match_date,
       is_updated, llm_model_used
FROM weekly_reports
ORDER BY match_date;
```

## Aggiornare la stagione (ogni anno ad agosto)

1. Aggiornare `CURRENT_SEASON` nel `.env`
2. Aggiornare il campo `season` nella tabella `competitions` su Supabase:
   ```sql
   UPDATE competitions SET season = 2026 WHERE season = 2025;
   ```
3. Riavviare il bot

## Struttura log attesa (avvio corretto)

```
2025-08-22 06:00:01 [INFO] __main__: Avvio Football AI Bot...
2025-08-22 06:00:01 [INFO] __main__: Scheduler avviato. Jobs: ['friday_fetch', 'saturday_refresh', 'sunday_refresh']
2025-08-22 06:00:01 [INFO] __main__: Bot Telegram in polling...
# ... silenzio fino a venerdì 06:00 UTC ...
2025-08-22 06:00:00 [INFO] cron_runner: === FRIDAY FETCH START ===
2025-08-22 06:00:00 [INFO] cron_runner: Call rimanenti prima del fetch: 100
2025-08-22 06:00:05 [INFO] cron_runner: Lega premier_league: 10 partite scaricate
...
```
