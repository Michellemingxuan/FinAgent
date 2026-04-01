import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .base_agent import BaseAgent
from data_sources.yfinance_client import YFinanceClient
from models.report import (
    EarningsEvent,
    FinancialMetrics,
    InsiderTransaction,
    PricePoint,
    ShortData,
    TickerFinancials,
)

logger = logging.getLogger(__name__)

SYSTEM = """You are a CFA-level financial analyst. Given 3 years of income statement,
balance sheet, and cash flow data for a company, write a concise analysis using
bullet points covering:
• Revenue and margin trajectory (cite specific numbers)
• Balance sheet health (debt levels, cash position)
• Cash generation quality (free cash flow trends)
• Any notable red flags or highlights
Use 4-6 bullet points. Be specific with numbers. Do not add investment advice."""

# yfinance row name mappings (may vary by ticker/version)
_INCOME_MAP = {
    "Total Revenue": "revenue",
    "Gross Profit": "gross_profit",
    "Operating Income": "operating_income",
    "Net Income": "net_income",
}
_BALANCE_MAP = {
    "Total Assets": "total_assets",
    "Total Debt": "total_debt",
    "Cash And Cash Equivalents": "cash_and_equivalents",
    "Cash Cash Equivalents And Short Term Investments": "cash_and_equivalents",
}
_CASHFLOW_MAP = {
    "Free Cash Flow": "free_cash_flow",
    "Capital Expenditure": "capex",
}


