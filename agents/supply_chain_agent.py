"""
SupplyChainAgent: uses Claude to discover and update upstream/downstream
supply chain relationships for a given stock ticker.

Runs weekly via GitHub Actions to keep stocks.json current.
"""
import json
import logging
import re
from typing import Optional

from .base_agent import BaseAgent
from data_sources.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

SYSTEM = """You are a supply chain analyst with deep knowledge of technology, semiconductor,
and industrial sectors. Given a company's profile, identify its key supply chain relationships.

Return a JSON object with exactly this structure:
{
  "upstream": [
    {"ticker": "ASML", "name": "ASML Holding", "relationship": "EUV lithography equipment supplier", "criticality": "high", "revenue_pct": 15},
    ...
  ],
  "downstream": [
    {"ticker": "AAPL", "name": "Apple Inc.", "relationship": "Major chip customer for mobile SoCs", "criticality": "high", "revenue_pct": 20},
    ...
  ],
  "supply_chain_summary": "2 sentence description of this company's position in the supply chain"
}

Rules:
- Return 3-6 upstream and 3-6 downstream companies
- Only include publicly traded companies with real ticker symbols
- Prioritize companies where the relationship is material (>5% revenue impact or critical dependency)
- criticality: "high" (existential/major), "medium" (significant), "low" (minor)
- revenue_pct: your best estimate of what % of the SUBJECT company's revenue or cost base this relationship represents (integer 1-100, or 0 if unknown). For downstream customers, it's % of subject's revenue. For upstream suppliers, it's % of subject's cost/capex. Use publicly known figures from filings when available.
- If a company is both upstream and downstream, pick the primary direction
- For companies with no clear supply chain, return empty arrays with a summary note"""

_FALLBACK = {"upstream": [], "downstream": [], "supply_chain_summary": ""}

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


class SupplyChainAgent(BaseAgent):
    def __init__(self, anthropic_api_key: str):
        super().__init__(anthropic_api_key)
        self._yf = YFinanceClient()

    def discover(self, symbol: str, name: str, sector: str = "") -> dict:
        """
        Returns dict: {
            "upstream": [{"ticker", "name", "relationship", "criticality"}, ...],
            "downstream": [...],
            "supply_chain_summary": "..."
        }
        Falls back to {"upstream": [], "downstream": [], "supply_chain_summary": ""} on error.
        """
        try:
            # 1. Get yfinance context
            info = self._yf.get_ticker_info(symbol)
            long_summary = info.get("longBusinessSummary", "")[:600]
            yf_sector = info.get("sector", sector)
            yf_industry = info.get("industry", "")

            # 2. Build prompt with company profile
            profile = (
                f"Company: {name} ({symbol})\n"
                f"Sector: {yf_sector}\n"
                f"Industry: {yf_industry}\n"
                f"Business summary: {long_summary}\n"
            )
            user_msg = (
                f"{profile}\n"
                "Identify the key upstream suppliers and downstream customers for this company. "
                "Return the JSON as specified."
            )

            # 3. Call _simple_completion
            raw = self._simple_completion(SYSTEM, user_msg, max_tokens=1500)

            # 4. Extract JSON
            parsed = _extract_json(raw, logger)
            if parsed is None:
                logger.warning("SupplyChainAgent: no JSON found for %s", symbol)
                return dict(_FALLBACK)

            # 5. Validate tickers
            for direction in ("upstream", "downstream"):
                entries = parsed.get(direction, [])
                if not isinstance(entries, list):
                    parsed[direction] = []
                    continue
                valid = []
                for entry in entries:
                    ticker = entry.get("ticker", "")
                    if isinstance(ticker, str) and _TICKER_RE.match(ticker):
                        valid.append(entry)
                    else:
                        logger.debug("SupplyChainAgent: skipping invalid ticker %r", ticker)
                parsed[direction] = valid

            if "supply_chain_summary" not in parsed:
                parsed["supply_chain_summary"] = ""

            return parsed

        except Exception as exc:
            logger.error("SupplyChainAgent.discover failed for %s: %s", symbol, exc)
            return dict(_FALLBACK)


def _extract_json(text: str, log) -> Optional[dict]:
    """Extract the largest valid JSON object from text, handling markdown code blocks."""
    # Strip markdown code fences first
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Find each '{' start position and try to extract balanced JSON from there
    starts = [i for i, c in enumerate(text) if c == "{"]
    for start in starts:
        depth = 0
        in_str = False
        escape = False
        for j in range(start, len(text)):
            ch = text[j]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:j + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    log.warning("SupplyChainAgent: could not extract JSON from response")
    return None
