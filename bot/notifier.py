"""
Notifiche push: invio automatico dei report agli utenti iscritti e
avvisi all'amministratore in caso di errori o di consumo OpenRouter elevato.

Pensato per essere chiamato da `scheduler/cron_runner.py`, che gira in
thread separati (APScheduler `BackgroundScheduler`): ogni invio crea un
proprio event loop con `asyncio.run`.
"""
import asyncio
import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError

from config.settings import TELEGRAM_TOKEN, ADMIN_TELEGRAM_ID, LEAGUE_ID_MAP
from config.database import get_client

logger = logging.getLogger(__name__)

# Pausa fra un invio e l'altro per restare sotto i limiti dell'API Telegram
# (~30 messaggi/secondo verso chat diverse).
_SEND_DELAY_SECONDS = 0.05


async def _send_text(bot: Bot, chat_id: int, text: str) -> None:
    """Invia un messaggio in Markdown, con fallback a testo semplice se il parsing fallisce."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.warning("Markdown non valido per %s, invio testo semplice: %s", chat_id, e)
        await bot.send_message(chat_id=chat_id, text=text)


async def _broadcast(chat_ids: list[int], text: str) -> None:
    bot = Bot(TELEGRAM_TOKEN)
    for chat_id in chat_ids:
        try:
            await _send_text(bot, chat_id, text)
        except Forbidden:
            logger.info("Utente %s ha bloccato il bot, salto", chat_id)
        except TelegramError as e:
            logger.warning("Invio a %s fallito: %s", chat_id, e)
        await asyncio.sleep(_SEND_DELAY_SECONDS)


def broadcast_report(competition_id: int, fixture_id: int, text: str, is_updated: bool = False) -> None:
    """
    Invia un report a tutti gli utenti che seguono la competizione della
    fixture. Chiamato dopo la generazione/aggiornamento di un report nei
    job pianificati (`cron_runner.py`).
    """
    competition_key = LEAGUE_ID_MAP.get(competition_id)
    if not competition_key:
        return

    db = get_client()
    prefs_res = db.table("user_preferences") \
        .select("telegram_id") \
        .eq("competition_key", competition_key) \
        .execute()
    chat_ids = [p["telegram_id"] for p in (prefs_res.data or [])]
    if not chat_ids:
        return

    prefix = "🔄 *Aggiornamento pronostico*\n\n" if is_updated else ""
    asyncio.run(_broadcast(chat_ids, prefix + text))
    logger.info("Report fixture %d inviato a %d utenti", fixture_id, len(chat_ids))


def notify_admin(message: str) -> None:
    """Invia un messaggio di servizio all'amministratore (se configurato)."""
    if not ADMIN_TELEGRAM_ID:
        logger.debug("ADMIN_TELEGRAM_ID non configurato, avviso solo loggato: %s", message)
        return
    try:
        asyncio.run(_broadcast([ADMIN_TELEGRAM_ID], message))
    except Exception as e:
        logger.error("Invio notifica admin fallito: %s", e)
