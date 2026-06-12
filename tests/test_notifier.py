from unittest.mock import patch, MagicMock, AsyncMock

from telegram.error import BadRequest

from bot import notifier


@patch("bot.notifier.get_client")
@patch("bot.notifier.Bot")
def test_broadcast_report_sends_to_followers(mock_bot_cls, mock_get_client):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"telegram_id": 111}, {"telegram_id": 222}]
    )
    mock_get_client.return_value = db

    bot_instance = mock_bot_cls.return_value
    bot_instance.send_message = AsyncMock()

    notifier.broadcast_report(competition_id=2019, fixture_id=1, text="Report testo")

    assert bot_instance.send_message.call_count == 2
    sent_chat_ids = {c.kwargs["chat_id"] for c in bot_instance.send_message.call_args_list}
    assert sent_chat_ids == {111, 222}
    for call in bot_instance.send_message.call_args_list:
        assert call.kwargs["text"] == "Report testo"


@patch("bot.notifier.get_client")
@patch("bot.notifier.Bot")
def test_broadcast_report_no_followers_skips_send(mock_bot_cls, mock_get_client):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_get_client.return_value = db

    notifier.broadcast_report(competition_id=2019, fixture_id=1, text="Report testo")

    mock_bot_cls.return_value.send_message.assert_not_called()


@patch("bot.notifier.get_client")
@patch("bot.notifier.Bot")
def test_broadcast_report_unknown_competition_skips(mock_bot_cls, mock_get_client):
    notifier.broadcast_report(competition_id=999999, fixture_id=1, text="x")

    mock_get_client.assert_not_called()
    mock_bot_cls.assert_not_called()


@patch("bot.notifier.get_client")
@patch("bot.notifier.Bot")
def test_broadcast_report_updated_adds_prefix(mock_bot_cls, mock_get_client):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"telegram_id": 111}]
    )
    mock_get_client.return_value = db

    bot_instance = mock_bot_cls.return_value
    bot_instance.send_message = AsyncMock()

    notifier.broadcast_report(competition_id=2019, fixture_id=1, text="Report testo", is_updated=True)

    sent_text = bot_instance.send_message.call_args.kwargs["text"]
    assert sent_text.startswith("🔄 *Aggiornamento pronostico*")
    assert "Report testo" in sent_text


@patch("bot.notifier.get_client")
@patch("bot.notifier.Bot")
def test_broadcast_falls_back_to_plain_text_on_bad_markdown(mock_bot_cls, mock_get_client):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"telegram_id": 111}]
    )
    mock_get_client.return_value = db

    bot_instance = mock_bot_cls.return_value
    bot_instance.send_message = AsyncMock(side_effect=[BadRequest("can't parse entities"), None])

    notifier.broadcast_report(competition_id=2019, fixture_id=1, text="*markdown rotto")

    assert bot_instance.send_message.call_count == 2
    second_call_kwargs = bot_instance.send_message.call_args_list[1].kwargs
    assert "parse_mode" not in second_call_kwargs


@patch("bot.notifier.Bot")
def test_notify_admin_noop_when_not_configured(mock_bot_cls):
    with patch("bot.notifier.ADMIN_TELEGRAM_ID", None):
        notifier.notify_admin("test")

    mock_bot_cls.assert_not_called()


@patch("bot.notifier.Bot")
def test_notify_admin_sends_to_admin(mock_bot_cls):
    bot_instance = mock_bot_cls.return_value
    bot_instance.send_message = AsyncMock()

    with patch("bot.notifier.ADMIN_TELEGRAM_ID", 999):
        notifier.notify_admin("Job falliti")

    bot_instance.send_message.assert_called_once()
    assert bot_instance.send_message.call_args.kwargs["chat_id"] == 999
    assert bot_instance.send_message.call_args.kwargs["text"] == "Job falliti"
