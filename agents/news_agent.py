import json
import logging
from typing import Optional

from .base_agent import BaseAgent
from data_sources.rss_client import RSSClient
from data_sources.wsj_client import WSJClient
from models.report import NewsItem, NewsSection

logger = logging.getLogger(__name__)

RELEVANCE_SYSTEM = """You are a financial news analyst. Given a list of news headlines
and a portfolio of stocks (with their upstream/downstream supply chains), your job is to:
1. Classify each news item as: "direct" (about a held ticker), "market" (upstream/downstream
   supply chain), or "macro" (general market/economic).
2. For each item, list which tickers from the extended universe are relevant.
3. Flag any tickers NOT in the portfolio that are worth monitoring based on the news.
4. Write a 2-3 sentence narrative summarizing the most important market themes.

Return a JSON object with this exact structure:
{
  "classified_items": [
    {
      "index": 0,
      "category": "direct|market|macro",
      "relevant_tickers": ["NVDA", "TSM"],
      "importance": "high|medium|low"
    }
  ],
  "flagged_tickers": ["ASML", "AMD"],
  "narrative": "..."
}"""


class NewsAgent(BaseAgent):
    def __init__(
        self,
        anthropic_api_key: str,
        wsj_cookie: Optional[str] = None,
        lookback_days: int = 3,
        max_per_ticker: int = 4,
        max_macro: int = 5,
    ):
        super().__init__(anthropic_api_key)
        self._rss = RSSClient(lookback_days=lookback_days)
        self._wsj = WSJClient(cookie=wsj_cookie, lookback_days=lookback_days)
        self._max_per_ticker = max_per_ticker
        self._max_macro = max_macro

    def run(self, ticker_configs: list[dict]) -> NewsSection:
        logger.info("Fetching news for %d tickers", len(ticker_configs))
        all_symbols = {t["symbol"] for t in ticker_configs}
        extended_symbols = all_symbols.copy()
        for t in ticker_configs:
            extended_symbols.update(t.get("upstream", []))
            extended_symbols.update(t.get("downstream", []))

        # Fetch raw news
        raw_items: list[dict] = []
        raw_items.extend(self._wsj.fetch_headlines())
        raw_items = self._wsj.enrich_with_full_text(raw_items)

        for symbol in all_symbols:
            raw_items.extend(self._rss.fetch_yahoo_for_ticker(symbol))
        raw_items.extend(self._rss.fetch_yahoo_general())

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_items: list[dict] = []
        for item in raw_items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                unique_items.append(item)

        if not unique_items:
            return NewsSection(
                direct_news=[],
                market_news=[],
                macro_news=[],
                flagged_tickers=[],
                ai_summary="No news items found for the selected tickers.",
                error="No news items fetched",
            )

        # Ask Claude to classify and analyze
        classification = self._classify_news(
            unique_items, ticker_configs, list(extended_symbols)
        )

        # Build structured output
        classified = {c["index"]: c for c in classification.get("classified_items", [])}
        direct_news: list[NewsItem] = []
        market_news: list[NewsItem] = []
        macro_news: list[NewsItem] = []

        for i, raw in enumerate(unique_items):
            meta = classified.get(i, {"category": "macro", "relevant_tickers": [], "importance": "low"})
            if meta.get("importance") == "low" and meta.get("category") == "macro":
                continue  # skip low-importance macro noise

            item = NewsItem(
                title=raw["title"],
                source=raw["source"],
                url=raw["url"],
                published=raw["published"],
                summary=raw["summary"],
                full_text_available=raw.get("full_text_available", False),
                relevant_tickers=meta.get("relevant_tickers", []),
            )
            cat = meta.get("category", "macro")
            if cat == "direct":
                direct_news.append(item)
            elif cat == "market":
                market_news.append(item)
            else:
                macro_news.append(item)

        # Apply limits
        direct_news = _top_n(direct_news, self._max_per_ticker * len(ticker_configs))
        market_news = _top_n(market_news, self._max_per_ticker * 2)
        macro_news = _top_n(macro_news, self._max_macro)

        return NewsSection(
            direct_news=direct_news,
            market_news=market_news,
            macro_news=macro_news,
            flagged_tickers=classification.get("flagged_tickers", []),
            ai_summary=classification.get("narrative", ""),
        )

    def _classify_news(
        self,
        items: list[dict],
        ticker_configs: list[dict],
        extended_symbols: list[str],
    ) -> dict:
        # Pass only title+summary to Claude to keep tokens manageable
        items_for_claude = [
            {
                "index": i,
                "title": item["title"],
                "summary": item["summary"][:300],
                "source": item["source"],
            }
            for i, item in enumerate(items[:60])  # cap at 60 items
        ]

        portfolio_info = {
            t["symbol"]: {
                "name": t["name"],
                "upstream": t.get("upstream", []),
                "downstream": t.get("downstream", []),
            }
            for t in ticker_configs
        }

        user_msg = (
            f"Portfolio:\n{json.dumps(portfolio_info, indent=2)}\n\n"
            f"Extended ticker universe: {extended_symbols}\n\n"
            f"News items:\n{json.dumps(items_for_claude, indent=2)}\n\n"
            "Classify each news item and return the JSON response."
        )

        raw = self._simple_completion(RELEVANCE_SYSTEM, user_msg, max_tokens=3000)

        return _extract_json(raw, logger) or {"classified_items": [], "flagged_tickers": [], "narrative": raw}


def _top_n(items: list[NewsItem], n: int) -> list[NewsItem]:
    return items[:n]


def _extract_json(text: str, log) -> dict | None:
    """Extract first valid JSON object from text, handling markdown code blocks."""
    import re
    # Strip markdown code fences first
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Try progressively smaller substrings starting at each '{'
    for start in [i for i, c in enumerate(text) if c == "{"]:
        for end in [i + 1 for i, c in enumerate(text) if c == "}" and i >= start]:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
    log.warning("News classification: could not extract JSON from response")
    return None
