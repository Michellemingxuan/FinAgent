from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnalystRating:
    firm: str
    analyst: str
    rating: str
    previous_rating: Optional[str]
    price_target: Optional[float]
    previous_price_target: Optional[float]
    date: str
    action: str  # e.g. "Maintains", "Upgrades", "Downgrades", "Initiates"


@dataclass
class TickerRatings:
    symbol: str
    name: str
    current_price: Optional[float]
    ratings: list[AnalystRating]
    ai_rationale: str  # Claude-generated paragraph
    error: Optional[str] = None


@dataclass
class NewsItem:
    title: str
    source: str  # "WSJ" or "Yahoo Finance"
    url: str
    published: str
    summary: str
    full_text_available: bool = False
    relevant_tickers: list[str] = field(default_factory=list)  # flagged by Claude


@dataclass
class NewsSection:
    direct_news: list[NewsItem]        # news about holdings
    market_news: list[NewsItem]        # upstream/downstream market news
    macro_news: list[NewsItem]         # macro/sector news
    flagged_tickers: list[str]         # tickers Claude flagged as worth following
    ai_summary: str                    # Claude-generated cross-news narrative
    error: Optional[str] = None


@dataclass
class FinancialMetrics:
    year: str
    revenue: Optional[float]
    gross_profit: Optional[float]
    operating_income: Optional[float]
    net_income: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    net_margin: Optional[float]
    total_assets: Optional[float]
    total_debt: Optional[float]
    cash_and_equivalents: Optional[float]
    free_cash_flow: Optional[float]


@dataclass
class TickerFinancials:
    symbol: str
    name: str
    current_price: Optional[float]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    ev_ebitda: Optional[float]
    debt_to_equity: Optional[float]
    fcf_yield: Optional[float]
    metrics_by_year: list[FinancialMetrics]
    ai_analysis: str  # Claude-generated analysis paragraph
    error: Optional[str] = None


@dataclass
class GeopoliticalTheme:
    theme: str
    affected_tickers: list[str]
    risk_level: str  # "Low", "Medium", "Medium-High", "High"
    ai_analysis: str  # Claude-generated paragraph
    source_headlines: list[str]
    latest_date: str = ""  # Most recent triggering headline date (YYYY-MM-DD)


@dataclass
class QuarterlySnapshot:
    period: str             # "YYYY-MM"
    revenue: Optional[float]
    gross_profit: Optional[float]
    operating_income: Optional[float]
    net_income: Optional[float]
    yoy_revenue_growth: Optional[float] = None   # computed by agent


@dataclass
class EarningsBeat:
    period: str             # "YYYY-MM"
    eps_estimate: Optional[float]
    eps_actual: Optional[float]
    surprise_pct: Optional[float]   # positive = beat


@dataclass
class TickerProduct:
    symbol: str
    name: str
    sector: str
    industry: str
    quarterly_revenue: list[QuarterlySnapshot]
    earnings_history: list[EarningsBeat]
    segments: tuple = field(default_factory=lambda: ([], ""))  # (list[dict], value_driver str)
    # Forward estimate metrics
    revenue_growth: Optional[float] = None       # TTM YoY
    earnings_growth: Optional[float] = None      # TTM YoY
    earnings_quarterly_growth: Optional[float] = None
    gross_margins: Optional[float] = None
    operating_margins: Optional[float] = None
    return_on_equity: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_sales: Optional[float] = None
    eps_forward: Optional[float] = None
    target_mean_price: Optional[float] = None
    current_price: Optional[float] = None
    recommendation: str = ""
    ai_analysis: str = ""                        # Claude narrative
    error: Optional[str] = None


@dataclass
class EarningsEvent:
    symbol: str
    earnings_date: str           # "YYYY-MM-DD" or "YYYY-MM-DD to YYYY-MM-DD" range
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]
    days_until: Optional[int]    # computed: how many days from today


@dataclass
class InsiderTransaction:
    reporting_name: str
    transaction_type: str        # e.g. "P-Purchase", "S-Sale"
    securities_transacted: Optional[float]
    price: Optional[float]
    total_value: Optional[float]  # price * securities_transacted
    transaction_date: str
    filing_date: str


@dataclass
class ShortData:
    short_percent_float: Optional[float]  # short as % of float
    short_percent_outstanding: Optional[float]
    float_shares: Optional[float]
    date: str


@dataclass
class PricePoint:
    date: str
    close: float


@dataclass
class PeerRow:
    symbol: str
    name: str
    current_price: Optional[float]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    ev_ebitda: Optional[float]
    gross_margin: Optional[float]     # most recent year
    revenue_growth: Optional[float]   # YoY from most recent two years
    debt_to_equity: Optional[float]
    fcf_yield: Optional[float]
    short_percent: Optional[float]


@dataclass
class ReportContext:
    generated_at: str
    watchlist_symbols: list[str]
    ratings: list[TickerRatings]
    news: NewsSection
    financials: list[TickerFinancials]
    geopolitical_themes: list[GeopoliticalTheme]
    geopolitical_summary: str
    errors: list[str] = field(default_factory=list)
    earnings_events: list[EarningsEvent] = field(default_factory=list)
    insider_transactions: dict[str, list[InsiderTransaction]] = field(default_factory=dict)  # symbol -> list
    short_data: dict[str, ShortData] = field(default_factory=dict)  # symbol -> ShortData
    price_history: dict[str, list[PricePoint]] = field(default_factory=dict)  # symbol -> list
    peer_table: list[PeerRow] = field(default_factory=list)
    themes: list[dict] = field(default_factory=list)  # from config
    supply_chain_detail: dict = field(default_factory=dict)  # symbol -> {upstream, downstream, supply_chain_summary}
    product_analysis: list["TickerProduct"] = field(default_factory=list)
