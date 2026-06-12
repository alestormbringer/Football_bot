import logging
import time
from datetime import date, timedelta
from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import (
    LEAGUES, LEAGUE_ID_MAP, INTERNATIONAL_LEAGUE_KEYS,
    FRIDAY_FETCH_HOUR, SATURDAY_FETCH_HOUR, SUNDAY_FETCH_HOUR
)
from config.database import get_client
from modules.api_client import FootballDataClient
from modules.predictor_ml import compute_poisson_probs
from modules.report_generator import build_match_prompt, generate_report_with_fallback
from modules.scraper import get_match_news_summary
from bot.notifier import broadcast_report, notify_admin

logger = logging.getLogger(__name__)
api    = FootballDataClient()
db     = get_client()

# Mappa stati football-data.org -> stati usati nel DB
_STATUS_MAP = {
    "SCHEDULED": "NS",
    "TIMED":     "NS",
    "FINISHED":  "FT",
}


# ==============================================================
# Helpers — date
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


# ==============================================================
# Helpers — classifiche (1 call per competizione)
# ==============================================================
def _safe_div(numerator, denominator, default):
    try:
        if not denominator:
            return default
        return round(numerator / denominator, 2)
    except (TypeError, ZeroDivisionError):
        return default


def _build_standings_cache(competition_code: str) -> dict:
    """
    Scarica la classifica (1 call) e restituisce:
        {team_id: {rank, form, home_goals_avg, home_conceded_avg,
                    away_goals_avg, away_conceded_avg}}

    football-data.org restituisce tabelle separate per tipo (TOTAL,
    HOME, AWAY) e per gruppo (gironi dei tornei internazionali). Se non
    sono disponibili tabelle HOME/AWAY (es. fase a gironi del Mondiale)
    si usa la tabella TOTAL come fallback per entrambe.
    """
    data = api.get_standings(competition_code)
    groups = data.get("standings", [])
    if not groups:
        return {}

    cache: dict[int, dict] = {}
    for group in groups:
        gtype = group.get("type", "TOTAL")
        for t in group.get("table", []):
            try:
                team_id = t["team"]["id"]
            except (KeyError, TypeError):
                continue

            entry = cache.setdefault(team_id, {
                "rank": None, "form": "",
                "home_goals_avg": 1.2, "home_conceded_avg": 1.0,
                "away_goals_avg": 1.0, "away_conceded_avg": 1.2,
                "_has_home": False, "_has_away": False,
            })

            played       = t.get("playedGames")
            goals_avg    = _safe_div(t.get("goalsFor"), played, None)
            conceded_avg = _safe_div(t.get("goalsAgainst"), played, None)

            if gtype == "TOTAL":
                entry["rank"] = t.get("position")
                entry["form"] = (t.get("form") or "").replace(",", "")
                if goals_avg is not None:
                    entry["_total_for"] = goals_avg
                    entry["_total_against"] = conceded_avg
            elif gtype == "HOME" and goals_avg is not None:
                entry["home_goals_avg"] = goals_avg
                entry["home_conceded_avg"] = conceded_avg
                entry["_has_home"] = True
            elif gtype == "AWAY" and goals_avg is not None:
                entry["away_goals_avg"] = goals_avg
                entry["away_conceded_avg"] = conceded_avg
                entry["_has_away"] = True

    # Fallback su TOTAL per chi non ha split home/away (es. gironi Mondiale)
    for entry in cache.values():
        if not entry.pop("_has_home") and "_total_for" in entry:
            entry["home_goals_avg"] = entry["_total_for"]
            entry["home_conceded_avg"] = entry["_total_against"]
        if not entry.pop("_has_away") and "_total_for" in entry:
            entry["away_goals_avg"] = entry["_total_for"]
            entry["away_conceded_avg"] = entry["_total_against"]
        entry.pop("_total_for", None)
        entry.pop("_total_against", None)

    return cache


def _build_fixture_row(m: dict, competition_id: int, week_start: date) -> dict | None:
    """
    Normalizza una partita football-data.org nel formato della tabella
    `fixtures`. Restituisce None se le squadre non sono ancora definite
    (es. fasi finali da sorteggiare).
    """
    home = m.get("homeTeam") or {}
    away = m.get("awayTeam") or {}
    if home.get("id") is None or away.get("id") is None:
        return None

    if m.get("group"):
        round_label = m["group"]
    elif m.get("matchday"):
        round_label = f"Matchday {m['matchday']}"
    else:
        round_label = m.get("stage")

    return {
        "id":             m["id"],
        "competition_id": competition_id,
        "home_team_id":   home["id"],
        "home_team_name": home.get("name") or home.get("shortName") or "?",
        "away_team_id":   away["id"],
        "away_team_name": away.get("name") or away.get("shortName") or "?",
        "match_date":     m["utcDate"],
        "round":          round_label,
        "status":         _STATUS_MAP.get(m.get("status"), m.get("status", "NS")),
        "week_start":     week_start.isoformat(),
        "raw_data":       m,
    }


