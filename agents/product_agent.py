"""
ProductAgent: Quarterly revenue trends, earnings beat/miss history, forward estimates,
and Claude-generated product & catalyst analysis.
"""

import json
import logging
import re
from typing import Optional

from .base_agent import BaseAgent
from data_sources.yfinance_client import YFinanceClient
from models.report import EarningsBeat, QuarterlySnapshot, TickerProduct

logger = logging.getLogger(__name__)

SEGMENT_SYSTEM = """You are a financial research analyst with deep knowledge of public company filings.
Given a company description and financial data, return a JSON object with:

1. "segments": array of the company's main business segments/product lines that drive revenue.
   Each entry: {"name": "...", "pct": <estimated % of total revenue as integer>, "trend": "growing|stable|declining", "description": "one sentence on what it is and why it matters"}
   - Base percentages on the most recent public filings, investor presentations, or well-known facts.
   - Percentages must sum to 100. Use your knowledge of recent annual reports.
   - List at most 6 segments, combining minor ones into "Other".

2. "value_driver": string — which 1-2 segments are the PRIMARY stock price drivers right now and why (1-2 sentences).

Return ONLY valid JSON, no markdown fences."""

ANALYSIS_SYSTEM = """You are a sell-side equity research analyst. Given a company's quarterly revenue
trend, earnings beat/miss history, forward growth estimates, margin profile, and estimate revision data,
write a concise product and business momentum analysis informative for stock price direction. Cover:

1. **Revenue momentum** — accelerating or decelerating? Cite latest quarter YoY growth rate.
2. **Earnings quality** — beat/miss streak and magnitude. Sandbagging or struggling?
3. **Margin trajectory** — gross/operating margins expanding or compressing and why.
4. **Key product catalysts** — 1-2 most important upcoming catalysts the market will price in.
5. **Estimate revision trend** — Based on analyst up/down revisions, direction: Upward / Neutral / Downward.

Use 5 bullet points. Be specific with numbers. No investment advice."""


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
        forward_data: dict = {}

        try:
            q_data = self._yf.get_quarterly_financials(symbol, quarters=8)
            eh_data = self._yf.get_earnings_history(symbol)
            estimates = self._yf.get_analyst_estimates(symbol)
            forward_data = self._yf.get_revenue_and_eps_estimates(symbol)

            # Build quarterly snapshots with YoY growth (need 8Q to compute YoY for last 4)
            raw_quarters = q_data.get("quarters", [])
            for i, q in enumerate(raw_quarters):
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
            # Keep only last 6 for display
            quarterly_snapshots = quarterly_snapshots[-6:]

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

        # Generate segment breakdown (separate Claude call)
        segments = self._generate_segments(
            symbol, name,
            estimates.get("long_business_summary", ""),
            estimates.get("sector", ""),
            estimates.get("industry", ""),
        )

        ai_analysis = self._generate_analysis(
            symbol, name, quarterly_snapshots, earnings_beats, estimates, forward_data
        )

        return TickerProduct(
            symbol=symbol,
            name=name,
            sector=estimates.get("sector", ticker_config.get("sector", "")),
            industry=estimates.get("industry", ""),
            quarterly_revenue=quarterly_snapshots,
            earnings_history=earnings_beats,
            segments=segments,
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

    def _generate_segments(
        self, symbol: str, name: str, description: str, sector: str, industry: str
    ) -> tuple[list[dict], str]:
        """Ask Claude to return structured segment/product breakdown."""
        user_msg = (
            f"Company: {name} ({symbol})\n"
            f"Sector: {sector} | Industry: {industry}\n\n"
            f"Business description: {description[:600]}\n\n"
            "Return the JSON segment breakdown."
        )
        raw = self._simple_completion(SEGMENT_SYSTEM, user_msg, max_tokens=800)
        try:
            clean = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            # Find balanced JSON object
            start = clean.find("{")
            if start == -1:
                raise ValueError("No JSON object found")
            depth = 0
            for i, ch in enumerate(clean[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        data = json.loads(clean[start:i + 1])
                        return data.get("segments", []), data.get("value_driver", "")
            raise ValueError("Unbalanced JSON")
        except Exception as exc:
            logger.warning("Segment JSON parse failed for %s: %s", symbol, exc)
            return [], ""

    def _generate_analysis(
        self,
        symbol: str,
        name: str,
        quarters: list[QuarterlySnapshot],
        earnings: list[EarningsBeat],
        estimates: dict,
        forward_data: dict,
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
                "surprise_pct": f"{e.surprise_pct:+.1f}%" if e.surprise_pct is not None else None,
            }
            for e in earnings
        ]
        metrics = {
            "sector": estimates.get("sector", ""),
            "ttm_revenue_growth": _fmt_pct(estimates.get("revenue_growth")),
            "ttm_earnings_growth": _fmt_pct(estimates.get("earnings_growth")),
            "earnings_quarterly_growth": _fmt_pct(estimates.get("earnings_quarterly_growth")),
            "gross_margin": _fmt_pct(estimates.get("gross_margins")),
            "operating_margin": _fmt_pct(estimates.get("operating_margins")),
            "return_on_equity": _fmt_pct(estimates.get("return_on_equity")),
            "peg_ratio": estimates.get("peg_ratio"),
            "consensus": estimates.get("recommendation", ""),
            "num_analysts": estimates.get("number_of_analysts"),
        }
        revisions = forward_data.get("eps_revisions", {})

        user_msg = (
            f"Company: {name} ({symbol})\n\n"
            f"Quarterly revenue (oldest→newest):\n{json.dumps(quarters_data, indent=2)}\n\n"
            f"Earnings beat/miss:\n{json.dumps(earnings_data, indent=2)}\n\n"
            f"Metrics:\n{json.dumps(metrics, indent=2)}\n\n"
            f"Analyst EPS revisions (current quarter, last 30 days): {revisions.get('0q', {})}\n\n"
            "Write the analysis."
        )

        system = ANALYSIS_SYSTEM
        if self._lang == "zh":
            system += "\n\nIMPORTANT: Write your entire response in Chinese (简体中文)."

        return self._simple_completion(system, user_msg, max_tokens=1000)


def _fmt_b(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val / 1e9:.2f}B"


def _fmt_pct(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val * 100:.1f}%"
