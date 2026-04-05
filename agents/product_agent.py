"""
ProductAgent: Quarterly revenue trends, earnings beat/miss history, forward estimates,
and Claude-generated product & catalyst analysis.
"""

import json
import logging
from typing import Optional

from .base_agent import BaseAgent
from data_sources.yfinance_client import YFinanceClient
from models.report import EarningsBeat, QuarterlySnapshot, TickerProduct

logger = logging.getLogger(__name__)

SYSTEM = """You are a sell-side equity research analyst. Given a company's quarterly revenue
trend, earnings beat/miss history, forward growth estimates, and margin profile, write a
concise product and business momentum analysis that is specifically informative for stock price
direction. Cover:

1. **Revenue momentum** — Is growth accelerating or decelerating? Cite the most recent quarter's
   YoY growth rate and trend direction.
2. **Earnings quality** — Beat/miss streak and magnitude. Is the company sandbagging or struggling?
3. **Margin trajectory** — Are gross/operating margins expanding or compressing? What drives this?
4. **Key product catalysts** — Based on the sector/industry and current growth profile, what are
   the 1-2 most important product or business catalysts the market will be pricing in next?
5. **Estimate revision risk** — Given growth vs. consensus target price, is this stock more likely
   to see estimate upgrades or cuts? Assign a direction: Upward / Neutral / Downward.

Use 5-6 bullet points. Be specific with numbers. Focus on what drives the stock, not generic
boilerplate. Do not add investment advice."""


class ProductAgent(BaseAgent):
    def __init__(self, anthropic_api_key: str, lang: str = "en"):
        super().__init__(anthropic_api_key)
        self._yf = YFinanceClient()
        self._lang = lang

    def run(self, ticker_config: dict) -> TickerProduct:
        symbol = ticker_config["symbol"]
        name = ticker_config["name"]
        logger.info("Running product analysis for %s", symbol)

        error: Optional[str] = None
        quarterly_snapshots: list[QuarterlySnapshot] = []
        earnings_beats: list[EarningsBeat] = []
        estimates: dict = {}

        try:
            q_data = self._yf.get_quarterly_financials(symbol, quarters=6)
            eh_data = self._yf.get_earnings_history(symbol)
            estimates = self._yf.get_analyst_estimates(symbol)

            # Build quarterly snapshots with YoY growth
            raw_quarters = q_data.get("quarters", [])
            for i, q in enumerate(raw_quarters):
                # YoY = compare to 4 quarters ago (index i - 4)
                yoy = None
                if i >= 4 and raw_quarters[i - 4].get("revenue") and q.get("revenue"):
                    prev = raw_quarters[i - 4]["revenue"]
                    curr = q["revenue"]
                    if prev and prev != 0:
                        yoy = (curr - prev) / abs(prev)
                quarterly_snapshots.append(QuarterlySnapshot(
                    period=q.get("period", ""),
                    revenue=q.get("revenue"),
                    gross_profit=q.get("gross_profit"),
                    operating_income=q.get("operating_income"),
                    net_income=q.get("net_income"),
                    yoy_revenue_growth=yoy,
                ))

            # Build earnings beat history
            for rec in eh_data:
                earnings_beats.append(EarningsBeat(
                    period=rec.get("period", ""),
                    eps_estimate=rec.get("eps_estimate"),
                    eps_actual=rec.get("eps_actual"),
                    surprise_pct=rec.get("surprise_pct"),
                ))

        except Exception as exc:
            logger.error("Product data fetch failed for %s: %s", symbol, exc)
            error = str(exc)

        ai_analysis = self._generate_analysis(
            symbol, name, quarterly_snapshots, earnings_beats, estimates
        )

        return TickerProduct(
            symbol=symbol,
            name=name,
            sector=estimates.get("sector", ticker_config.get("sector", "")),
            industry=estimates.get("industry", ""),
            quarterly_revenue=quarterly_snapshots,
            earnings_history=earnings_beats,
            revenue_growth=estimates.get("revenue_growth"),
            earnings_growth=estimates.get("earnings_growth"),
            earnings_quarterly_growth=estimates.get("earnings_quarterly_growth"),
            gross_margins=estimates.get("gross_margins"),
            operating_margins=estimates.get("operating_margins"),
            return_on_equity=estimates.get("return_on_equity"),
            peg_ratio=estimates.get("peg_ratio"),
            price_to_sales=estimates.get("price_to_sales"),
            eps_forward=estimates.get("eps_forward"),
            target_mean_price=estimates.get("target_mean"),
            current_price=estimates.get("current_price"),
            recommendation=estimates.get("recommendation", ""),
            ai_analysis=ai_analysis,
            error=error,
        )

    def _generate_analysis(
        self,
        symbol: str,
        name: str,
        quarters: list[QuarterlySnapshot],
        earnings: list[EarningsBeat],
        estimates: dict,
    ) -> str:
        quarters_data = [
            {
                "period": q.period,
                "revenue_B": _fmt_b(q.revenue),
                "gross_profit_B": _fmt_b(q.gross_profit),
                "operating_income_B": _fmt_b(q.operating_income),
                "yoy_revenue_growth": _fmt_pct(q.yoy_revenue_growth),
            }
            for q in quarters
        ]
        earnings_data = [
            {
                "period": e.period,
                "eps_estimate": e.eps_estimate,
                "eps_actual": e.eps_actual,
                "beat_miss_pct": _fmt_pct(e.surprise_pct / 100 if e.surprise_pct else None),
            }
            for e in earnings
        ]
        metrics = {
            "sector": estimates.get("sector", ""),
            "industry": estimates.get("industry", ""),
            "ttm_revenue_growth": _fmt_pct(estimates.get("revenue_growth")),
            "ttm_earnings_growth": _fmt_pct(estimates.get("earnings_growth")),
            "earnings_quarterly_growth": _fmt_pct(estimates.get("earnings_quarterly_growth")),
            "gross_margin": _fmt_pct(estimates.get("gross_margins")),
            "operating_margin": _fmt_pct(estimates.get("operating_margins")),
            "return_on_equity": _fmt_pct(estimates.get("return_on_equity")),
            "peg_ratio": estimates.get("peg_ratio"),
            "price_to_sales": estimates.get("price_to_sales"),
            "forward_eps": estimates.get("eps_forward"),
            "analyst_target_mean": estimates.get("target_mean"),
            "current_price": estimates.get("current_price"),
            "consensus": estimates.get("recommendation", ""),
            "num_analysts": estimates.get("number_of_analysts"),
        }

        user_msg = (
            f"Company: {name} ({symbol})\n\n"
            f"Last 6 quarters (oldest → newest):\n{json.dumps(quarters_data, indent=2)}\n\n"
            f"Earnings beat/miss history (oldest → newest):\n{json.dumps(earnings_data, indent=2)}\n\n"
            f"Growth & margin metrics:\n{json.dumps(metrics, indent=2)}\n\n"
            "Write product and business momentum analysis."
        )

        system = SYSTEM
        if self._lang == "zh":
            system += "\n\nIMPORTANT: Write your entire response in Chinese (简体中文)."

        return self._simple_completion(system, user_msg, max_tokens=600)


def _fmt_b(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val / 1e9:.2f}B"


def _fmt_pct(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val * 100:.1f}%"