# ==============================================================
# Helpers — elaborazione singola partita
# ==============================================================
def _process_fixture(f: dict, standings_cache: dict) -> None:
    """
    H2H + ML + report LLM per una singola partita.
    Usato sia dal fetch del venerdì sia dal fetch giornaliero
    dei tornei internazionali.
    """
    comp_id    = f["competition_id"]
    fixture_id = f["id"]

    h2h = api.get_h2h(fixture_id, limit=5)

    team_stats = standings_cache.get(comp_id, {})
    home_stats = team_stats.get(f["home_team_id"], {})
    away_stats = team_stats.get(f["away_team_id"], {})

    ml_input = {
        "home_attack":  home_stats.get("home_goals_avg", 1.2),
        "home_defense": home_stats.get("home_conceded_avg", 1.0),
        "away_attack":  away_stats.get("away_goals_avg", 1.0),
        "away_defense": away_stats.get("away_conceded_avg", 1.2),
    }
    probs = compute_poisson_probs(**ml_input)
    h2h_summary = _summarize_h2h(h2h)

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
        "ml_home_prob":           probs["home_win"],
        "ml_draw_prob":           probs["draw"],
        "ml_away_prob":           probs["away_win"],
        "ml_expected_goals_home": probs["expected_home"],
        "ml_expected_goals_away": probs["expected_away"],
    }, on_conflict="fixture_id").execute()

    news_summary = get_match_news_summary(f["home_team_name"], f["away_team_name"])

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
        injuries_home=[],
        injuries_away=[],
        news_summary=news_summary,
    )
    text, model_used = generate_report_with_fallback(prompt)
    if text:
        db.table("reports").upsert({
            "fixture_id":     fixture_id,
            "report_text":    text,
            "llm_model_used": model_used,
            "is_updated":     False,
        }, on_conflict="fixture_id").execute()
        logger.info("Report generato per fixture %d [%s]", fixture_id, model_used)
        broadcast_report(comp_id, fixture_id, text, is_updated=False)
    else:
        logger.error("Report fallito per fixture %d", fixture_id)


# ==============================================================
# JOB 1 — VENERDÌ: fetch completo
# ==============================================================
def friday_full_fetch():
    """
    Scarica tutto il necessario per il weekend:
    1. Fixtures per ogni competizione (1 call ciascuna)
    2. Classifica per ogni competizione con partite (1 call ciascuna)
    3. H2H per ogni partita (1 call ciascuna)
    4. Calcola probabilità ML
    5. Genera report LLM per ogni partita
    """
    logger.info("=== FRIDAY FETCH START ===")
    start = time.monotonic()
    from_date, to_date = get_weekend_range()
    week_start = get_week_start()

    # --- Step 1: Fixtures ---
    fixtures_by_league: dict[int, list[dict]] = {}
    all_fixtures: list[dict] = []
    for key, league in LEAGUES.items():
        matches = api.get_matches(league["code"], from_date, to_date)
        if not matches:
            logger.debug("Lega %s: nessuna partita nel weekend, skip.", key)
            continue

        league_rows = []
        for m in matches:
            fixture_row = _build_fixture_row(m, league["id"], week_start)
            if fixture_row is None:
                continue
            db.table("fixtures").upsert(fixture_row).execute()
            league_rows.append(fixture_row)

        if not league_rows:
            continue

        fixtures_by_league[league["id"]] = league_rows
        all_fixtures.extend(league_rows)
        logger.info("Lega %s: %d partite scaricate", key, len(league_rows))

    # --- Step 2: Standings (solo per leghe con partite questo weekend) ---
    standings_cache: dict[int, dict] = {}
    for key, league in LEAGUES.items():
        league_id = league["id"]
        if league_id not in fixtures_by_league:
            continue
        standings_cache[league_id] = _build_standings_cache(league["code"])

    # --- Step 3, 4, 5: H2H + ML + report per partita ---
    for f in all_fixtures:
        _process_fixture(f, standings_cache)

    logger.info("=== FRIDAY FETCH END — %d partite elaborate (%.1fs) ===",
                len(all_fixtures), time.monotonic() - start)


