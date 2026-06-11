from modules.predictor_ml import (
    parse_form,
    compute_poisson_probs,
    build_match_stats,
    adjust_for_injuries,
)


def test_parse_form_basic():
    assert parse_form("WWDLW") == 3 / 5
    assert parse_form("LLLLL") == 0.0
    assert parse_form("WWWWW") == 1.0


def test_parse_form_empty_defaults_to_half():
    assert parse_form("") == 0.5
    assert parse_form(None) == 0.5


def test_parse_form_uses_last_n_only():
    assert parse_form("LLLLLWWWWW", last_n=5) == 1.0


def test_compute_poisson_probs_sums_to_one():
    probs = compute_poisson_probs(
        home_attack=1.5, home_defense=1.0,
        away_attack=1.1, away_defense=1.3,
    )
    total = probs["home_win"] + probs["draw"] + probs["away_win"]
    assert abs(total - 1.0) < 1e-6
    assert 0 <= probs["over_25"] <= 1


def test_compute_poisson_probs_home_advantage():
    """A stronger home side should have a higher home_win than away_win."""
    probs = compute_poisson_probs(
        home_attack=2.0, home_defense=0.8,
        away_attack=0.8, away_defense=2.0,
    )
    assert probs["home_win"] > probs["away_win"]


def test_compute_poisson_probs_clips_extreme_inputs():
    probs = compute_poisson_probs(
        home_attack=100, home_defense=100,
        away_attack=0, away_defense=0,
    )
    assert probs["expected_home"] <= 5.0
    assert probs["expected_away"] >= 0.3


def test_build_match_stats_uses_defaults_for_missing_fields():
    stats = build_match_stats({})
    assert stats == {
        "home_attack": 1.2,
        "home_defense": 1.0,
        "away_attack": 1.0,
        "away_defense": 1.2,
    }


def test_build_match_stats_reads_row_values():
    row = {
        "home_goals_avg": 2.1,
        "home_conceded_avg": 0.9,
        "away_goals_avg": 1.4,
        "away_conceded_avg": 1.6,
    }
    assert build_match_stats(row) == {
        "home_attack": 2.1,
        "home_defense": 0.9,
        "away_attack": 1.4,
        "away_defense": 1.6,
    }


def test_adjust_for_injuries_penalizes_team_with_more_injuries():
    base = compute_poisson_probs(
        home_attack=1.4, home_defense=1.1,
        away_attack=1.1, away_defense=1.2,
    )
    adjusted = adjust_for_injuries(base, home_injury_count=5, away_injury_count=0)

    assert adjusted["home_win"] < base["home_win"]
    total = adjusted["home_win"] + adjusted["draw"] + adjusted["away_win"]
    assert abs(total - 1.0) < 1e-6


def test_adjust_for_injuries_keeps_probabilities_in_range():
    base = compute_poisson_probs(
        home_attack=1.4, home_defense=1.1,
        away_attack=1.1, away_defense=1.2,
    )
    adjusted = adjust_for_injuries(base, home_injury_count=10, away_injury_count=10)

    for key in ("home_win", "draw", "away_win"):
        assert 0.0 < adjusted[key] < 1.0
