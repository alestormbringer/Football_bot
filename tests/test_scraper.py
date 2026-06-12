import xml.etree.ElementTree as ET
from unittest.mock import patch

from modules.scraper import fetch_news, search_team_news, get_match_news_summary

SAMPLE_XML = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Juventus batte Inter 2-1</title>
  <link>https://example.com/1</link>
  <pubDate>Mon, 08 Jun 2026 10:00:00 GMT</pubDate>
  <description>La Juventus vince il derby</description>
</item>
<item>
  <title>Milan pareggia con Roma</title>
  <link>https://example.com/2</link>
  <pubDate>Tue, 09 Jun 2026 10:00:00 GMT</pubDate>
  <description>Pareggio a San Siro</description>
</item>
</channel></rss>"""


def _root():
    return ET.fromstring(SAMPLE_XML)


def test_fetch_news_parses_items():
    with patch("modules.scraper._fetch_xml", return_value=_root()):
        items = fetch_news(["https://feed.example/rss"], max_items=5)

    assert len(items) == 2
    assert items[0]["title"] == "Juventus batte Inter 2-1"
    assert items[0]["link"] == "https://example.com/1"


def test_fetch_news_skips_unreachable_feeds():
    with patch("modules.scraper._fetch_xml", return_value=None):
        items = fetch_news(["https://feed.example/rss"])

    assert items == []


def test_fetch_news_respects_max_items():
    with patch("modules.scraper._fetch_xml", return_value=_root()):
        items = fetch_news(["https://feed.example/rss"], max_items=1)

    assert len(items) == 1


def test_search_team_news_filters_by_name():
    with patch("modules.scraper._fetch_xml", return_value=_root()):
        items = search_team_news("Juventus", feed_urls=["https://feed.example/rss"])

    assert len(items) == 1
    assert "Juventus" in items[0]["title"]


def test_search_team_news_no_match():
    with patch("modules.scraper._fetch_xml", return_value=_root()):
        items = search_team_news("Napoli", feed_urls=["https://feed.example/rss"])

    assert items == []


def test_get_match_news_summary_combines_both_teams():
    with patch("modules.scraper._fetch_xml", return_value=_root()):
        summary = get_match_news_summary("Juventus", "Milan")

    assert "Juventus" in summary
    assert "Milan" in summary
    assert " | " in summary


def test_get_match_news_summary_empty_when_no_news():
    with patch("modules.scraper.search_team_news", return_value=[]):
        summary = get_match_news_summary("Team X", "Team Y")

    assert summary == ""


def test_get_match_news_summary_returns_empty_on_error():
    with patch("modules.scraper.search_team_news", side_effect=Exception("rete down")):
        summary = get_match_news_summary("Team X", "Team Y")

    assert summary == ""
