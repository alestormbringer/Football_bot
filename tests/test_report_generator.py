from unittest.mock import patch, MagicMock

import requests

from config.settings import LLM_PRIMARY, LLM_FALLBACK, OPENROUTER_DAILY_WARN_LIMIT
from modules.report_generator import (
    build_match_prompt,
    generate_report,
    generate_report_with_fallback,
    _warn_if_quota_near_limit,
)

BASE_PROMPT_KWARGS = dict(
    home_team="Juventus",
    away_team="Milan",
    competition="Serie A",
    match_date="2026-06-13",
    home_form="WWDLW",
    away_form="LWWDD",
    home_position=1,
    away_position=4,
    ml_probs={
        "home_win": 0.5, "draw": 0.25, "away_win": 0.25,
        "expected_home": 1.8, "expected_away": 1.1, "over_25": 0.55,
    },
    h2h_summary="Juventus 2-1 Milan | Milan 0-0 Juventus",
    injuries_home=[],
    injuries_away=[],
)


def test_build_match_prompt_includes_news_summary():
    prompt = build_match_prompt(**BASE_PROMPT_KWARGS, news_summary="Juventus cambia allenatore")
    assert "Notizie recenti: Juventus cambia allenatore" in prompt


def test_build_match_prompt_defaults_news_text_when_empty():
    prompt = build_match_prompt(**BASE_PROMPT_KWARGS)
    assert "Notizie recenti: nessuna novità rilevante" in prompt


def _mock_response(status_code, json_data=None, headers=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_data or {}
    if status_code == 200:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
    return resp


def test_generate_report_success():
    resp = _mock_response(200, {"choices": [{"message": {"content": " Report generato "}}]})
    with patch("modules.report_generator.requests.post", return_value=resp):
        text = generate_report("prompt", model="some-model")

    assert text == "Report generato"


def test_generate_report_retries_on_429_then_succeeds():
    resp_429 = _mock_response(429, headers={"Retry-After": "0"})
    resp_ok = _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    with patch("modules.report_generator.requests.post", side_effect=[resp_429, resp_ok]), \
            patch("modules.report_generator.time.sleep"):
        text = generate_report("prompt", model="some-model", retries=2)

    assert text == "ok"


def test_generate_report_returns_none_after_exhausting_429_retries():
    resp_429 = _mock_response(429, headers={"Retry-After": "0"})

    with patch("modules.report_generator.requests.post", return_value=resp_429), \
            patch("modules.report_generator.time.sleep"):
        text = generate_report("prompt", model="some-model", retries=1)

    assert text is None


@patch("modules.report_generator.notify_admin")
@patch("modules.report_generator.get_client")
def test_generate_report_with_fallback_logs_primary_success(mock_get_client, mock_notify):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(count=1)
    mock_get_client.return_value = db

    resp = _mock_response(200, {"choices": [{"message": {"content": "primary ok"}}]})
    with patch("modules.report_generator.requests.post", return_value=resp):
        text, model = generate_report_with_fallback("prompt")

    assert (text, model) == ("primary ok", LLM_PRIMARY)

    logged = db.table.return_value.insert.call_args[0][0]
    assert logged["model"] == LLM_PRIMARY
    assert logged["success"] is True
    mock_notify.assert_not_called()


@patch("modules.report_generator.notify_admin")
@patch("modules.report_generator.get_client")
def test_generate_report_with_fallback_uses_fallback_on_primary_failure(mock_get_client, mock_notify):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(count=1)
    mock_get_client.return_value = db

    fail_resp = _mock_response(500)
    ok_resp = _mock_response(200, {"choices": [{"message": {"content": "fallback ok"}}]})

    # 3 tentativi falliti (default retries=2) per il primario, poi successo al fallback
    with patch("modules.report_generator.requests.post",
               side_effect=[fail_resp, fail_resp, fail_resp, ok_resp]), \
            patch("modules.report_generator.time.sleep"):
        text, model = generate_report_with_fallback("prompt")

    assert (text, model) == ("fallback ok", LLM_FALLBACK)


@patch("modules.report_generator.notify_admin")
@patch("modules.report_generator.get_client")
def test_generate_report_with_fallback_both_fail(mock_get_client, mock_notify):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(count=1)
    mock_get_client.return_value = db

    fail_resp = _mock_response(500)
    with patch("modules.report_generator.requests.post", return_value=fail_resp), \
            patch("modules.report_generator.time.sleep"):
        text, model = generate_report_with_fallback("prompt")

    assert (text, model) == (None, "none")


@patch("modules.report_generator.notify_admin")
@patch("modules.report_generator.get_client")
def test_warn_if_quota_near_limit_notifies_admin_at_threshold(mock_get_client, mock_notify):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = \
        MagicMock(count=OPENROUTER_DAILY_WARN_LIMIT)
    mock_get_client.return_value = db

    _warn_if_quota_near_limit()

    mock_notify.assert_called_once()
    assert str(OPENROUTER_DAILY_WARN_LIMIT) in mock_notify.call_args[0][0]


@patch("modules.report_generator.notify_admin")
@patch("modules.report_generator.get_client")
def test_warn_if_quota_near_limit_silent_below_threshold(mock_get_client, mock_notify):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = \
        MagicMock(count=OPENROUTER_DAILY_WARN_LIMIT - 1)
    mock_get_client.return_value = db

    _warn_if_quota_near_limit()

    mock_notify.assert_not_called()
