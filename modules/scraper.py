import logging
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Feed RSS calcio di default. Non consumano budget API-Football.
DEFAULT_FEEDS = [
    "https://www.gazzetta.it/rss/calcio.xml",
    "https://www.football-italia.net/rss.xml",
]

_REQUEST_TIMEOUT = 10
_USER_AGENT = "football-ai-bot/1.0"


def _fetch_xml(url: str) -> ET.Element | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return ET.fromstring(resp.read())
    except Exception as e:
        logger.warning("Errore fetch feed %s: %s", url, e)
        return None


def _text(item: ET.Element, tag: str) -> str:
    el = item.find(tag)
    return (el.text or "").strip() if el is not None else ""


def fetch_news(feed_urls: list[str] | None = None, max_items: int = 5) -> list[dict]:
    """
    Scarica le news più recenti dai feed RSS configurati (formato RSS 2.0).
    Restituisce una lista di dict con title, link, published, summary.
    Usato come contesto opzionale (nessun impatto sul budget API-Football).
    """
    feed_urls = feed_urls or DEFAULT_FEEDS
    items = []
    for url in feed_urls:
        root = _fetch_xml(url)
        if root is None:
            continue
        for item in root.findall("./channel/item")[:max_items]:
            items.append({
                "title": _text(item, "title"),
                "link": _text(item, "link"),
                "published": _text(item, "pubDate"),
                "summary": _text(item, "description"),
            })
    return items[:max_items]


def search_team_news(team_name: str, feed_urls: list[str] | None = None, max_items: int = 3) -> list[dict]:
    """Filtra le news più recenti che menzionano il nome della squadra."""
    all_news = fetch_news(feed_urls, max_items=20)
    needle = team_name.lower()
    matches = [
        n for n in all_news
        if needle in n["title"].lower() or needle in n.get("summary", "").lower()
    ]
    return matches[:max_items]
