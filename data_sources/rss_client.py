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

# Google News RSS — per-ticker search
GOOGLE_NEWS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
)

# Always-included general market RSS feeds
MARKET_RSS_FEEDS = [
    ("https://search.cnbc.com/rs/search/combinedcms/view.xml"
     "?partnerId=wrss01&id=10001147", "CNBC"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch"),
    ("https://feeds.reuters.com/reuters/businessNews", "Reuters"),
]


class RSSClient:
    def __init__(self, lookback_days: int = 3):
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    def fetch_yahoo_for_ticker(self, symbol: str) -> list[dict]:
        """Fetch Yahoo Finance + Google News for a specific ticker (always both)."""
        items: list[dict] = []
        yahoo_url = YAHOO_RSS_TEMPLATE.format(symbol=symbol)
        items.extend(self._parse_feed(yahoo_url, source="Yahoo Finance"))

        google_url = GOOGLE_NEWS_TEMPLATE.format(symbol=symbol)
        items.extend(self._parse_feed(google_url, source="Google News"))

        logger.info("Fetched %d news items for ticker %s (Yahoo + Google News)", len(items), symbol)
        return items

    def fetch_yahoo_general(self) -> list[dict]:
        """Fetch general market news from Yahoo, CNBC, MarketWatch, and Reuters (always all)."""
        items: list[dict] = []

        for url in YAHOO_GENERAL_RSS:
            fetched = self._parse_feed(url, source="Yahoo Finance")
            items.extend(fetched)

        for url, source in MARKET_RSS_FEEDS:
            fetched = self._parse_feed(url, source=source)
            if fetched:
                logger.info("Fetched %d items from %s", len(fetched), source)
            items.extend(fetched)

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