# ==============================================================
# JOB 3 — TORNEI INTERNAZIONALI: fetch giornaliero (lun-gio)
# ==============================================================
def international_daily_fetch():
    """
    Durante un torneo internazionale (Mondiali, Europei) le partite si
    giocano OGNI giorno della settimana, non solo nel weekend. Questo job
    copre lunedì-giovedì: scarica fixtures + classifica + H2H + ML + report
    per le partite di OGGI di ciascun torneo internazionale attivo. Il
    weekend (venerdì-lunedì) resta coperto da friday_full_fetch + daily_refresh.

    Se nessun torneo internazionale ha partite oggi, il job non fa nulla
    (1 call per torneo per verificare le fixtures).
    """
    logger.info("=== INTERNATIONAL DAILY FETCH START ===")
    start = time.monotonic()
    today_str = date.today().isoformat()
    week_start = get_week_start()

    all_fixtures: list[dict] = []
    standings_cache: dict[int, dict] = {}

    for key in INTERNATIONAL_LEAGUE_KEYS:
        league = LEAGUES[key]
        matches = api.get_matches(league["code"], today_str, today_str)
        if not matches:
            logger.debug("Torneo %s: nessuna partita oggi, skip.", key)
            continue

        league_rows = []
        for m in matches:
            fixture_row = _build_fixture_row(m, league["id"], week_start)
            if fixture_row is None:
                continue
            db.table("fixtures").upsert(fixture_row).execute()
            league_rows.append(fixture_row)

        if not league_rows:
            continue

        all_fixtures.extend(league_rows)
        logger.info("Torneo %s: %d partite oggi", key, len(league_rows))
        standings_cache[league["id"]] = _build_standings_cache(league["code"])

    if not all_fixtures:
        logger.info("Nessuna partita nei tornei internazionali oggi (%.1fs).", time.monotonic() - start)
        return

    for f in all_fixtures:
        _process_fixture(f, standings_cache)

    logger.info("=== INTERNATIONAL DAILY FETCH END — %d partite elaborate (%.1fs) ===",
                len(all_fixtures), time.monotonic() - start)


