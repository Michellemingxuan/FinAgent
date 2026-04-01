"""
Scrapes individual analyst ratings and price targets from stockanalysis.com.

Source: https://stockanalysis.com/stocks/{ticker}/forecast/
Table columns: Analyst, Firm, Rating, Action, Price Target, Upside, Date

No authentication required. Falls back to empty list gracefully on any error.
"""

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://stockanalysis.com/stocks/{ticker}/forecast/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://stockanalysis.com/",
}
_REQUEST_DELAY = 1.5  # seconds between requests to be polite


class StockAnalysisClient:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._last_request = 0.0

    def get_analyst_ratings(self, symbol: str, limit: int = 10) -> list[dict]:
        """
        Returns up to `limit` most recent individual analyst ratings.
        Each dict: analyst, firm, rating, previous_rating, action,
                   price_target, previous_price_target, upside_pct, date
        """
        self._throttle()
        url = _BASE.format(ticker=symbol.lower())
        try:
            resp = self._session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("StockAnalysis fetch failed for %s: %s", symbol, exc)
            return []

        return _parse_ratings_table(resp.text, limit)

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < _REQUEST_DELAY:
            time.sleep(_REQUEST_DELAY - elapsed)
        self._last_request = time.time()


def _parse_ratings_table(html: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # Find the analyst ratings table — has headers: Analyst, Firm, Rating, Action, Price Target, ...
    target_table = None
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if "Analyst" in headers and "Firm" in headers and "Price Target" in headers:
            target_table = table
            break

    if target_table is None:
        logger.warning("StockAnalysis: could not find analyst ratings table in page")
        return []

    results = []
    rows = target_table.find_all("tr")[1:]  # skip header row

    for row in rows[:limit]:
        cells = row.find_all("td")
        if len(cells) < 7:
            continue
        try:
            # Layout: [0]=analyst+firm, [1]=firm, [2]=rating+action+pt(combined),
            #         [3]=rating, [4]=action, [5]=price_target, [6]=upside, [7]=date
            analyst = _parse_analyst_from_cell(cells[0], cells[1].get_text(strip=True))
            firm = cells[1].get_text(strip=True)
            rating = cells[3].get_text(strip=True)
            action = cells[4].get_text(strip=True)
            pt, prev_pt = _parse_price_target_cell(cells[5])
            upside = _parse_upside(cells[6].get_text(strip=True))
            date = cells[7].get_text(strip=True) if len(cells) > 7 else ""

            results.append({
                "analyst": analyst,
                "firm": firm,
                "rating": rating,
                "previous_rating": None,
                "action": action,
                "price_target": pt,
                "previous_price_target": prev_pt,
                "upside_pct": upside,
                "date": _normalize_date(date),
            })
        except Exception as exc:
            logger.debug("StockAnalysis row parse failed: %s", exc)
            continue

    return results


def _parse_analyst_from_cell(cell, firm_name: str) -> str:
    """Cell[0] has analyst+firm concatenated (e.g. 'Kevin CassidyRosenblatt').
    Strip the firm suffix to get the analyst name."""
    text = cell.get_text(strip=True)
    if firm_name and text.endswith(firm_name):
        return text[: -len(firm_name)].strip()
    return text


def _parse_price_target_cell(cell) -> tuple[Optional[float], Optional[float]]:
    """
    Cell text looks like "$325" or "$291→$323".
    Returns (current_pt, previous_pt).
    """
    text = cell.get_text(strip=True).replace(",", "")
    arrow_variants = ["→", "->", "➝", "⟶"]
    for arrow in arrow_variants:
        if arrow in text:
            parts = text.split(arrow)
            return _parse_dollar(parts[-1].strip()), _parse_dollar(parts[0].strip())
    return _parse_dollar(text), None


def _parse_dollar(text: str) -> Optional[float]:
    text = text.replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_upside(text: str) -> Optional[float]:
    """Parse '+86.35%' or '-12.5%' → float (as fraction, e.g. 0.8635)."""
    text = text.replace("%", "").replace("+", "").strip()
    try:
        return float(text) / 100
    except ValueError:
        return None


def _normalize_date(date_str: str) -> str:
    """Convert 'Mar 23, 2026' → '2026-03-23'."""
    try:
        from datetime import datetime
        return datetime.strptime(date_str, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str
