"""
WSJ data source.

Headlines are fetched from WSJ's public RSS feeds (no auth required).
Article body fetching uses your WSJ subscription cookie, stored in the
WSJ_COOKIE environment variable / GitHub Secret. If the cookie is absent
or stale, the system gracefully falls back to RSS summary text only.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Public WSJ RSS feeds (no authentication required for headlines)
WSJ_RSS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
    "https://feeds.a.dj.com/rss/RSSWSJD.xml",  # Tech
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class WSJClient:
    def __init__(self, cookie: Optional[str] = None, lookback_days: int = 3):
        self._cookie = cookie
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        if cookie:
            self._session.headers["Cookie"] = cookie

    def fetch_headlines(self) -> list[dict]:
        items: list[dict] = []
        for url in WSJ_RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    published = _parse_rss_date(entry)
                    if published and published < self._cutoff:
                        continue
                    items.append({
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                        "published": (
                            published.strftime("%Y-%m-%d %H:%M UTC")
                            if published else ""
                        ),
                        "source": "WSJ",
                        "full_text_available": False,
                    })
            except Exception as exc:
                logger.warning("WSJ RSS fetch failed for %s: %s", url, exc)
        return items

    def enrich_with_full_text(self, items: list[dict]) -> list[dict]:
        """
        Attempt to fetch full article body for each item using the subscription
        cookie. Modifies items in-place; falls back silently if fetch fails.
        Returns the same list.
        """
        if not self._cookie:
            logger.info("WSJ_COOKIE not set — using headlines/summaries only")
            return items

        for item in items:
            body = self._fetch_article_body(item["url"])
            if body:
                item["summary"] = body[:2000]  # cap to avoid token bloat
                item["full_text_available"] = True
        return items

    def _fetch_article_body(self, url: str) -> Optional[str]:
        try:
            resp = self._session.get(url, timeout=15, allow_redirects=True)
            if resp.status_code != 200:
                logger.debug(
                    "WSJ article fetch got %s for %s — cookie may be stale",
                    resp.status_code, url
                )
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            # WSJ uses data-type="paragraph" on article body elements
            paragraphs = soup.find_all(
                attrs={"data-type": "paragraph"}
            )
            if not paragraphs:
                # fallback selector
                paragraphs = soup.select("div.article-content p, article p")
            if not paragraphs:
                return None
            return " ".join(p.get_text(separator=" ").strip() for p in paragraphs)
        except Exception as exc:
            logger.debug("WSJ article body fetch failed: %s", exc)
            return None


def _parse_rss_date(entry) -> Optional[datetime]:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None
