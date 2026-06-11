import logging
from datetime import date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

from config.settings import TELEGRAM_TOKEN, COMPETITION_DISPLAY_NAMES, LEAGUES
from config.database import get_client

logger = logging.getLogger(__name__)
db = get_client()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start — registra utente e mostra selezione competizioni."""
    user = update.effective_user
    db.table("users").upsert({
        "telegram_id":   user.id,
        "username":      user.username,
        "first_name":    user.first_name,
        "language_code": user.language_code or "it",
    }).execute()

    await update.message.reply_text(
        f"👋 Ciao {user.first_name}! Seleziona le competizioni che vuoi seguire:",
        reply_markup=_build_competition_keyboard(user.id),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /help — elenco comandi disponibili."""
    await update.message.reply_text(
        "*Comandi disponibili:*\n"
        "/start — registrati e scegli le competizioni da seguire\n"
        "/pronostici — ricevi i pronostici della settimana per le tue competizioni\n"
        "/help — mostra questo messaggio",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_pronostici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /pronostici — invia i report della settimana filtrati per preferenze."""
    user_id = update.effective_user.id

    prefs_res = db.table("user_preferences") \
        .select("competition_key") \
        .eq("telegram_id", user_id) \
        .execute()
    prefs = [p["competition_key"] for p in (prefs_res.data or [])]

    if not prefs:
        await update.message.reply_text(
            "⚙️ Non hai ancora scelto le competizioni. Usa /start per configurarle."
        )
        return

    league_ids = [LEAGUES[k]["id"] for k in prefs if k in LEAGUES]

    if not league_ids:
        await update.message.reply_text("Nessuna competizione trovata.")
        return

    # Recupera fixtures della settimana
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    fixtures_res = db.table("fixtures") \
        .select("id, home_team_name, away_team_name, match_date") \
        .in_("competition_id", league_ids) \
        .gte("week_start", week_start) \
        .eq("status", "NS") \
        .order("match_date") \
        .execute()

    fixtures = fixtures_res.data or []
    if not fixtures:
        await update.message.reply_text("📭 Nessuna partita in programma questa settimana.")
        return

    sent = 0
    for f in fixtures:
        report_res = db.table("reports") \
            .select("report_text") \
            .eq("fixture_id", f["id"]) \
            .execute()
        if not report_res.data:
            continue
        text = report_res.data[0]["report_text"]
        await _safe_reply(update.message, text)
        sent += 1

    if sent == 0:
        await update.message.reply_text("⏳ Report in elaborazione, riprova più tardi.")


async def callback_competition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pulsanti selezione competizioni."""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    data = query.data  # formato: "comp_toggle:serie_a" o "comp_save"

    if data.startswith("comp_toggle:"):
        key = data.split(":", 1)[1]
        # Verifica se già presente
        existing = db.table("user_preferences") \
            .select("id") \
            .eq("telegram_id", user_id) \
            .eq("competition_key", key) \
            .execute()
        if existing.data:
            db.table("user_preferences") \
                .delete() \
                .eq("telegram_id", user_id) \
                .eq("competition_key", key) \
                .execute()
        else:
            db.table("user_preferences") \
                .insert({"telegram_id": user_id, "competition_key": key}) \
                .execute()
        # Aggiorna tastiera
        await query.edit_message_reply_markup(
            reply_markup=_build_competition_keyboard(user_id)
        )

    elif data == "comp_save":
        prefs_res = db.table("user_preferences") \
            .select("competition_key") \
            .eq("telegram_id", user_id) \
            .execute()
        count = len(prefs_res.data or [])
        await query.edit_message_text(
            f"✅ Preferenze salvate! Segui {count} competizioni.\n"
            f"Usa /pronostici per vedere i report del weekend."
        )


def _build_competition_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Costruisce la tastiera con stato attivo/inattivo per ogni competizione."""
    prefs_res = db.table("user_preferences") \
        .select("competition_key") \
        .eq("telegram_id", user_id) \
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


async def _safe_reply(message, text: str):
    """Invia un messaggio in Markdown, con fallback a testo semplice se il parsing fallisce."""
    try:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.warning("Markdown non valido, invio testo semplice: %s", e)
        await message.reply_text(text)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("pronostici", cmd_pronostici))
    app.add_handler(CallbackQueryHandler(callback_competition))
    return app
