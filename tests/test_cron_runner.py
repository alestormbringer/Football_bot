from datetime import date
from unittest.mock import patch, MagicMock

from scheduler.cron_runner import (
    get_weekend_range,
    get_week_start,
    _build_fixture_row,
    _summarize_h2h,
    _get_league_name,
    _build_standings_cache,
    _process_fixture,
    _on_job_error,
)


def test_get_weekend_range_returns_friday_to_monday():
    friday_str, monday_str = get_weekend_range()
    friday = date.fromisoformat(friday_str)
    monday = date.fromisoformat(monday_str)

    assert friday.weekday() == 4  # venerdì
    assert monday.weekday() == 0  # lunedì
    assert (monday - friday).days == 3


def test_get_week_start_is_monday():
    week_start = get_week_start()
    assert week_start.weekday() == 0


def test_build_fixture_row_normalizes_match():
    m = {
        "id": 12345,
        "homeTeam": {"id": 1, "name": "Juventus"},
        "awayTeam": {"id": 2, "name": "Milan"},
        "utcDate": "2026-06-13T18:00:00Z",
        "matchday": 38,
        "status": "SCHEDULED",
    }
    row = _build_fixture_row(m, competition_id=2019, week_start=date(2026, 6, 8))

    assert row["id"] == 12345
    assert row["competition_id"] == 2019
    assert row["home_team_id"] == 1
    assert row["away_team_id"] == 2
    assert row["status"] == "NS"
    assert row["round"] == "Matchday 38"
    assert row["week_start"] == "2026-06-08"


def test_build_fixture_row_returns_none_if_teams_undefined():
    m = {
        "id": 1,
        "homeTeam": {},
        "awayTeam": {"id": 2, "name": "Milan"},
        "utcDate": "2026-06-13T18:00:00Z",
        "status": "SCHEDULED",
    }
    assert _build_fixture_row(m, competition_id=2000, week_start=date(2026, 6, 8)) is None


def test_build_fixture_row_uses_group_label_for_international():
    m = {
        "id": 99,
        "homeTeam": {"id": 1, "name": "Mexico"},
        "awayTeam": {"id": 2, "name": "South Africa"},
        "utcDate": "2026-06-11T18:00:00Z",
        "group": "GROUP_A",
        "status": "FINISHED",
    }
    row = _build_fixture_row(m, competition_id=2000, week_start=date(2026, 6, 8))

    assert row["round"] == "GROUP_A"
    assert row["status"] == "FT"


def test_summarize_h2h_no_matches():
    assert _summarize_h2h({}) == "nessun precedente"
    assert _summarize_h2h({"matches": []}) == "nessun precedente"