# ==============================================================
# JOB 2 — SABATO / DOMENICA: refresh delta
# ==============================================================
def daily_refresh(day_name: str = "saturday"):
    """
    Refresh giornaliero: per ogni lega che ha partite in programma oggi,
    riscarica la classifica aggiornata (1 call per lega). Se forma o
    posizione di una delle due squadre sono cambiate rispetto all'ultimo
    fetch (es. per turni infrasettimanali), ricalcola le probabilità ML
    e rigenera il report.
    """
    logger.info("=== %s REFRESH START ===", day_name.upper())
    start = time.monotonic()
    today = date.today().isoformat()

    result = db.table("fixtures") \
        .select("id, home_team_id, away_team_id, home_team_name, away_team_name, competition_id") \
        .eq("status", "NS") \
        .gte("match_date", f"{today}T00:00:00") \
        .lte("match_date", f"{today}T23:59:59") \
        .execute()

    today_fixtures = result.data or []
    if not today_fixtures:
        logger.info("Nessuna partita oggi, refresh saltato (%.1fs).", time.monotonic() - start)
        return

    logger.info("Partite oggi: %d", len(today_fixtures))

    # Classifica aggiornata per ogni lega che gioca oggi (1 call per lega)
    leagues_today = {f["competition_id"] for f in today_fixtures}
    standings_cache: dict[int, dict] = {}
    for league_id in leagues_today:
        league_key = LEAGUE_ID_MAP.get(league_id)
        if not league_key:
            continue
        standings_cache[league_id] = _build_standings_cache(LEAGUES[league_key]["code"])

    for f in today_fixtures:
        fid = f["id"]
        comp_id = f["competition_id"]

        team_stats = standings_cache.get(comp_id, {})
        home_stats = team_stats.get(f["home_team_id"], {})
        away_stats = team_stats.get(f["away_team_id"], {})

        stats_res = db.table("fixture_stats").select("*").eq("fixture_id", fid).execute()
        stats = stats_res.data[0] if stats_res.data else {}

        if home_stats.get("form", "") == (stats.get("home_form") or "") and \
                away_stats.get("form", "") == (stats.get("away_form") or "") and \
                home_stats.get("rank") == stats.get("home_position") and \
                away_stats.get("rank") == stats.get("away_position"):
            continue  # nessuna novità rispetto all'ultimo fetch

        ml_input = {
            "home_attack":  home_stats.get("home_goals_avg",    stats.get("home_goals_avg", 1.2)),
            "home_defense": home_stats.get("home_conceded_avg", stats.get("home_conceded_avg", 1.0)),
            "away_attack":  away_stats.get("away_goals_avg",    stats.get("away_goals_avg", 1.0)),
            "away_defense": away_stats.get("away_conceded_avg", stats.get("away_conceded_avg", 1.2)),
        }
        probs = compute_poisson_probs(**ml_input)

        home_form = home_stats.get("form") or stats.get("home_form") or ""
        away_form = away_stats.get("form") or stats.get("away_form") or ""
        home_position = home_stats.get("rank") or stats.get("home_position")
        away_position = away_stats.get("rank") or stats.get("away_position")

        db.table("fixture_stats").upsert({
            "fixture_id":             fid,
            "home_form":              home_form,
            "away_form":              away_form,
            "home_position":          home_position,
            "away_position":          away_position,
            "home_goals_avg":         ml_input["home_attack"],
            "away_goals_avg":         ml_input["away_attack"],
            "home_conceded_avg":      ml_input["home_defense"],
            "away_conceded_avg":      ml_input["away_defense"],
            "ml_home_prob":           probs["home_win"],
            "ml_draw_prob":           probs["draw"],
            "ml_away_prob":           probs["away_win"],
            "ml_expected_goals_home": probs["expected_home"],
            "ml_expected_goals_away": probs["expected_away"],
        }, on_conflict="fixture_id").execute()

        news_summary = get_match_news_summary(f["home_team_name"], f["away_team_name"])

        prompt = build_match_prompt(
            home_team=f["home_team_name"], away_team=f["away_team_name"],
            competition=_get_league_name(comp_id),
            match_date=today,
            home_form=home_form or "N/A",
            away_form=away_form or "N/A",
            home_position=home_position or 0,
            away_position=away_position or 0,
            ml_probs=probs, h2h_summary="aggiornamento del giorno",
            injuries_home=[], injuries_away=[],
            news_summary=news_summary,
        )
        text, model_used = generate_report_with_fallback(prompt)
        if text:
            db.table("reports").upsert({
                "fixture_id":     fid,
                "report_text":    text,
                "llm_model_used": model_used,
                "is_updated":     True,
            }, on_conflict="fixture_id").execute()
            logger.info("Report aggiornato fixture %d (classifica cambiata)", fid)
            broadcast_report(comp_id, fid, text, is_updated=True)

    logger.info("=== %s REFRESH END (%.1fs) ===", day_name.upper(), time.monotonic() - start)


# ==============================================================
# Helpers
# ==============================================================
def _summarize_h2h(h2h_data: dict) -> str:
    """Produce stringa leggibile dagli ultimi precedenti."""
    matches = (h2h_data or {}).get("matches", [])
    if not matches:
        return "nessun precedente"
    results = []
    for match in matches[:5]:
        home = match.get("homeTeam", {}) or {}
        away = match.get("awayTeam", {}) or {}
        score = (match.get("score", {}) or {}).get("fullTime", {}) or {}
        h_name = home.get("name") or home.get("shortName") or "?"
        a_name = away.get("name") or away.get("shortName") or "?"
        h_gol = score.get("home")
        a_gol = score.get("away")
        h_gol = "?" if h_gol is None else h_gol
        a_gol = "?" if a_gol is None else a_gol
        results.append(f"{h_name} {h_gol}-{a_gol} {a_name}")
    return " | ".join(results)


def _get_league_name(league_id: int) -> str:
    key = LEAGUE_ID_MAP.get(league_id, "")
    return LEAGUES.get(key, {}).get("name", str(league_id))


# ==============================================================
# Setup scheduler
# ==============================================================
def _on_job_error(event):
    """Listener APScheduler: logga e notifica l'admin se un job pianificato
    solleva un'eccezione non gestita (lo scheduler continua comunque)."""
    logger.error("Job %s fallito: %s", event.job_id, event.exception)
    notify_admin(f"❌ Job `{event.job_id}` fallito: {event.exception}")


def setup_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
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
    scheduler.add_job(
        international_daily_fetch,
        CronTrigger(day_of_week="mon-thu", hour=FRIDAY_FETCH_HOUR, minute=0),
        id="international_daily_fetch", replace_existing=True,
    )
    return scheduler
