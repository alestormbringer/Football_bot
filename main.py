import os
import logging
from scheduler.cron_runner import setup_scheduler
from bot.telegram_handler import build_application

os.makedirs("logs", exist_ok=True)

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