class FinancialsAgent(BaseAgent):
    def __init__(self, anthropic_api_key: str, fmp_api_key: str = "", financials_years: int = 3, lang: str = "en"):
        super().__init__(anthropic_api_key)
        self._yf = YFinanceClient()
        self._years = financials_years
        self._lang = lang

    def run(
        self, ticker_config: dict
    ) -> tuple[TickerFinancials, Optional[EarningsEvent], list[InsiderTransaction], Optional[ShortData], list[PricePoint]]:
        symbol = ticker_config["symbol"]
        name = ticker_config["name"]
        logger.info("Fetching financials for %s", symbol)

        error: Optional[str] = None
        metrics_by_year: list[FinancialMetrics] = []
        info: dict = {}

        try:
            raw = self._yf.get_financials(symbol, years=self._years)
            info = self._yf.get_ticker_info(symbol)
            price = self._yf.get_current_price(symbol)

            # Build per-year metrics
            income = raw.get("income_stmt", {})
            balance = raw.get("balance_sheet", {})
            cashflow = raw.get("cash_flow", {})

            all_years = sorted(
                set(list(income.keys()) + list(balance.keys()) + list(cashflow.keys())),
                reverse=True,
            )[: self._years]

            for year in all_years:
                inc = income.get(year, {})
                bal = balance.get(year, {})
                cf = cashflow.get(year, {})

                revenue = _pick(inc, _INCOME_MAP, "revenue")
                gross_profit = _pick(inc, _INCOME_MAP, "gross_profit")
                operating_income = _pick(inc, _INCOME_MAP, "operating_income")
                net_income = _pick(inc, _INCOME_MAP, "net_income")
                total_assets = _pick(bal, _BALANCE_MAP, "total_assets")
                total_debt = _pick(bal, _BALANCE_MAP, "total_debt")
                cash = _pick(bal, _BALANCE_MAP, "cash_and_equivalents")
                fcf = _pick(cf, _CASHFLOW_MAP, "free_cash_flow")

                metrics_by_year.append(FinancialMetrics(
                    year=year[:4],
                    revenue=revenue,
                    gross_profit=gross_profit,
                    operating_income=operating_income,
                    net_income=net_income,
                    gross_margin=_safe_div(gross_profit, revenue),
                    operating_margin=_safe_div(operating_income, revenue),
                    net_margin=_safe_div(net_income, revenue),
                    total_assets=total_assets,
                    total_debt=total_debt,
                    cash_and_equivalents=cash,
                    free_cash_flow=fcf,
                ))

        except Exception as exc:
            logger.error("Financials fetch failed for %s: %s", symbol, exc)
            error = str(exc)

        market_cap = info.get("marketCap")
        analysis = self._generate_analysis(symbol, name, metrics_by_year, info)

        tf = TickerFinancials(
            symbol=symbol,
            name=name,
            current_price=info.get("currentPrice") or info.get("regularMarketPrice"),
            market_cap=market_cap,
            pe_ratio=info.get("trailingPE"),
            forward_pe=info.get("forwardPE"),
            ev_ebitda=info.get("enterpriseToEbitda"),
            debt_to_equity=info.get("debtToEquity"),
            fcf_yield=_fcf_yield(metrics_by_year, market_cap),
            metrics_by_year=metrics_by_year,
            ai_analysis=analysis,
            error=error,
        )

        earnings_event = self._fetch_earnings_event(symbol)
        insider_txns = self._fetch_insider_transactions(symbol)
        short_data = self._fetch_short_data(symbol)
        price_points = self._fetch_price_history(symbol)

        return tf, earnings_event, insider_txns, short_data, price_points

    def _fetch_earnings_event(self, symbol: str) -> Optional[EarningsEvent]:
        try:
            cal = self._yf.get_earnings_calendar(symbol)
            if not cal:
                return None
            today = datetime.now(timezone.utc).date()
            dates = cal.get("Earnings Date", [])
            # dates is a list of Timestamps; find first one >= today
            upcoming = None
            for d in dates:
                try:
                    d_date = d.date() if hasattr(d, "date") else d
                    if d_date >= today:
                        upcoming = d_date
                        break
                except Exception:
                    continue

            if upcoming is None and dates:
                # fall back to the last date in the list
                try:
                    d = dates[-1]
                    upcoming = d.date() if hasattr(d, "date") else d
                except Exception:
                    pass

            if upcoming is None:
                return None

            # If there are two dates in the list (a range), format as range
            earnings_date_str = str(upcoming)
            if len(dates) >= 2:
                try:
                    d2 = dates[-1]
                    d2_date = d2.date() if hasattr(d2, "date") else d2
                    if d2_date != upcoming:
                        earnings_date_str = f"{upcoming} to {d2_date}"
                except Exception:
                    pass

            days_until = (upcoming - today).days

            eps_est = cal.get("EPS Estimate")
            rev_est = cal.get("Revenue Estimate")
            try:
                eps_est = float(eps_est) if eps_est is not None else None
            except (TypeError, ValueError):
                eps_est = None
            try:
                rev_est = float(rev_est) if rev_est is not None else None
            except (TypeError, ValueError):
                rev_est = None

            return EarningsEvent(
                symbol=symbol,
                earnings_date=earnings_date_str,
                eps_estimate=eps_est,
                revenue_estimate=rev_est,
                days_until=days_until,
            )
        except Exception as exc:
            logger.warning("Earnings event fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_insider_transactions(self, symbol: str) -> list[InsiderTransaction]:
        raw = self._yf.get_insider_transactions(symbol, limit=10)
        result = []
        for rec in raw:
            try:
                shares = _safe_float(rec.get("shares"))
                value = _safe_float(rec.get("value"))
                price = _safe_float(rec.get("price"))
                result.append(InsiderTransaction(
                    reporting_name=rec.get("reporting_name") or "",
                    transaction_type=rec.get("transaction_type") or "",
                    securities_transacted=shares,
                    price=price,
                    total_value=value,
                    transaction_date=rec.get("date") or "",
                    filing_date=rec.get("date") or "",
                ))
            except Exception as exc:
                logger.warning("Insider transaction parse failed for %s: %s", symbol, exc)
        return result

    def _fetch_short_data(self, symbol: str) -> Optional[ShortData]:
        rec = self._yf.get_short_data(symbol)
        if rec is None:
            return None
        return ShortData(
            short_percent_float=rec.get("short_percent_float"),
            short_percent_outstanding=None,
            float_shares=rec.get("float_shares"),
            date=rec.get("date", ""),
        )

    def _fetch_price_history(self, symbol: str) -> list[PricePoint]:
        raw = self._yf.get_price_history(symbol, period="3mo")
        return [PricePoint(date=r["date"], close=r["close"]) for r in raw]

    def _generate_analysis(
        self,
        symbol: str,
        name: str,
        metrics: list[FinancialMetrics],
        info: dict,
    ) -> str:
        if not metrics:
            return f"Financial data unavailable for {symbol}."

        metrics_text = json.dumps(
            [
                {
                    "year": m.year,
                    "revenue_B": _fmt_b(m.revenue),
                    "gross_margin_pct": _fmt_pct(m.gross_margin),
                    "operating_margin_pct": _fmt_pct(m.operating_margin),
                    "net_margin_pct": _fmt_pct(m.net_margin),
                    "free_cash_flow_B": _fmt_b(m.free_cash_flow),
                    "total_debt_B": _fmt_b(m.total_debt),
                    "cash_B": _fmt_b(m.cash_and_equivalents),
                }
                for m in metrics
            ],
            indent=2,
        )

        valuation_text = json.dumps(
            {
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "debt_to_equity": info.get("debtToEquity"),
                "market_cap_B": _fmt_b(info.get("marketCap")),
            },
            indent=2,
        )

        user_msg = (
            f"Company: {name} ({symbol})\n\n"
            f"3-year financials:\n{metrics_text}\n\n"
            f"Current valuation metrics:\n{valuation_text}\n\n"
            "Write bullet-point financial analysis."
        )

        system = SYSTEM
        if self._lang == "zh":
            system += "\n\nIMPORTANT: Write your entire response in Chinese (简体中文)."

        return self._simple_completion(system, user_msg, max_tokens=500)


def _pick(data: dict, mapping: dict, target_key: str) -> Optional[float]:
    for row_name, mapped_key in mapping.items():
        if mapped_key == target_key and row_name in data:
            return data[row_name]
    return None


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fcf_yield(metrics: list[FinancialMetrics], market_cap: Optional[float]) -> Optional[float]:
    if not metrics or market_cap is None or market_cap == 0:
        return None
    fcf = metrics[0].free_cash_flow
    return _safe_div(fcf, market_cap)


def _fmt_b(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val / 1e9:.2f}B"


def _fmt_pct(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val * 100:.1f}%"
