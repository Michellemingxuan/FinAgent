import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import feedparser

logger = logging.getLogger(__name__)

YAHOO_RSS_TEMPLATE = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={symbol}&region=US&lang=en-US"
)
YAHOO_GENERAL_RSS = [
    "https://finance.yahoo.com/news/rssindex",
]


class RSSClient:
    def __init__(self, lookback_days: int = 3):
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    def fetch_yahoo_for_ticker(self, symbol: str) -> list[dict]:
        url = YAHOO_RSS_TEMPLATE.format(symbol=symbol)
        return self._parse_feed(url, source="Yahoo Finance")

    def fetch_yahoo_general(self) -> list[dict]:
        items: list[dict] = []
        for url in YAHOO_GENERAL_RSS:
            items.extend(self._parse_feed(url, source="Yahoo Finance"))
        return items

    def _parse_feed(self, url: str, source: str) -> list[dict]:
        try:
            feed = feedparser.parse(url)
            items = []
            for entry in feed.entries:
                published = _parse_date(entry)
                if published and published < self._cutoff:
                    continue
                items.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", ""),
                    "published": published.strftime("%Y-%m-%d %H:%M UTC") if published else "",
                    "source": source,
                    "full_text_available": False,
                })
            return items
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", url, exc)
            return []


def _parse_date(entry) -> Optional[datetime]:
    try:
        import time
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None