def test_summarize_h2h_formats_scores():
    h2h = {"matches": [
        {
            "homeTeam": {"name": "Juventus"}, "awayTeam": {"name": "Milan"},
            "score": {"fullTime": {"home": 2, "away": 1}},
        },
        {
            "homeTeam": {"name": "Milan"}, "awayTeam": {"name": "Juventus"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
    ]}
    assert _summarize_h2h(h2h) == "Juventus 2-1 Milan | Milan ?-? Juventus"


def test_get_league_name_known_and_unknown():
    assert _get_league_name(2019) == "Serie A"
    assert _get_league_name(424242) == "424242"


@patch("scheduler.cron_runner.api")
def test_build_standings_cache_uses_home_away_split(mock_api):
    mock_api.get_standings.return_value = {
        "standings": [
            {"type": "TOTAL", "table": [
                {"team": {"id": 1}, "position": 1, "form": "W,W,D",
                 "playedGames": 10, "goalsFor": 20, "goalsAgainst": 5},
            ]},
            {"type": "HOME", "table": [
                {"team": {"id": 1}, "playedGames": 5, "goalsFor": 12, "goalsAgainst": 2},
            ]},
            {"type": "AWAY", "table": [
                {"team": {"id": 1}, "playedGames": 5, "goalsFor": 8, "goalsAgainst": 3},
            ]},
        ]
    }

    cache = _build_standings_cache("SA")
    entry = cache[1]

    assert entry["rank"] == 1
    assert entry["form"] == "WWD"
    assert entry["home_goals_avg"] == 2.4
    assert entry["home_conceded_avg"] == 0.4
    assert entry["away_goals_avg"] == 1.6
    assert entry["away_conceded_avg"] == 0.6


@patch("scheduler.cron_runner.api")
def test_build_standings_cache_falls_back_to_total_without_home_away(mock_api):
    mock_api.get_standings.return_value = {
        "standings": [
            {"type": "TOTAL", "table": [
                {"team": {"id": 5}, "position": 3, "form": "L,L,W",
                 "playedGames": 10, "goalsFor": 15, "goalsAgainst": 10},
            ]},
        ]
    }

    cache = _build_standings_cache("WC")
    entry = cache[5]

    assert entry["home_goals_avg"] == 1.5
    assert entry["home_conceded_avg"] == 1.0
    assert entry["away_goals_avg"] == 1.5
    assert entry["away_conceded_avg"] == 1.0
    assert "_has_home" not in entry
    assert "_total_for" not in entry


@patch("scheduler.cron_runner.api")
def test_build_standings_cache_empty_standings(mock_api):
    mock_api.get_standings.return_value = {"standings": []}
    assert _build_standings_cache("SA") == {}


@patch("scheduler.cron_runner.broadcast_report")
@patch("scheduler.cron_runner.get_match_news_summary", return_value="Juventus news")
@patch("scheduler.cron_runner.generate_report_with_fallback")
@patch("scheduler.cron_runner.db")
@patch("scheduler.cron_runner.api")
def test_process_fixture_generates_and_broadcasts_report(
    mock_api, mock_db, mock_generate, mock_news, mock_broadcast,
):
    mock_api.get_h2h.return_value = {"matches": []}
    mock_generate.return_value = ("Report testo", "openrouter/free")

    f = {
        "id": 1001,
        "competition_id": 2019,
        "home_team_id": 1,
        "home_team_name": "Juventus",
        "away_team_id": 2,
        "away_team_name": "Milan",
        "match_date": "2026-06-13T18:00:00Z",
    }
    standings_cache = {2019: {
        1: {"rank": 1, "form": "WWWWW", "home_goals_avg": 2.0, "home_conceded_avg": 0.5,
            "away_goals_avg": 1.5, "away_conceded_avg": 0.8},
        2: {"rank": 4, "form": "WLDWL", "home_goals_avg": 1.6, "home_conceded_avg": 1.1,
            "away_goals_avg": 1.0, "away_conceded_avg": 1.4},
    }}

    _process_fixture(f, standings_cache)

    upsert_calls = mock_db.table.return_value.upsert.call_args_list
    assert len(upsert_calls) == 2

    stats_payload = upsert_calls[0].args[0]
    assert stats_payload["fixture_id"] == 1001
    assert upsert_calls[0].kwargs["on_conflict"] == "fixture_id"

    report_payload = upsert_calls[1].args[0]
    assert report_payload["fixture_id"] == 1001
    assert report_payload["report_text"] == "Report testo"
    assert report_payload["is_updated"] is False
    assert upsert_calls[1].kwargs["on_conflict"] == "fixture_id"

    mock_broadcast.assert_called_once_with(2019, 1001, "Report testo", is_updated=False)


@patch("scheduler.cron_runner.broadcast_report")
@patch("scheduler.cron_runner.get_match_news_summary", return_value="")
@patch("scheduler.cron_runner.generate_report_with_fallback", return_value=(None, "none"))
@patch("scheduler.cron_runner.db")
@patch("scheduler.cron_runner.api")
def test_process_fixture_skips_broadcast_on_report_failure(
    mock_api, mock_db, mock_generate, mock_news, mock_broadcast,
):
    mock_api.get_h2h.return_value = {"matches": []}

    f = {
        "id": 1002,
        "competition_id": 2019,
        "home_team_id": 1,
        "home_team_name": "Juventus",
        "away_team_id": 2,
        "away_team_name": "Milan",
        "match_date": "2026-06-13T18:00:00Z",
    }

    _process_fixture(f, {})

    # solo l'upsert di fixture_stats, nessun report salvato
    assert mock_db.table.return_value.upsert.call_count == 1
    mock_broadcast.assert_not_called()


@patch("scheduler.cron_runner.notify_admin")
def test_on_job_error_notifies_admin(mock_notify):
    event = MagicMock(job_id="friday_fetch", exception=RuntimeError("boom"))

    _on_job_error(event)

    mock_notify.assert_called_once()
    assert "friday_fetch" in mock_notify.call_args[0][0]
