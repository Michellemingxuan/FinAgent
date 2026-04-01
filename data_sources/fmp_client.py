import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"


class FMPClient:
    def __init__(self, api_key: str):
        self._key = api_key
        self._session = requests.Session()
        self._session.params = {"apikey": api_key}  # type: ignore[assignment]

    def get_analyst_ratings(self, symbol: str, limit: int = 5) -> list[dict]:
        """
        Returns a list of recent analyst rating records for the given ticker.
        Each record contains: analystRatingsStrongBuy, analystRatingsBuy, etc.
        Falls back to empty list on any error.
        """
        try:
            resp = self._session.get(
                f"{FMP_BASE}/analyst-stock-recommendations/{symbol}",
                params={"limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.warning("FMP analyst ratings failed for %s: %s", symbol, exc)
            return []

    def get_price_targets(self, symbol: str, limit: int = 5) -> list[dict]:
        """
        Returns recent analyst price target records.
        Each record: analystName, priceTarget, priceWhenPosted, adjPriceTarget, publishedDate, newsURL, newsTitle, newsPublisher
        """
        try:
            resp = self._session.get(
                f"{FMP_BASE}/price-target/{symbol}",
                params={"limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.warning("FMP price targets failed for %s: %s", symbol, exc)
            return []

    def get_upgrades_downgrades(self, symbol: str, limit: int = 5) -> list[dict]:
        """
        Returns recent upgrades/downgrades.
        Each record: publishedDate, newsURL, newsTitle, newsBaseURL, newsPublisher,
                     newGrade, previousGrade, gradingCompany, action, priceWhenPosted
        """
        try:
            resp = self._session.get(
                f"{FMP_BASE}/upgrades-downgrades/{symbol}",
                params={"limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.warning("FMP upgrades/downgrades failed for %s: %s", symbol, exc)
            return []

    def get_quote(self, symbol: str) -> Optional[dict]:
        try:
            resp = self._session.get(
                f"{FMP_BASE}/quote/{symbol}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else None
        except Exception as exc:
            logger.warning("FMP quote failed for %s: %s", symbol, exc)
            return None

    def get_insider_transactions(self, symbol: str, limit: int = 10) -> list[dict]:
        try:
            resp = self._session.get(
                f"{FMP_BASE}/insider-trading/{symbol}",
                params={"limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json() or []
        except Exception as exc:
            logger.warning("FMP insider transactions failed for %s: %s", symbol, exc)
            return []

    def get_short_interest(self, symbol: str) -> Optional[dict]:
        try:
            resp = self._session.get(
                f"{FMP_BASE}/short-volume/{symbol}",
                params={"limit": 1},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return data[0]
        except Exception as exc:
            logger.warning("FMP short interest failed for %s: %s", symbol, exc)
        try:
            resp = self._session.get(
                f"{FMP_BASE}/shares-float/{symbol}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return data[0]
        except Exception as exc2:
            logger.warning("FMP shares-float fallback failed for %s: %s", symbol, exc2)
        return None

    def get_shares_float(self, symbol: str) -> Optional[dict]:
        try:
            resp = self._session.get(
                f"{FMP_BASE}/shares-float/{symbol}",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else None
        except Exception as exc:
            logger.warning("FMP shares float failed for %s: %s", symbol, exc)
            return None
