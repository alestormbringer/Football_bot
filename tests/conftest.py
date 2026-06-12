"""
Variabili d'ambiente fittizie per i test: permettono di importare i moduli
che istanziano un client Supabase o un Bot Telegram a livello di modulo
(`scheduler.cron_runner`, `bot.telegram_handler`, `bot.notifier`) senza
credenziali reali e senza alcuna chiamata di rete (`create_client` e `Bot()`
non effettuano I/O alla creazione).
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-supabase-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-telegram-token")
os.environ.setdefault("FOOTBALL_DATA_API_KEY", "test-football-data-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "")
