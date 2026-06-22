from datetime import datetime, timezone
from models.report import ReportContext


def build_digest(ctx: ReportContext, report_url: str = "") -> dict:
    symbols_str = ", ".join(ctx.watchlist_symbols)
    date_str = ctx.generated_at.split(" ")[0]
    subject = f"FinAgent — {date_str} | {symbols_str}"

    bullets = _build_bullets(ctx)

    text = "\n".join(f"• {b}" for b in bullets)
    if len(text) > 500:
        text = text[:497] + "..."

    html = _build_html_email(ctx, bullets, date_str, report_url)

    return {"subject": subject, "text": text, "html": html}


def _build_bullets(ctx: ReportContext) -> list[str]:
    bullets = []

    # Analyst changes
    upgrades, downgrades = [], []
    for tr in ctx.ratings:
        for r in tr.ratings:
            action_lower = (r.action or "").lower()
            if "upgrade" in action_lower:
                upgrades.append(f"{tr.symbol} ({r.firm})")
            elif "downgrade" in action_lower:
                downgrades.append(f"{tr.symbol} ({r.firm})")

    if upgrades or downgrades:
        parts = []
        if upgrades:
            parts.append(f"↑ {', '.join(upgrades[:2])}")
        if downgrades:
            parts.append(f"↓ {', '.join(downgrades[:2])}")
        bullets.append("Ratings: " + "  ".join(parts))
    else:
        bullets.append("Ratings: No upgrades or downgrades today")

    # Upcoming earnings
    soon = sorted(
        [e for e in ctx.earnings_events if e.days_until is not None and 0 <= e.days_until <= 14],
        key=lambda e: e.days_until,
    )
    if soon:
        parts = []
        for e in soon[:3]:
            eps = f"  EPS est. ${e.eps_estimate:.2f}" if e.eps_estimate else ""
            parts.append(f"{e.symbol} in {e.days_until}d ({e.earnings_date}){eps}")
        bullets.append("Earnings: " + " · ".join(parts))
    else:
        bullets.append("Earnings: None within 14 days")

    # Insider buys
    buy_lines = []
    for sym, txns in ctx.insider_transactions.items():
        for t in txns:
            if "purchase" in (t.transaction_type or "").lower() or "P-" in (t.transaction_type or ""):
                val = f"${t.total_value / 1e6:.1f}M" if t.total_value and t.total_value >= 1e6 else (
                    f"${t.total_value:,.0f}" if t.total_value else "")
                buy_lines.append(f"{sym}: {t.reporting_name} {val}")
                if len(buy_lines) >= 2:
                    break
        if len(buy_lines) >= 2:
            break
    if buy_lines:
        bullets.append("Insider buys: " + " · ".join(buy_lines))

    # Top geopolitical theme
    if ctx.geopolitical_themes:
        top = max(ctx.geopolitical_themes, key=lambda t: _risk_sort(t.risk_level))
        bullets.append(f"Geo risk: {top.theme} — {top.risk_level} ({', '.join(top.affected_tickers[:3])})")

    # Flagged watchlist tickers
    if ctx.news.flagged_tickers:
        bullets.append(f"Watch: {', '.join(ctx.news.flagged_tickers[:5])}")

    return bullets


