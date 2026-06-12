import time
import logging
from datetime import date
import requests
from config.settings import (
    OPENROUTER_BASE_URL, OPENROUTER_KEY, LLM_PRIMARY, LLM_FALLBACK, LLM_MAX_TOKENS,
    OPENROUTER_DAILY_WARN_LIMIT,
)
from config.database import get_client
from bot.notifier import notify_admin

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sei un analista sportivo esperto in pronostici calcistici.
Scrivi report concisi, diretti e informativi in italiano.
Usa il formato Markdown compatibile con Telegram (grassetto con *, corsivo con _, codice con `).
Non inventare mai dati. Se un dato è assente, omettilo.
Non usare emoji eccessive. Massimo 3-4 per report."""


def build_match_prompt(
    home_team: str,
    away_team: str,
    competition: str,
    match_date: str,
    home_form: str,
    away_form: str,
    home_position: int,
    away_position: int,
    ml_probs: dict,
    h2h_summary: str,
    injuries_home: list,
    injuries_away: list,
    news_summary: str = "",
) -> str:
    """
    Costruisce il prompt per la generazione del report.
    Tutti i parametri numerici vengono dal modello ML — l'LLM
    deve SOLO trasformarli in testo, non ricalcolarli.
    """

    injuries_home_text = ", ".join(
        f"{p['name']} ({p['reason']})" for p in injuries_home[:3]
    ) if injuries_home else "nessun infortunio noto"

    injuries_away_text = ", ".join(
        f"{p['name']} ({p['reason']})" for p in injuries_away[:3]
    ) if injuries_away else "nessun infortunio noto"

    news_text = news_summary or "nessuna novità rilevante"

    prompt = f"""Genera un report di pronostico per questa partita:

**Partita:** {home_team} vs {away_team}
**Competizione:** {competition}
**Data:** {match_date}

**Dati statistici (già calcolati, usa questi):**
- Forma recente {home_team}: {home_form} (posizione: {home_position}°)
- Forma recente {away_team}: {away_form} (posizione: {away_position}°)
- Probabilità ML: {home_team} {ml_probs['home_win']*100:.1f}% | Pareggio {ml_probs['draw']*100:.1f}% | {away_team} {ml_probs['away_win']*100:.1f}%
- Gol attesi: {home_team} {ml_probs['expected_home']} | {away_team} {ml_probs['expected_away']}
- Probabilità Over 2.5: {ml_probs['over_25']*100:.1f}%
- H2H (ultimi 5): {h2h_summary}
- Infortuni {home_team}: {injuries_home_text}
- Infortuni {away_team}: {injuries_away_text}
- Notizie recenti: {news_text}

**Struttura richiesta (rispetta questa struttura esatta):**

*{home_team} vs {away_team}*
📊 _Analisi_
[2-3 righe di analisi qualitativa basata sui dati]

🎯 _Pronostico_
[1 riga: consiglio specifico es. "1X + Under 3.5"]

📈 _Probabilità_
`{home_team}: XX% | X: XX% | {away_team}: XX%`

⚠️ _Da tenere d'occhio_
[infortuni rilevanti o fattori di rischio, max 1 riga]

Lunghezza massima: 200 parole. Scrivi in italiano."""

    return prompt


def _retry_after_seconds(resp: requests.Response, default: float = 5.0) -> float:
    """Estrae il tempo di attesa da un 429: header Retry-After, oppure
    error.metadata.retry_after_seconds nel body (formato OpenRouter)."""
    header_value = resp.headers.get("Retry-After")
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            pass
    try:
        metadata = resp.json().get("error", {}).get("metadata", {})
        if "retry_after_seconds" in metadata:
            return float(metadata["retry_after_seconds"])
    except Exception:
        pass
    return default


def _log_llm_call(model: str, success: bool) -> None:
    """Logga su Supabase ogni chiamata LLM (monitoring consumo OpenRouter)."""
    try:
        get_client().table("llm_usage_log").insert({
            "log_date": date.today().isoformat(),
            "model": model,
            "success": success,
        }).execute()
    except Exception as e:
        logger.warning("Log chiamata LLM fallito: %s", e)


def _warn_if_quota_near_limit() -> None:
    """Avvisa l'admin (una volta al giorno) se ci si avvicina al limite
    di 50 richieste/giorno del piano Free OpenRouter."""
    try:
        today = date.today().isoformat()
        res = get_client().table("llm_usage_log") \
            .select("id", count="exact") \
            .eq("log_date", today) \
            .execute()
        count = res.count or 0
    except Exception as e:
        logger.warning("Controllo quota OpenRouter fallito: %s", e)
        return

    if count == OPENROUTER_DAILY_WARN_LIMIT:
        notify_admin(
            f"⚠️ OpenRouter: raggiunte {count} chiamate oggi "
            f"(soglia di avviso {OPENROUTER_DAILY_WARN_LIMIT}/giorno sul piano Free). "
            "Valutare l'aggiunta di credito se i report iniziano a fallire."
        )


def generate_report(prompt: str, model: str = LLM_PRIMARY, retries: int = 2) -> str | None:
    """
    Chiama OpenRouter con il modello specificato.
    Su 429 (rate limit upstream sui modelli :free) attende il tempo
    indicato da Retry-After e ritenta fino a `retries` volte.
    Restituisce il testo generato o None in caso di errore.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/football-ai-bot",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.7,
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if resp.status_code == 429:
                wait = _retry_after_seconds(resp)
                if attempt < retries:
                    logger.warning(
                        "[%s] Rate limit upstream (429), attendo %.1fs (tentativo %d/%d)",
                        model, wait, attempt + 1, retries,
                    )
                    time.sleep(wait)
                    continue
                logger.error("[%s] Rate limit upstream (429), tentativi esauriti", model)
                return None

            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error("Errore OpenRouter [%s]: %s", model, e)
            if attempt == retries:
                return None
            time.sleep(2)
    return None


def generate_report_with_fallback(prompt: str) -> tuple[str | None, str]:
    """
    Tenta LLM_PRIMARY, poi LLM_FALLBACK.
    Restituisce (testo, modello_usato).
    """
    text = generate_report(prompt, LLM_PRIMARY)
    if text:
        _log_llm_call(LLM_PRIMARY, success=True)
        _warn_if_quota_near_limit()
        return text, LLM_PRIMARY

    _log_llm_call(LLM_PRIMARY, success=False)
    logger.warning("Primary LLM fallito, provo fallback %s", LLM_FALLBACK)
    text = generate_report(prompt, LLM_FALLBACK)
    if text:
        _log_llm_call(LLM_FALLBACK, success=True)
        _warn_if_quota_near_limit()
        return text, LLM_FALLBACK

    _log_llm_call(LLM_FALLBACK, success=False)
    return None, "none"
