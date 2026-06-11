import time
import logging
import requests
from datetime import date
from config.settings import API_BASE_URL, API_HEADERS, CALL_SAFETY_BUFFER
from config.database import get_client

logger = logging.getLogger(__name__)


class APIFootballClient:
    """
    Wrapper per API-Football v3.
    - Rispetta il limite di 100 call/giorno
    - Retry automatico su 499/500
    - Logging di ogni call su Supabase
    - /status non conta sulla quota (chiamato gratis per monitoraggio)
    """

    def __init__(self):
        self.base_url = API_BASE_URL
        self.headers  = API_HEADERS
        self.session  = requests.Session()
        self.session.headers.update(self.headers)

    # ------------------------------------------------------------------
    # Quota management
    # ------------------------------------------------------------------

    def get_remaining_calls(self) -> int:
        """Chiama /status (non quota) per sapere le call rimanenti oggi."""
        try:
            resp = self.session.get(f"{self.base_url}/status", timeout=10)
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Errore /status: %s", e)
            return 0

        if data.get("errors"):
            logger.warning("Errore /status: %s", data["errors"])
            return 0
        req = data["response"]["requests"]
        used  = req["current"]
        limit = req["limit_day"]
        return limit - used

    def _budget_ok(self, needed: int = 1) -> bool:
        remaining = self.get_remaining_calls()
        ok = remaining >= (needed + CALL_SAFETY_BUFFER)
        if not ok:
            logger.error(
                "Budget esaurito: rimangono %d call, servono %d + %d buffer",
                remaining, needed, CALL_SAFETY_BUFFER
            )
        return ok

    def _log_call(self, endpoint: str):
        """Registra la call su Supabase per tracciamento."""
        try:
            get_client().table("api_usage_log").insert({
                "log_date": date.today().isoformat(),
                "endpoint": endpoint,
            }).execute()
        except Exception as e:
            logger.warning("Log call fallito: %s", e)

    # ------------------------------------------------------------------
    # Metodo base
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: dict, retries: int = 2) -> list | None:
        """
        GET generico con retry su 499/500.
        Restituisce response[] o None in caso di errore.
        """
        if not self._budget_ok():
            return None

        url = f"{self.base_url}/{endpoint}"
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                self._log_call(endpoint)

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("errors"):
                        logger.warning("[%s] Errori API: %s", endpoint, data["errors"])
                        return None
                    return data.get("response", [])

                elif resp.status_code in (499, 500):
                    logger.warning("[%s] Status %d, retry %d/%d",
                                   endpoint, resp.status_code, attempt + 1, retries)
                    time.sleep(2 ** attempt)  # backoff esponenziale

                elif resp.status_code == 429:
                    logger.error("[%s] Rate limit (429) — aspetto 60s", endpoint)
                    time.sleep(60)

                else:
                    logger.error("[%s] HTTP %d", endpoint, resp.status_code)
                    return None

            except requests.RequestException as e:
                logger.error("[%s] Eccezione request: %s", endpoint, e)
                if attempt == retries:
                    return None
                time.sleep(2)

        return None

    # ------------------------------------------------------------------
    # Endpoint specifici
    # ------------------------------------------------------------------

    def get_fixtures_by_league(self, league_id: int, season: int,
                                from_date: str, to_date: str) -> list:
        """
        Scarica tutte le partite di una lega in un intervallo di date.
        1 call -> tutti i match del weekend.
        Esempio: from_date="2025-08-22", to_date="2025-08-25"
        """
        return self._get("fixtures", {
            "league": league_id,
            "season": season,
            "from": from_date,
            "to": to_date,
            "timezone": "Europe/Rome",
        }) or []

    def get_fixtures_batch(self, fixture_ids: list[int]) -> list:
        """
        Batch fetch: max 20 fixture IDs in una sola call.
        Restituisce eventi + lineups + statistics + players.
        Usato per refresh sab/dom.
        """
        if not fixture_ids:
            return []
        # L'API accetta max 20 ids separati da "-"
        chunks = [fixture_ids[i:i + 20] for i in range(0, len(fixture_ids), 20)]
        results = []
        for chunk in chunks:
            ids_str = "-".join(str(fid) for fid in chunk)
            data = self._get("fixtures", {"ids": ids_str}) or []
            results.extend(data)
        return results

    def get_standings(self, league_id: int, season: int) -> list:
        """Classifica completa di una lega. 1 call."""
        return self._get("standings", {
            "league": league_id,
            "season": season,
        }) or []

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 5) -> list:
        """
        Ultimi N scontri diretti tra due squadre.
        1 call per coppia. Usato nel fetch venerdi.
        """
        return self._get("fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}",
            "last": last,
        }) or []

    def get_injuries(self, league_id: int, season: int, fixture_ids: list[int] = None) -> list:
        """
        Infortuni per lega (fetch completo venerdi) oppure
        per fixture specifici batch (refresh sab/dom).
        1 call per lega in modalita venerdi.
        In modalita refresh: usa il parametro ids (max 20).
        """
        if fixture_ids:
            ids_str = "-".join(str(fid) for fid in fixture_ids[:20])
            return self._get("injuries", {"ids": ids_str}) or []
        else:
            return self._get("injuries", {
                "league": league_id,
                "season": season,
            }) or []

    def get_lineups(self, fixture_id: int) -> list:
        """
        Formazioni ufficiali (disponibili ~60 min prima del match).
        Usato solo nel refresh sab/dom per partite imminenti.
        """
        return self._get("fixtures/lineups", {"fixture": fixture_id}) or []

    def get_teams_statistics(self, league_id: int, team_id: int, season: int) -> dict:
        """
        Statistiche stagionali di una squadra in una lega.
        Opzionale: usato per arricchire il prompt LLM se il budget lo permette.
        """
        result = self._get("teams/statistics", {
            "league": league_id,
            "team": team_id,
            "season": season,
        })
        return result[0] if result else {}