def _build_html_email(ctx: ReportContext, bullets: list[str], date_str: str, report_url: str) -> str:
    # Build analyst ratings rows
    ratings_rows = ""
    for tr in ctx.ratings:
        if not tr.ratings:
            continue
        r = tr.ratings[0]  # most recent
        rating_color = "#16864d" if _is_buy(r.rating) else ("#cc1f1f" if _is_sell(r.rating) else "#d97706")
        pt_str = f"${r.price_target:,.0f}" if r.price_target else "—"
        prev_str = f"← ${r.previous_price_target:,.0f}" if r.previous_price_target else ""
        price_str = f"${tr.current_price:,.2f}" if tr.current_price else "—"

        # Compute upside
        upside_str = ""
        if r.price_target and tr.current_price and tr.current_price > 0:
            upside = (r.price_target - tr.current_price) / tr.current_price * 100
            upside_color = "#16864d" if upside >= 0 else "#cc1f1f"
            upside_str = f"<span style='color:{upside_color};font-size:11px;'>{upside:+.1f}%</span>"

        ratings_rows += f"""
        <tr>
          <td style='padding:8px 12px;font-weight:700;font-size:13px;'>{tr.symbol}</td>
          <td style='padding:8px 12px;color:#566072;font-size:12px;'>{r.firm}</td>
          <td style='padding:8px 12px;font-size:12px;color:#566072;'>{r.analyst}</td>
          <td style='padding:8px 12px;'>
            <span style='background:{"#f0fdf4" if _is_buy(r.rating) else ("#fef2f2" if _is_sell(r.rating) else "#fffbeb")};
                         color:{rating_color};padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;'>
              {r.rating or "—"}
            </span>
          </td>
          <td style='padding:8px 12px;font-size:12px;text-align:right;'>{price_str}</td>
          <td style='padding:8px 12px;font-size:12px;text-align:right;'>{pt_str} <span style='color:#9ca3af;font-size:10px;'>{prev_str}</span></td>
          <td style='padding:8px 12px;text-align:right;'>{upside_str}</td>
        </tr>"""

    # Build news rows (top 5)
    top_news = (ctx.news.direct_news + ctx.news.market_news + ctx.news.macro_news)[:5]
    news_rows = ""
    for item in top_news:
        source_color = "#92400e" if item.source == "WSJ" else "#5b21b6"
        source_bg = "#fef3c7" if item.source == "WSJ" else "#ede9fe"
        tickers_html = "".join(
            f"<span style='background:#f3f4f6;color:#566072;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;margin-left:3px;'>{t}</span>"
            for t in item.relevant_tickers[:3]
        )
        news_rows += f"""
        <tr>
          <td style='padding:8px 12px;border-bottom:1px solid #f3f4f6;'>
            <div style='font-size:12px;font-weight:600;margin-bottom:3px;'>
              <a href='{item.url}' style='color:#1a2330;text-decoration:none;'>{item.title}</a>
            </div>
            <div>
              <span style='background:{source_bg};color:{source_color};padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;'>{item.source}</span>
              <span style='color:#9ca3af;font-size:10px;margin-left:6px;'>{item.published}</span>
              {tickers_html}
            </div>
          </td>
        </tr>"""

    # Bullets for the summary block
    bullets_html = "".join(
        f"<li style='margin-bottom:5px;font-size:13px;color:#374151;'>{b}</li>"
        for b in bullets
    )

    view_button = ""
    if report_url:
        view_button = f"""
        <div style='text-align:center;margin:24px 0 0;'>
          <a href='{report_url}'
             style='background:#0b5cab;color:#fff;padding:10px 24px;border-radius:6px;
                    font-size:13px;font-weight:600;text-decoration:none;display:inline-block;'>
            View Full Report →
          </a>
        </div>"""

    geo_html = ""
    if ctx.geopolitical_themes:
        geo_items = ""
        for theme in ctx.geopolitical_themes[:3]:
            risk_color = {"High": "#cc1f1f", "Medium-High": "#ea580c", "Medium": "#d97706", "Low": "#16864d"}.get(theme.risk_level, "#566072")
            tickers = ", ".join(theme.affected_tickers[:4])
            geo_items += f"""
            <div style='margin-bottom:10px;padding:10px 12px;background:#f4f6f8;border-radius:6px;border-left:3px solid {risk_color};'>
              <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
                <span style='font-size:12px;font-weight:700;color:#1a2330;'>{theme.theme}</span>
                <span style='font-size:10px;font-weight:700;color:{risk_color};margin-left:8px;white-space:nowrap;'>{theme.risk_level}</span>
              </div>
              <div style='font-size:11px;color:#566072;margin-top:2px;'>{tickers}</div>
            </div>"""
        geo_html = f"""
        <div style='margin-bottom:24px;'>
          <div style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:#9ca3af;margin-bottom:10px;'>Geopolitical Risk</div>
          {geo_items}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style='margin:0;padding:0;background:#f4f6f8;font-family:"Roboto",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'>
<div style='max-width:620px;margin:24px auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #dfe3e8;'>

  <!-- Header -->
  <div style='background:#fff;padding:20px 24px;border-bottom:2px solid #0b5cab;'>
    <div style='font-size:20px;font-weight:900;color:#0b5cab;letter-spacing:-0.5px;'>FinAgent</div>
    <div style='font-size:12px;color:#566072;margin-top:3px;'>{date_str} · {", ".join(ctx.watchlist_symbols)}</div>
  </div>

  <div style='padding:20px 24px;'>

    <!-- Summary bullets -->
    <div style='margin-bottom:24px;'>
      <div style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:#9ca3af;margin-bottom:10px;'>Summary</div>
      <ul style='margin:0;padding-left:18px;'>
        {bullets_html}
      </ul>
    </div>

    <!-- Analyst Ratings -->
    <div style='margin-bottom:24px;'>
      <div style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:#9ca3af;margin-bottom:10px;'>Latest Analyst Ratings</div>
      <table style='width:100%;border-collapse:collapse;border:1px solid #dfe3e8;border-radius:6px;overflow:hidden;'>
        <thead>
          <tr style='background:#f4f6f8;'>
            <th style='padding:7px 12px;text-align:left;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Ticker</th>
            <th style='padding:7px 12px;text-align:left;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Firm</th>
            <th style='padding:7px 12px;text-align:left;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Analyst</th>
            <th style='padding:7px 12px;text-align:left;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Rating</th>
            <th style='padding:7px 12px;text-align:right;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Price</th>
            <th style='padding:7px 12px;text-align:right;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>PT</th>
            <th style='padding:7px 12px;text-align:right;font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:0.4px;border-bottom:1px solid #dfe3e8;'>Upside</th>
          </tr>
        </thead>
        <tbody>
          {ratings_rows}
        </tbody>
      </table>
    </div>

    <!-- Top News -->
    <div style='margin-bottom:24px;'>
      <div style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;color:#9ca3af;margin-bottom:10px;'>Top News</div>
      <table style='width:100%;border-collapse:collapse;border:1px solid #dfe3e8;border-radius:6px;overflow:hidden;'>
        <tbody>{news_rows}</tbody>
      </table>
    </div>

    <!-- Geopolitical -->
    {geo_html}

    <!-- View full report button -->
    {view_button}

  </div>

  <!-- Footer -->
  <div style='padding:14px 24px;border-top:1px solid #dfe3e8;background:#f4f6f8;'>
    <p style='margin:0;font-size:11px;color:#9ca3af;'>For informational purposes only. Not investment advice. Generated {ctx.generated_at}.</p>
  </div>

</div>
</body>
</html>"""


def _is_buy(rating: str) -> bool:
    r = (rating or "").lower()
    return any(x in r for x in ["buy", "overweight", "outperform", "strong buy"])


def _is_sell(rating: str) -> bool:
    r = (rating or "").lower()
    return any(x in r for x in ["sell", "underweight", "underperform"])


def _risk_sort(level: str) -> int:
    return {"Low": 0, "Medium": 1, "Medium-High": 2, "High": 3}.get(level, 0)
