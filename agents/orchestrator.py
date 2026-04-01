"""
Orchestrator: runs all four section agents and assembles the ReportContext.

The four agents run as follows:
  - AnalystRatingsAgent, NewsAgent, FinancialsAgent run in parallel via threads
  - GeopoliticalAgent runs after NewsAgent completes (needs its output)
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .analyst_ratings_agent import AnalystRatingsAgent
from .news_agent import NewsAgent
from .financials_agent import FinancialsAgent
from .geopolitical_agent import GeopoliticalAgent
from models.report import (
    EarningsEvent,
    InsiderTransaction,
    PeerRow,
    PricePoint,
    ReportContext,
    ShortData,
    TickerFinancials,
    TickerRatings,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        anthropic_api_key: str,
        fmp_api_key: str = "",
        wsj_cookie: Optional[str] = None,
        report_settings: Optional[dict] = None,
        delivery_config: Optional[dict] = None,
        report_output_dir: str = "output",
    ):
        settings = report_settings or {}
        self._fmp_api_key = fmp_api_key
        self._delivery_config = delivery_config or {}
        self._report_output_dir = report_output_dir

        self._ratings_agent = AnalystRatingsAgent(
            anthropic_api_key=anthropic_api_key,
            fmp_api_key=fmp_api_key,
            ratings_count=settings.get("analyst_ratings_count", 5),
        )
        self._news_agent = NewsAgent(
            anthropic_api_key=anthropic_api_key,
            wsj_cookie=wsj_cookie,
            lookback_days=settings.get("news_lookback_days", 3),
            max_per_ticker=settings.get("max_news_per_ticker", 4),
            max_macro=settings.get("max_macro_news", 5),
        )
        self._financials_agent = FinancialsAgent(
            anthropic_api_key=anthropic_api_key,
            fmp_api_key=fmp_api_key,
            financials_years=settings.get("financials_years", 3),
        )
        self._geo_agent = GeopoliticalAgent(anthropic_api_key=anthropic_api_key)

    def run(self, ticker_configs: list[dict], themes: Optional[list[dict]] = None, supply_chain_detail: Optional[dict] = None) -> ReportContext:
        errors: list[str] = []
        symbols = [t["symbol"] for t in ticker_configs]
        logger.info("Starting report generation for: %s", symbols)

        ratings_results: list[TickerRatings] = []
        financials_results: list[TickerFinancials] = []
        news_result = None

        # Extra data collected per ticker from FinancialsAgent
        all_earnings: list[EarningsEvent] = []
        all_insider: dict[str, list[InsiderTransaction]] = {}
        all_short: dict[str, ShortData] = {}
        all_price_history: dict[str, list[PricePoint]] = {}

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}

            for tc in ticker_configs:
                f = pool.submit(self._ratings_agent.run, tc)
                futures[f] = ("ratings", tc["symbol"])

            f = pool.submit(self._news_agent.run, ticker_configs)
            futures[f] = ("news", "all")

            for tc in ticker_configs:
                f = pool.submit(self._financials_agent.run, tc)
                futures[f] = ("financials", tc["symbol"])

            for future in as_completed(futures):
                kind, label = futures[future]
                try:
                    result = future.result()
                    if kind == "ratings":
                        ratings_results.append(result)
                    elif kind == "news":
                        news_result = result
                    elif kind == "financials":
                        tf, earnings_ev, insider_txns, short_data, price_pts = result
                        financials_results.append(tf)
                        if earnings_ev is not None:
                            all_earnings.append(earnings_ev)
                        if insider_txns:
                            all_insider[tf.symbol] = insider_txns
                        if short_data is not None:
                            all_short[tf.symbol] = short_data
                        if price_pts:
                            all_price_history[tf.symbol] = price_pts
                except Exception as exc:
                    logger.error("%s failed for %s: %s", kind, label, exc)
                    errors.append(f"{kind}/{label}: {exc}")

        order = {t["symbol"]: i for i, t in enumerate(ticker_configs)}
        ratings_results.sort(key=lambda r: order.get(r.symbol, 99))
        financials_results.sort(key=lambda r: order.get(r.symbol, 99))

        if news_result is None:
            from models.report import NewsSection
            news_result = NewsSection(
                direct_news=[], market_news=[], macro_news=[],
                flagged_tickers=[], ai_summary="News unavailable.",
                error="News agent failed",
            )
            errors.append("news/all: agent returned None")

        geo_themes, geo_summary = [], ""
        try:
            geo_themes, geo_summary = self._geo_agent.run(ticker_configs, news_result)
        except Exception as exc:
            logger.error("Geopolitical agent failed: %s", exc)
            errors.append(f"geopolitical: {exc}")

        peer_table = _build_peer_table(financials_results, all_short)

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        return ReportContext(
            generated_at=generated_at,
            watchlist_symbols=symbols,
            ratings=ratings_results,
            news=news_result,
            financials=financials_results,
            geopolitical_themes=geo_themes,
            geopolitical_summary=geo_summary,
            errors=errors,
            earnings_events=all_earnings,
            insider_transactions=all_insider,
            short_data=all_short,
            price_history=all_price_history,
            peer_table=peer_table,
            themes=themes or [],
            supply_chain_detail=supply_chain_detail or {},
        )

    def render_html(
        self,
        context: ReportContext,
        template_dir: str,
        output_path: str,
        github_repo: Optional[str] = None,
        archive_dates: Optional[list[str]] = None,
    ) -> str:
        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
        )
        env.globals["fmt_b"] = _fmt_billions
        env.globals["fmt_pct"] = _fmt_pct
        env.globals["fmt_price"] = _fmt_price
        env.tests["containing"] = lambda seq, item: item in (seq or [])

        template = env.get_template("report.html.j2")
        html = template.render(
            ctx=context,
            github_repo=github_repo,
            archive_dates=archive_dates or [],
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html, encoding="utf-8")
        logger.info("Report written to %s", output_path)
        return html

    def save_archive(self, html_content: str, output_dir: str, date_str: str) -> list[str]:
        archive_dir = Path(output_dir) / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{date_str}.html"
        archive_path.write_text(html_content, encoding="utf-8")
        logger.info("Archive saved to %s", archive_path)

        dates = []
        for p in archive_dir.iterdir():
            if p.suffix == ".html" and p.stem:
                dates.append(p.stem)
        dates.sort()
        return dates

    def deliver(
        self,
        ctx: ReportContext,
        subscribers: dict,
        report_url: Optional[str] = None,
    ) -> None:
        from delivery.digest import build_digest
        digest = build_digest(ctx, report_url=report_url or "")

        cfg = self._delivery_config
        email_addresses = subscribers.get("email", [])
        if email_addresses and cfg.get("smtp_host") and cfg.get("smtp_user"):
            from delivery.email_sender import EmailSender
            sender = EmailSender(
                smtp_host=cfg["smtp_host"],
                smtp_port=int(cfg.get("smtp_port", 587)),
                username=cfg["smtp_user"],
                password=cfg.get("smtp_password", ""),
            )
            sender.send(
                to_addresses=email_addresses,
                subject=digest["subject"],
                html_body=digest["html"],
                text_body=digest["text"],
            )

        wa_apikey = os.environ.get("WHATSAPP_APIKEY", "").strip() or cfg.get("whatsapp_apikey", "")
        whatsapp_numbers = subscribers.get("whatsapp", [])
        if wa_apikey and whatsapp_numbers:
            from delivery.whatsapp_sender import WhatsAppSender
            wa = WhatsAppSender(api_key=wa_apikey)
            wa.send(phone_numbers=whatsapp_numbers, text=digest["text"])



def _build_peer_table(
    financials: list[TickerFinancials],
    short_data: dict,
) -> list[PeerRow]:
    rows = []
    for tf in financials:
        gross_margin = None
        revenue_growth = None
        if tf.metrics_by_year:
            m0 = tf.metrics_by_year[0]
            gross_margin = m0.gross_margin
            if len(tf.metrics_by_year) >= 2:
                m1 = tf.metrics_by_year[1]
                if m0.revenue and m1.revenue and m1.revenue != 0:
                    revenue_growth = (m0.revenue - m1.revenue) / abs(m1.revenue)

        sd = short_data.get(tf.symbol)
        short_pct = None
        if sd:
            short_pct = sd.short_percent_float or sd.short_percent_outstanding

        rows.append(PeerRow(
            symbol=tf.symbol,
            name=tf.name,
            current_price=tf.current_price,
            market_cap=tf.market_cap,
            pe_ratio=tf.pe_ratio,
            forward_pe=tf.forward_pe,
            ev_ebitda=tf.ev_ebitda,
            gross_margin=gross_margin,
            revenue_growth=revenue_growth,
            debt_to_equity=tf.debt_to_equity,
            fcf_yield=tf.fcf_yield,
            short_percent=short_pct,
        ))
    return rows


def _fmt_billions(val) -> str:
    if val is None:
        return "N/A"
    try:
        f = float(val)
        if abs(f) >= 1e9:
            return f"${f / 1e9:.2f}B"
        if abs(f) >= 1e6:
            return f"${f / 1e6:.1f}M"
        return f"${f:,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    try:
        return f"{float(val) * 100:.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_price(val) -> str:
    if val is None:
        return "N/A"
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return "N/A"
