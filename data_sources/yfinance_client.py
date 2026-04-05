import logging
from typing import Optional
import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceClient:
    def get_ticker_info(self, symbol: str) -> dict:
        try:
            t = yf.Ticker(symbol)
            return t.info or {}
        except Exception as exc:
            logger.warning("yfinance info failed for %s: %s", symbol, exc)
            return {}

    def get_financials(self, symbol: str, years: int = 3) -> dict:
        """
        Returns a dict with keys: income_stmt, balance_sheet, cash_flow
        Each is a dict mapping column label (year string) → dict of metric → value.
        Limited to the most recent `years` columns.
        """
        result: dict = {"income_stmt": {}, "balance_sheet": {}, "cash_flow": {}}
        try:
            t = yf.Ticker(symbol)

            for attr, key in [
                ("income_stmt", "income_stmt"),
                ("balance_sheet", "balance_sheet"),
                ("cashflow", "cash_flow"),
            ]:
                df = getattr(t, attr)
                if df is None or df.empty:
                    continue
                cols = list(df.columns)[:years]
                for col in cols:
                    col_label = str(col)[:10]  # YYYY-MM-DD
                    result[key][col_label] = {
                        row: _safe_float(df.loc[row, col])
                        for row in df.index
                        if _safe_float(df.loc[row, col]) is not None
                    }
        except Exception as exc:
            logger.warning("yfinance financials failed for %s: %s", symbol, exc)
        return result

    def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="1d")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception as exc:
            logger.warning("yfinance price failed for %s: %s", symbol, exc)
            return None

    def get_earnings_calendar(self, symbol: str) -> Optional[dict]:
        try:
            t = yf.Ticker(symbol)
            cal = t.calendar
            if not cal:
                return None
            result = {}
            if "Earnings Date" in cal:
                result["Earnings Date"] = cal["Earnings Date"]
            if "EPS Estimate" in cal:
                result["EPS Estimate"] = cal["EPS Estimate"]
            if "Revenue Estimate" in cal:
                result["Revenue Estimate"] = cal["Revenue Estimate"]
            return result if result else None
        except Exception as exc:
            logger.warning("yfinance earnings calendar failed for %s: %s", symbol, exc)
            return None

    def get_price_history(self, symbol: str, period: str = "3mo") -> list[dict]:
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period=period)
            if hist.empty:
                return []
            result = []
            for idx, row in hist.iterrows():
                date_str = str(idx)[:10]
                result.append({"date": date_str, "close": float(row["Close"])})
            return result
        except Exception as exc:
            logger.warning("yfinance price history failed for %s: %s", symbol, exc)
            return []

    def get_upgrades_downgrades(self, symbol: str, limit: int = 5) -> list[dict]:
        """Returns recent analyst upgrades/downgrades from yfinance."""
        try:
            t = yf.Ticker(symbol)
            df = t.upgrades_downgrades
            if df is None or df.empty:
                return []
            df = df.sort_index(ascending=False).head(limit).reset_index()
            results = []
            for _, row in df.iterrows():
                date_val = row.get("GradeDate") or row.get("Date") or row.get("index", "")
                results.append({
                    "date": str(date_val)[:10],
                    "firm": str(row.get("Firm", "")),
                    "to_grade": str(row.get("ToGrade", "")),
                    "from_grade": str(row.get("FromGrade", "")),
                    "action": str(row.get("Action", "")),
                })
            return results
        except Exception as exc:
            logger.warning("yfinance upgrades/downgrades failed for %s: %s", symbol, exc)
            return []

    def get_analyst_price_targets(self, symbol: str) -> dict:
        """Returns analyst price target summary from yfinance ticker.info."""
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            return {
                "target_mean": _safe_float(info.get("targetMeanPrice")),
                "target_high": _safe_float(info.get("targetHighPrice")),
                "target_low": _safe_float(info.get("targetLowPrice")),
                "target_median": _safe_float(info.get("targetMedianPrice")),
                "number_of_analysts": info.get("numberOfAnalystOpinions"),
                "recommendation": info.get("recommendationKey", ""),
                "recommendation_mean": _safe_float(info.get("recommendationMean")),
            }
        except Exception as exc:
            logger.warning("yfinance price targets failed for %s: %s", symbol, exc)
            return {}

    def get_insider_transactions(self, symbol: str, limit: int = 10) -> list[dict]:
        """Returns recent insider transactions from yfinance."""
        try:
            t = yf.Ticker(symbol)
            df = t.insider_transactions
            if df is None or df.empty:
                return []
            df = df.head(limit).reset_index(drop=True)
            results = []
            for _, row in df.iterrows():
                shares = _safe_float(row.get("Shares") or row.get("shares"))
                value = _safe_float(row.get("Value") or row.get("value"))
                price = None
                if shares and value and shares != 0:
                    price = value / shares
                start_date = row.get("Start Date") or row.get("startDate") or row.get("Date", "")
                results.append({
                    "reporting_name": str(row.get("Insider") or row.get("insider") or ""),
                    "transaction_type": str(row.get("Transaction") or row.get("transaction") or ""),
                    "shares": shares,
                    "value": value,
                    "price": price,
                    "date": str(start_date)[:10],
                    "position": str(row.get("Position") or row.get("position") or ""),
                })
            return results
        except Exception as exc:
            logger.warning("yfinance insider transactions failed for %s: %s", symbol, exc)
            return []

    def get_short_data(self, symbol: str) -> Optional[dict]:
        """Returns short interest data from yfinance ticker.info."""
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            short_pct_float = _safe_float(info.get("shortPercentOfFloat"))
            shares_short = _safe_float(info.get("sharesShort"))
            float_shares = _safe_float(info.get("floatShares"))
            short_ratio = _safe_float(info.get("shortRatio"))
            if short_pct_float is None and shares_short is None:
                return None
            return {
                "short_percent_float": short_pct_float,
                "shares_short": shares_short,
                "float_shares": float_shares,
                "short_ratio": short_ratio,
                "date": "",
            }
        except Exception as exc:
            logger.warning("yfinance short data failed for %s: %s", symbol, exc)
            return None


    def get_quarterly_financials(self, symbol: str, quarters: int = 6) -> dict:
        """Returns last N quarters of revenue, gross profit, operating income, net income."""
        result: list[dict] = []
        try:
            t = yf.Ticker(symbol)
            df = t.quarterly_income_stmt
            if df is None or df.empty:
                return {"quarters": []}
            cols = list(df.columns)[:quarters]
            for col in cols:
                label = str(col)[:7]  # YYYY-MM
                row: dict = {"period": label}
                for src_name, dst_key in [
                    ("Total Revenue", "revenue"),
                    ("Gross Profit", "gross_profit"),
                    ("Operating Income", "operating_income"),
                    ("Net Income", "net_income"),
                ]:
                    if src_name in df.index:
                        row[dst_key] = _safe_float(df.loc[src_name, col])
                result.append(row)
        except Exception as exc:
            logger.warning("yfinance quarterly financials failed for %s: %s", symbol, exc)
        return {"quarters": list(reversed(result))}  # oldest first

    def get_earnings_history(self, symbol: str) -> list[dict]:
        """Returns EPS actual vs estimate for the last ~4 quarters."""
        try:
            t = yf.Ticker(symbol)
            df = t.earnings_history
            if df is None or df.empty:
                return []
            # yfinance index is 'quarter' (Timestamps), columns: epsActual, epsEstimate, surprisePercent
            df = df.sort_index(ascending=False).head(4).reset_index()
            results = []
            for _, row in df.iterrows():
                # Index column after reset_index is named 'quarter'
                period_val = row.get("quarter") or row.get("Quarter") or row.get("index", "")
                period = str(period_val)[:7]
                # Columns are camelCase: epsActual, epsEstimate, surprisePercent
                eps_est = _safe_float(row.get("epsEstimate") or row.get("epsestimate"))
                eps_act = _safe_float(row.get("epsActual") or row.get("epsactual"))
                surprise_pct = _safe_float(row.get("surprisePercent") or row.get("epssurprisepct"))
                # surprisePercent is a ratio (0.08 = 8%), convert to percent
                if surprise_pct is not None and abs(surprise_pct) < 5:
                    surprise_pct = surprise_pct * 100
                results.append({
                    "period": period,
                    "eps_estimate": eps_est,
                    "eps_actual": eps_act,
                    "surprise_pct": surprise_pct,
                })
            return list(reversed(results))  # oldest first
        except Exception as exc:
            logger.warning("yfinance earnings history failed for %s: %s", symbol, exc)
            return []

    def get_revenue_and_eps_estimates(self, symbol: str) -> dict:
        """Returns forward revenue estimates and EPS revision counts."""
        result: dict = {"revenue_estimates": [], "eps_revisions": {}}
        try:
            t = yf.Ticker(symbol)
            rev_df = t.revenue_estimate
            if rev_df is not None and not rev_df.empty:
                rev_df = rev_df.reset_index()
                for _, row in rev_df.iterrows():
                    period = str(row.get("period", ""))
                    result["revenue_estimates"].append({
                        "period": period,
                        "avg": _safe_float(row.get("avg")),
                        "low": _safe_float(row.get("low")),
                        "high": _safe_float(row.get("high")),
                        "growth": _safe_float(row.get("growth")),
                    })
            rev_df2 = t.eps_revisions
            if rev_df2 is not None and not rev_df2.empty:
                rev_df2 = rev_df2.reset_index()
                for _, row in rev_df2.iterrows():
                    period = str(row.get("period", ""))
                    result["eps_revisions"][period] = {
                        "up_7d": int(row.get("upLast7days") or 0),
                        "up_30d": int(row.get("upLast30days") or 0),
                        "down_30d": int(row.get("downLast30days") or 0),
                        "down_7d": int(row.get("downLast7Days") or 0),
                    }
        except Exception as exc:
            logger.warning("yfinance revenue/eps estimates failed for %s: %s", symbol, exc)
        return result

    def get_analyst_estimates(self, symbol: str) -> dict:
        """Returns forward EPS/revenue estimates and revision trend from ticker.info."""
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            return {
                "eps_current_year": _safe_float(info.get("epsCurrentYear")),
                "eps_forward": _safe_float(info.get("epsForward") or info.get("forwardEps")),
                "revenue_growth": _safe_float(info.get("revenueGrowth")),
                "earnings_growth": _safe_float(info.get("earningsGrowth")),
                "earnings_quarterly_growth": _safe_float(info.get("earningsQuarterlyGrowth")),
                "gross_margins": _safe_float(info.get("grossMargins")),
                "operating_margins": _safe_float(info.get("operatingMargins")),
                "profit_margins": _safe_float(info.get("profitMargins")),
                "return_on_equity": _safe_float(info.get("returnOnEquity")),
                "return_on_assets": _safe_float(info.get("returnOnAssets")),
                "revenue_per_share": _safe_float(info.get("revenuePerShare")),
                "peg_ratio": _safe_float(info.get("pegRatio")),
                "price_to_sales": _safe_float(info.get("priceToSalesTrailing12Months")),
                "price_to_book": _safe_float(info.get("priceToBook")),
                "long_business_summary": info.get("longBusinessSummary", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "number_of_analysts": info.get("numberOfAnalystOpinions"),
                "recommendation": info.get("recommendationKey", ""),
                "target_mean": _safe_float(info.get("targetMeanPrice")),
                "current_price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
            }
        except Exception as exc:
            logger.warning("yfinance analyst estimates failed for %s: %s", symbol, exc)
            return {}


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None
