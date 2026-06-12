import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from bot.telegram_handler import _build_competition_keyboard, callback_competition
from config.settings import COMPETITION_GROUPS


@patch("bot.telegram_handler.db")
def test_keyboard_has_one_header_row_per_group(mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    keyboard = _build_competition_keyboard(user_id=1)
    rows = keyboard.inline_keyboard

    expected_rows = sum(1 + len(keys) for keys in COMPETITION_GROUPS.values()) + 1  # + "Salva"
    assert len(rows) == expected_rows

    header_texts = [row[0].text for row in rows if row[0].callback_data == "noop"]
    assert header_texts == [f"— {name} —" for name in COMPETITION_GROUPS]


@patch("bot.telegram_handler.db")
def test_keyboard_marks_active_competitions(mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"competition_key": "serie_a"}]
    )

    keyboard = _build_competition_keyboard(user_id=1)
    buttons = [b for row in keyboard.inline_keyboard for b in row]

    serie_a_btn = next(b for b in buttons if b.callback_data == "comp_toggle:serie_a")
    assert serie_a_btn.text.startswith("✅")

    other_btn = next(b for b in buttons if b.callback_data == "comp_toggle:premier_league")
    assert other_btn.text.startswith("⬜")


@patch("bot.telegram_handler.db")
def test_callback_noop_answers_without_touching_db(mock_db):
    query = MagicMock()
    query.data = "noop"
    query.answer = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    asyncio.run(callback_competition(update, MagicMock()))

    query.answer.assert_called_once()
    mock_db.table.assert_not_called()
