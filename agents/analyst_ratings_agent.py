import json
import logging
from typing import Optional

from .base_agent import BaseAgent
from data_sources.yfinance_client import YFinanceClient
from data_sources.stockanalysis_client import StockAnalysisClient
from models.report import AnalystRating, TickerRatings

logger = logging.getLogger(__name__)

SYSTEM = """You are a senior equity research analyst. Given raw analyst rating and
price target data for a stock, write a concise 2-3 sentence rationale paragraph
that synthesizes the consensus view, key bull/bear arguments, and any notable
rating changes. Be factual and grounded in the data provided. Do not speculate
beyond what the data shows."""


class AnalystRatingsAgent(BaseAgent):
    def __init__(self, anthropic_api_key: str, fmp_api_key: str = "", ratings_count: int = 5):
        super().__init__(anthropic_api_key)
        self._yf = YFinanceClient()
        self._sa = StockAnalysisClient()
        self._count = ratings_count

    def run(self, ticker_config: dict) -> TickerRatings:
        symbol = ticker_config["symbol"]
        name = ticker_config["name"]
        logger.info("Fetching analyst ratings for %s", symbol)

        price = None
        ratings: list[AnalystRating] = []
        pt_summary: dict = {}
        error: Optional[str] = None

        try:
            price = self._yf.get_current_price(symbol)
            pt_summary = self._yf.get_analyst_price_targets(symbol)

            # Individual firm ratings + PTs from StockAnalysis
            sa_ratings = self._sa.get_analyst_ratings(symbol, limit=self._count)
            for rec in sa_ratings:
                ratings.append(AnalystRating(
                    firm=rec.get("firm", "Unknown"),
                    analyst=rec.get("analyst", ""),
                    rating=rec.get("rating", ""),
                    previous_rating=rec.get("previous_rating") or None,
                    price_target=rec.get("price_target"),
                    previous_price_target=rec.get("previous_price_target"),
                    date=rec.get("date", ""),
                    action=rec.get("action", ""),
                ))

            # Fall back to yfinance upgrades/downgrades if scrape returned nothing
            if not ratings:
                logger.info("StockAnalysis returned no ratings for %s, falling back to yfinance", symbol)
                upgrades = self._yf.get_upgrades_downgrades(symbol, limit=self._count)
                for rec in upgrades:
                    ratings.append(AnalystRating(
                        firm=rec.get("firm", "Unknown"),
                        analyst="",
                        rating=rec.get("to_grade", ""),
                        previous_rating=rec.get("from_grade") or None,
                        price_target=None,
                        previous_price_target=None,
                        date=rec.get("date", ""),
                        action=rec.get("action", ""),
                    ))

        except Exception as exc:
            logger.error("Ratings fetch failed for %s: %s", symbol, exc)
            error = str(exc)

        rationale = self._generate_rationale(symbol, name, price, ratings, pt_summary)

        return TickerRatings(
            symbol=symbol,
            name=name,
            current_price=price,
            ratings=ratings,
            ai_rationale=rationale,
            error=error,
        )

    def _generate_rationale(
        self,
        symbol: str,
        name: str,
        price: Optional[float],
        ratings: list[AnalystRating],
        pt_summary: dict,
    ) -> str:
        if not ratings and not pt_summary:
            return f"No recent analyst ratings data available for {symbol}."

        ratings_text = json.dumps(
            [
                {
                    "firm": r.firm,
                    "rating": r.rating,
                    "previous_rating": r.previous_rating,
                    "date": r.date,
                    "action": r.action,
                }
                for r in ratings
            ],
            indent=2,
        )

        price_str = f"${price:.2f}" if price else "N/A"
        pt_text = ""
        if pt_summary:
            pt_text = (
                f"\nConsensus price targets ({pt_summary.get('number_of_analysts', '?')} analysts): "
                f"Mean ${pt_summary.get('target_mean') or 'N/A'}, "
                f"High ${pt_summary.get('target_high') or 'N/A'}, "
                f"Low ${pt_summary.get('target_low') or 'N/A'}. "
                f"Recommendation: {pt_summary.get('recommendation', 'N/A')} "
                f"(mean score {pt_summary.get('recommendation_mean') or 'N/A'}/5)."
            )

        user_msg = (
            f"Stock: {name} ({symbol})\n"
            f"Current price: {price_str}{pt_text}\n\n"
            f"Recent analyst actions:\n{ratings_text}\n\n"
            "Write a 2-3 sentence rationale paragraph synthesizing these ratings."
        )

        return self._simple_completion(SYSTEM, user_msg, max_tokens=300)
