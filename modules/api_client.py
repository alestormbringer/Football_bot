import time
import logging
import requests
from collections import deque
from datetime import date
from config.settings import FOOTBALL_DATA_BASE_URL, FOOTBALL_DATA_HEADERS, RATE_LIMIT_PER_MINUTE
from config.database import get_client

logger = logging.getLogger(__name__)


class FootballDataClient:
    """
    Wrapper per football-data.org v4 (piano Free).
    - Rate limit: 10 richieste/minuto (rispettato con una sliding window locale)
    - Retry automatico su 429/5xx
    - Logging di ogni call su Supabase (monitoring)
    """

    def __init__(self):
        self.base_url = FOOTBALL_DATA_BASE_URL
        self.session  = requests.Session()
        self.session.headers.update(FOOTBALL_DATA_HEADERS)
        self._call_times: deque = deque()

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def _wait_for_slot(self):
        """Blocca finché non c'è uno slot libero nella finestra di 60s."""
        now = time.monotonic()
        while self._call_times and now - self._call_times[0] >= 60:
            self._call_times.popleft()
        if len(self._call_times) >= RATE_LIMIT_PER_MINUTE:
            sleep_for = 60 - (now - self._call_times[0]) + 0.1
            logger.debug("Rate limit locale raggiunto, attendo %.1fs", sleep_for)
            time.sleep(max(sleep_for, 0))
            now = time.monotonic()
            while self._call_times and now - self._call_times[0] >= 60:
                self._call_times.popleft()
        self._call_times.append(time.monotonic())

    def _log_call(self, endpoint: str):
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
    def _get(self, path: str, params: dict | None = None, retries: int = 2) -> dict | None:
        """
        GET generico con rate limiting e retry su 429/5xx.
        Restituisce il body JSON o None in caso di errore.
        """
        url = f"{self.base_url}/{path}"
        for attempt in range(retries + 1):
            self._wait_for_slot()
            try:
                resp = self.session.get(url, params=params, timeout=15)
                self._log_call(path)

                if resp.status_code == 200:
                    return resp.json()

                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning("[%s] Rate limit (429), attendo %ds", path, retry_after)
                    time.sleep(retry_after)

                elif resp.status_code >= 500:
                    logger.warning("[%s] Status %d, retry %d/%d",
                                   path, resp.status_code, attempt + 1, retries)
                    time.sleep(2 ** attempt)

                elif resp.status_code == 404:
                    logger.debug("[%s] 404 Not Found", path)
                    return None

                else:
                    logger.error("[%s] HTTP %d: %s", path, resp.status_code, resp.text[:200])
                    return None

            except requests.RequestException as e:
                logger.error("[%s] Eccezione request: %s", path, e)
                if attempt == retries:
                    return None
                time.sleep(2)

        return None

    # ------------------------------------------------------------------
    # Endpoint specifici
    # ------------------------------------------------------------------
    def get_matches(self, competition_code: str, date_from: str, date_to: str) -> list:
        """
        Partite di una competizione in un intervallo di date (formato YYYY-MM-DD).
        1 call -> tutte le partite del periodo.
        """
        data = self._get(f"competitions/{competition_code}/matches", {
            "dateFrom": date_from,
            "dateTo": date_to,
        })
        return (data or {}).get("matches", [])

    def get_standings(self, competition_code: str) -> dict:
        """Classifica (stagione corrente) di una competizione. 1 call."""
        return self._get(f"competitions/{competition_code}/standings") or {}

    def get_h2h(self, match_id: int, limit: int = 5) -> dict:
        """Ultimi N scontri diretti per una partita. 1 call."""
        return self._get(f"matches/{match_id}/head2head", {"limit": limit}) or {}
