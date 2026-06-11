import logging
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import (
    LEAGUES, LEAGUE_ID_MAP, CURRENT_SEASON, INTERNATIONAL_LEAGUE_KEYS,
    FRIDAY_FETCH_HOUR, SATURDAY_FETCH_HOUR, SUNDAY_FETCH_HOUR
)
from config.database import get_client
from modules.api_client import APIFootballClient
from modules.predictor_ml import compute_poisson_probs, adjust_for_injuries, build_match_stats
from modules.report_generator import build_match_prompt, generate_report_with_fallback

logger = logging.getLogger(__name__)
api    = APIFootballClient()
db     = get_client()


# ==============================================================
# Helpers — date e stagioni
# ==============================================================
def get_weekend_range() -> tuple[str, str]:
    """Restituisce (venerdì, lunedì) della settimana corrente, come stringhe ISO."""
    today  = date.today()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    monday = friday + timedelta(days=3)
    return friday.isoformat(), monday.isoformat()


def get_week_start() -> date:
    """Lunedì della settimana corrente."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def get_season_for_competition(league_key: str) -> int:
    """
    Stagione corretta per ogni competizione.

    - Campionati e coppe club -> CURRENT_SEASON (anno di inizio, es. 2025 = 25/26)
    - Tornei internazionali   -> anno solare corrente (es. 2026 per i Mondiali 2026)

    I campionati nazionali sono SEMPRE sospesi durante i tornei internazionali,
    quindi il budget 100 call/giorno non si somma mai: quando i tornei
    internazionali hanno partite, i campionati restituiscono lista vuota.
    """
    if league_key in INTERNATIONAL_LEAGUE_KEYS:
        return date.today().year
    return CURRENT_SEASON


# ==============================================================
# Helpers — classifiche e infortuni (per lega, 1 call ciascuno)
# ==============================================================
def _safe_div(numerator, denominator, default: float) -> float:
    try:
        if not denominator:
            return default
        return round(numerator / denominator, 2)
    except (TypeError, ZeroDivisionError):
        return default


def _build_standings_cache(league_id: int, season: int) -> dict:
    """
    Scarica la classifica (1 call) e restituisce:
        {team_id: {rank, form, home_goals_avg, home_conceded_avg,
                    away_goals_avg, away_conceded_avg}}

    Gestisce sia campionati a girone unico sia tornei a gironi multipli
    (Mondiali, Europei) appiattendo tutte le liste di standings.
    """
    standings = api.get_standings(league_id, season)
    if not standings:
        return {}

    cache: dict[int, dict] = {}
    try:
        groups = standings[0]["league"]["standings"]
        for group in groups:
            for t in group:
                team_id = t["team"]["id"]
                home = t.get("home", {})
                away = t.get("away", {})
                cache[team_id] = {
                    "rank": t.get("rank"),
                    "form": t.get("form") or "",
                    "home_goals_avg":    _safe_div(home.get("goals", {}).get("for"), home.get("played"), 1.2),
                    "home_conceded_avg": _safe_div(home.get("goals", {}).get("against"), home.get("played"), 1.0),
                    "away_goals_avg":    _safe_div(away.get("goals", {}).get("for"), away.get("played"), 1.0),
                    "away_conceded_avg": _safe_div(away.get("goals", {}).get("against"), away.get("played"), 1.2),
                }
    except (KeyError, IndexError, TypeError):
        logger.warning("Formato standings inatteso per lega %d", league_id)
    return cache


def _build_injuries_cache(league_id: int, season: int) -> dict:
    """
    Scarica gli infortuni "Missing Fixture" per l'intera lega (1 call)
    e li raggruppa per team_id. Usato per evitare 1 call per partita.
    """
    injuries_raw = api.get_injuries(league_id=league_id, season=season)
    cache: dict[int, list] = {}
    for inj in injuries_raw:
        try:
            if inj["player"].get("type") != "Missing Fixture":
                continue
            team_id = inj["team"]["id"]
            cache.setdefault(team_id, []).append({
                "name": inj["player"]["name"],
                "reason": inj["player"].get("reason", "?"),
            })
        except KeyError:
            continue
    return cache


# ==============================================================
# JOB 1 — VENERDÌ: fetch completo
# ==============================================================
def friday_full_fetch():
    """
    Scarica tutto il necessario per il weekend:
    1. Fixtures per ogni competizione (1 call ciascuna)
    2. Standings + injuries per ogni lega con partite (1+1 call ciascuna)
    3. H2H per ogni partita (1 call ciascuna)
    4. Calcola probabilità ML
    5. Genera report LLM per ogni partita
    """
    logger.info("=== FRIDAY FETCH START ===")
    from_date, to_date = get_weekend_range()
    week_start = get_week_start()

    remaining = api.get_remaining_calls()
    logger.info("Call rimanenti prima del fetch: %d", remaining)

    # --- Step 1: Fixtures ---
    fixtures_by_league: dict[int, list[dict]] = {}
    all_fixtures: list[dict] = []
    for key, league in LEAGUES.items():
        season = get_season_for_competition(key)
        fixtures = api.get_fixtures_by_league(
            league_id=league["id"],
            season=season,
            from_date=from_date,
            to_date=to_date,
        )
        if not fixtures:
            # Lista vuota = nessuna partita questa settimana per questa competizione.
            # Normale durante pause internazionali (campionati) o fuori stagione (coppe).
            logger.debug("Lega %s: nessuna partita nel weekend, skip.", key)
            continue

        league_rows = []
        for f in fixtures:
            fixture_row = {
                "id":             f["fixture"]["id"],
                "competition_id": league["id"],
                "home_team_id":   f["teams"]["home"]["id"],
                "home_team_name": f["teams"]["home"]["name"],
                "away_team_id":   f["teams"]["away"]["id"],
                "away_team_name": f["teams"]["away"]["name"],
                "match_date":     f["fixture"]["date"],
                "round":          f["league"].get("round"),
                "status":         f["fixture"]["status"]["short"],
                "week_start":     week_start.isoformat(),
                "raw_data":       f,
            }
            db.table("fixtures").upsert(fixture_row).execute()
            league_rows.append(fixture_row)

        fixtures_by_league[league["id"]] = league_rows
        all_fixtures.extend(league_rows)
        logger.info("Lega %s (season %s): %d partite scaricate", key, season, len(fixtures))

    # --- Step 2: Standings + Injuries (solo per leghe con partite questo weekend) ---
    standings_cache: dict[int, dict] = {}
    injuries_cache: dict[int, dict] = {}
    for key, league in LEAGUES.items():
        league_id = league["id"]
        if league_id not in fixtures_by_league:
            continue
        season = get_season_for_competition(key)
        standings_cache[league_id] = _build_standings_cache(league_id, season)
        injuries_cache[league_id] = _build_injuries_cache(league_id, season)

    # --- Step 3, 4, 5: H2H + ML + report per partita ---
    for f in all_fixtures:
        home_id    = f["home_team_id"]
        away_id    = f["away_team_id"]
        comp_id    = f["competition_id"]
        fixture_id = f["id"]

        # H2H
        h2h = api.get_h2h(home_id, away_id, last=5)

        team_stats = standings_cache.get(comp_id, {})
        home_stats = team_stats.get(home_id, {})
        away_stats = team_stats.get(away_id, {})

        injuries_home = injuries_cache.get(comp_id, {}).get(home_id, [])
        injuries_away = injuries_cache.get(comp_id, {}).get(away_id, [])

        # --- ML ---
        ml_input = {
            "home_attack":  home_stats.get("home_goals_avg", 1.2),
            "home_defense": home_stats.get("home_conceded_avg", 1.0),
            "away_attack":  away_stats.get("away_goals_avg", 1.0),
            "away_defense": away_stats.get("away_conceded_avg", 1.2),
        }
        probs = compute_poisson_probs(**ml_input)
        probs = adjust_for_injuries(probs, len(injuries_home), len(injuries_away))

        h2h_summary = _summarize_h2h(h2h)

        # Salva fixture_stats
        db.table("fixture_stats").upsert({
            "fixture_id":             fixture_id,
            "home_form":              home_stats.get("form", ""),
            "away_form":              away_stats.get("form", ""),
            "home_position":          home_stats.get("rank"),
            "away_position":          away_stats.get("rank"),
            "home_goals_avg":         ml_input["home_attack"],
            "away_goals_avg":         ml_input["away_attack"],
            "home_conceded_avg":      ml_input["home_defense"],
            "away_conceded_avg":      ml_input["away_defense"],
            "h2h_data":               h2h,
            "injuries_home":          injuries_home,
            "injuries_away":          injuries_away,
            "ml_home_prob":           probs["home_win"],
            "ml_draw_prob":           probs["draw"],
            "ml_away_prob":           probs["away_win"],
            "ml_expected_goals_home": probs["expected_home"],
            "ml_expected_goals_away": probs["expected_away"],
        }).execute()

        # --- LLM report ---
        prompt = build_match_prompt(
            home_team=f["home_team_name"],
            away_team=f["away_team_name"],
            competition=_get_league_name(comp_id),
            match_date=f["match_date"][:10],
            home_form=home_stats.get("form") or "N/A",
            away_form=away_stats.get("form") or "N/A",
            home_position=home_stats.get("rank") or 0,
            away_position=away_stats.get("rank") or 0,
            ml_probs=probs,
            h2h_summary=h2h_summary,
            injuries_home=injuries_home,
            injuries_away=injuries_away,
        )
        text, model_used = generate_report_with_fallback(prompt)
        if text:
            db.table("reports").upsert({
                "fixture_id":     fixture_id,
                "report_text":    text,
                "llm_model_used": model_used,
                "is_updated":     False,
            }).execute()
            logger.info("Report generato per fixture %d [%s]", fixture_id, model_used)
        else:
            logger.error("Report fallito per fixture %d", fixture_id)

    logger.info("=== FRIDAY FETCH END — %d partite elaborate ===", len(all_fixtures))


# ==============================================================
# JOB 2 — SABATO / DOMENICA: refresh delta
# ==============================================================
def daily_refresh(day_name: str = "saturday"):
    """
    Refresh giornaliero: per ogni lega che ha partite in programma oggi,
    riscarica gli infortuni aggiornati (1 call per lega, come il venerdì —
    "a giornata" e non solo una volta nel weekend). Se la situazione
    infortuni è cambiata rispetto all'ultimo fetch, ricalcola le
    probabilità ML (dalle statistiche già salvate venerdì) e rigenera
    il report.
    """
    logger.info("=== %s REFRESH START ===", day_name.upper())
    today = date.today().isoformat()

    # Partite di oggi dal DB
    result = db.table("fixtures") \
        .select("id, home_team_id, away_team_id, home_team_name, away_team_name, competition_id") \
        .eq("status", "NS") \
        .gte("match_date", f"{today}T00:00:00") \
        .lte("match_date", f"{today}T23:59:59") \
        .execute()

    today_fixtures = result.data or []
    if not today_fixtures:
        logger.info("Nessuna partita oggi, refresh saltato.")
        return

    logger.info("Partite oggi: %d", len(today_fixtures))

    # Infortuni aggiornati per ogni lega che gioca oggi (1 call per lega)
    leagues_today = {f["competition_id"] for f in today_fixtures}
    injuries_cache: dict[int, dict] = {}
    for league_id in leagues_today:
        league_key = LEAGUE_ID_MAP.get(league_id)
        season = get_season_for_competition(league_key) if league_key else CURRENT_SEASON
        injuries_cache[league_id] = _build_injuries_cache(league_id, season)

    # Rigenera report solo se la situazione infortuni è cambiata
    for f in today_fixtures:
        fid = f["id"]
        comp_id = f["competition_id"]

        injuries_home = injuries_cache.get(comp_id, {}).get(f["home_team_id"], [])
        injuries_away = injuries_cache.get(comp_id, {}).get(f["away_team_id"], [])

        # Recupera stats salvate (venerdì o refresh precedente)
        stats_res = db.table("fixture_stats").select("*").eq("fixture_id", fid).execute()
        stats = stats_res.data[0] if stats_res.data else {}

        if injuries_home == (stats.get("injuries_home") or []) and \
                injuries_away == (stats.get("injuries_away") or []):
            continue  # nessuna novità rispetto all'ultimo fetch

        ml_input = build_match_stats(stats)
        probs = compute_poisson_probs(**ml_input)
        probs = adjust_for_injuries(probs, len(injuries_home), len(injuries_away))

        db.table("fixture_stats").upsert({
            "fixture_id":    fid,
            "injuries_home": injuries_home,
            "injuries_away": injuries_away,
        }).execute()

        prompt = build_match_prompt(
            home_team=f["home_team_name"], away_team=f["away_team_name"],
            competition=_get_league_name(comp_id),
            match_date=today,
            home_form=stats.get("home_form") or "N/A",
            away_form=stats.get("away_form") or "N/A",
            home_position=stats.get("home_position") or 0,
            away_position=stats.get("away_position") or 0,
            ml_probs=probs, h2h_summary="aggiornamento del giorno",
            injuries_home=injuries_home, injuries_away=injuries_away,
        )
        text, model_used = generate_report_with_fallback(prompt)
        if text:
            db.table("reports").upsert({
                "fixture_id":     fid,
                "report_text":    text,
                "llm_model_used": model_used,
                "is_updated":     True,
            }).execute()
            logger.info("Report aggiornato fixture %d (infortuni cambiati)", fid)

    logger.info("=== %s REFRESH END ===", day_name.upper())


# ==============================================================
# Helpers
# ==============================================================
def _summarize_h2h(h2h_data: list) -> str:
    """Produce stringa leggibile dagli ultimi 5 H2H."""
    if not h2h_data:
        return "nessun precedente"
    results = []
    for match in h2h_data[:5]:
        teams = match.get("teams", {})
        goals = match.get("goals", {})
        h_name = teams.get("home", {}).get("name", "?")
        a_name = teams.get("away", {}).get("name", "?")
        h_gol = goals.get("home", "?")
        a_gol = goals.get("away", "?")
        results.append(f"{h_name} {h_gol}-{a_gol} {a_name}")
    return " | ".join(results)


def _get_league_name(league_id: int) -> str:
    key = LEAGUE_ID_MAP.get(league_id, "")
    return LEAGUES.get(key, {}).get("name", str(league_id))


# ==============================================================
# Setup scheduler
# ==============================================================
def setup_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        friday_full_fetch,
        CronTrigger(day_of_week="fri", hour=FRIDAY_FETCH_HOUR, minute=0),
        id="friday_fetch", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_refresh("saturday"),
        CronTrigger(day_of_week="sat", hour=SATURDAY_FETCH_HOUR, minute=0),
        id="saturday_refresh", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_refresh("sunday"),
        CronTrigger(day_of_week="sun", hour=SUNDAY_FETCH_HOUR, minute=0),
        id="sunday_refresh", replace_existing=True,
    )
    return scheduler
