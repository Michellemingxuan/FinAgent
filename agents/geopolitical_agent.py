import json
import logging

from .base_agent import BaseAgent
from models.report import GeopoliticalTheme, NewsSection

logger = logging.getLogger(__name__)

SYSTEM = """You are a geopolitical risk analyst specializing in technology and financial markets.
Given a set of RECENT news headlines (each with a publication date), identify distinct geopolitical
developments that are actively unfolding RIGHT NOW and could materially affect the portfolio.

CRITICAL RULES:
- Every theme you identify MUST be directly triggered by at least one headline from the provided list.
- Do NOT invent or recall general background knowledge about long-standing risks (e.g. "China has
  always threatened Taiwan"). Only surface a theme if a specific recent headline evidences it.
- Include the triggering headline text verbatim in source_headlines.
- Include the publication date of the most recent triggering headline in latest_date (YYYY-MM-DD).
- Write the analysis bullets in present-tense, event-driven language:
  e.g. "• [Date] — New rule restricts H20 chip exports; NVDA guides down ~$5.5B"
  NOT "• The US has historically imposed export controls..."

For each theme:
- Name it concisely after the specific current event (e.g. "BIS H20 Export Licensing Rule — Apr 2025")
- List which portfolio tickers are affected
- Assign risk level: Low / Medium / Medium-High / High
- Write 2-3 bullet points, each starting with the event date and key fact

Return a JSON object with this exact structure:
{
  "themes": [
    {
      "theme": "...",
      "affected_tickers": ["NVDA", "TSM"],
      "risk_level": "Medium-High",
      "latest_date": "2025-04-15",
      "analysis": "• [date] — fact\n• [date] — fact",
      "source_headlines": ["exact headline text from input"]
    }
  ],
  "portfolio_summary": "• bullet 1\n• bullet 2"
}

Focus on: trade policy, sanctions, export controls, geopolitical conflicts, supply chain
disruptions, regulatory actions by governments. Omit purely domestic business/earnings news.
If there are no geopolitical headlines at all, return {"themes": [], "portfolio_summary": "No geopolitical events in recent headlines."}"""


class GeopoliticalAgent(BaseAgent):
    def __init__(self, anthropic_api_key: str, lang: str = "en"):
        super().__init__(anthropic_api_key)
        self._lang = lang

    def run(
        self,
        ticker_configs: list[dict],
        news_section: NewsSection,
    ) -> tuple[list[GeopoliticalTheme], str]:
        logger.info("Running geopolitical analysis")

        all_news = (
            news_section.direct_news
            + news_section.market_news
            + news_section.macro_news
        )

        headlines = [
            {
                "title": item.title,
                "source": item.source,
                "published": item.published,
                "summary": item.summary[:200],
            }
            for item in all_news
        ]

        portfolio_symbols = [t["symbol"] for t in ticker_configs]
        flagged = news_section.flagged_tickers

        user_msg = (
            f"Portfolio tickers: {portfolio_symbols}\n"
            f"Flagged watch tickers: {flagged}\n\n"
            f"Recent headlines ({len(headlines)} items):\n"
            f"{json.dumps(headlines, indent=2)}\n\n"
            "Identify geopolitical themes and return the JSON response."
        )

        system = SYSTEM
        if self._lang == "zh":
            system += "\n\nIMPORTANT: Write the analysis bullets and portfolio_summary bullets in Chinese (简体中文). Keep the JSON keys and risk_level values in English."

        raw = self._simple_completion(system, user_msg, max_tokens=2000)

        data = _extract_json(raw)
        if data:
            try:
                themes = [
                    GeopoliticalTheme(
                        theme=t["theme"],
                        affected_tickers=t.get("affected_tickers", []),
                        risk_level=t.get("risk_level", "Medium"),
                        ai_analysis=t.get("analysis", ""),
                        source_headlines=t.get("source_headlines", []),
                        latest_date=t.get("latest_date", ""),
                    )
                    for t in data.get("themes", [])
                ]
                summary = data.get("portfolio_summary", "")
                return themes, summary
            except (KeyError, TypeError) as exc:
                logger.warning("Geopolitical theme parse failed: %s", exc)

        return [], raw


def _extract_json(text: str) -> dict | None:
    import re
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    for start in [i for i, c in enumerate(text) if c == "{"]:
        for end in [i + 1 for i, c in enumerate(text) if c == "}" and i >= start]:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
    return None
