"""
FinAgent — entry point.

Usage:
  python main.py                            # generate full report + deliver
  python main.py --section analyst          # ratings only (faster test)
  python main.py --test-delivery            # send digest using last generated report (no re-run)
  python main.py --preview-email            # write email HTML to output/email_preview.html
  python main.py --refresh-supply-chain     # update supply chain relationships in config

Environment variables (see .env.example):
  ANTHROPIC_API_KEY
  WSJ_COOKIE            (optional)
  GITHUB_REPO           (optional, e.g. "username/FinAgent")
  SMTP_USER / SMTP_PASSWORD
  WHATSAPP_APIKEY
"""

import argparse
import json
import logging
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("finagent")

_CONTEXT_CACHE = Path("output/.last_context.pkl")


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        logger.error("Required environment variable %s is not set. See .env.example.", name)
        sys.exit(1)
    return val


def _load_delivery_config() -> dict:
    return {
        "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
        "smtp_user": os.environ.get("SMTP_USER", ""),
        "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
        "whatsapp_apikey": os.environ.get("WHATSAPP_APIKEY", ""),
    }


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    with config_path.open() as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="FinAgent report generator")
    parser.add_argument("--section", choices=["analyst", "news", "financials", "geo", "all"], default="all")
    parser.add_argument("--output", default="output/index.html")
    parser.add_argument("--config", default="config/stocks.json")
    parser.add_argument("--lang", choices=["en", "zh"], default="en", help="Language for AI summaries (en or zh)")
    parser.add_argument(
        "--test-delivery",
        action="store_true",
        help="Send digest using the last cached report context (no report re-run)",
    )
    parser.add_argument(
        "--preview-email",
        action="store_true",
        help="Write email HTML to output/email_preview.html and open in browser",
    )
    parser.add_argument(
        "--refresh-supply-chain",
        action="store_true",
        help="Run SupplyChainAgent for each ticker and update config/stocks.json",
    )
    parser.add_argument(
        "--add-ticker",
        type=str,
        default="",
        help="Add a new ticker to config/stocks.json and run a full report",
    )
    args = parser.parse_args()

    config = _load_config(Path(args.config))

    # ── Add new ticker to config if requested ──────────────────────────
    if args.add_ticker:
        new_sym = args.add_ticker.strip().upper()
        existing = {t["symbol"] for t in config.get("tickers", [])}
        if new_sym in existing:
            logger.info("Ticker %s already in config — skipping add", new_sym)
        else:
            logger.info("Adding new ticker %s to config", new_sym)
            new_entry = {"symbol": new_sym, "name": new_sym, "sector": "", "market": "", "upstream": [], "downstream": []}
            config.setdefault("tickers", []).append(new_entry)
            # Auto-discover supply chain
            anthropic_key_for_sc = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if anthropic_key_for_sc:
                try:
                    from agents.supply_chain_agent import SupplyChainAgent
                    sc_agent = SupplyChainAgent(anthropic_api_key=anthropic_key_for_sc)
                    result = sc_agent.discover(new_sym, new_sym, "")
                    config.setdefault("supply_chain_detail", {})[new_sym] = result
                    new_entry["upstream"] = [r["ticker"] for r in result.get("upstream", [])]
                    new_entry["downstream"] = [r["ticker"] for r in result.get("downstream", [])]
                    logger.info("Supply chain discovered for %s", new_sym)
                except Exception as exc:
                    logger.warning("Supply chain discovery failed for %s: %s", new_sym, exc)
            # Save updated config
            with Path(args.config).open("w") as f:
                json.dump(config, f, indent=2)
            logger.info("Config updated: %s", args.config)

    if args.refresh_supply_chain:
        anthropic_key = _require_env("ANTHROPIC_API_KEY")
        _refresh_supply_chain(Path(args.config), anthropic_key)
        return

    subscribers: dict = config.get("subscribers", {})
    delivery_config = _load_delivery_config()
    github_repo = os.environ.get("GITHUB_REPO", "").strip() or None
    report_url = f"https://{github_repo.split('/')[0]}.github.io/{github_repo.split('/')[1]}/" if github_repo and "/" in github_repo else ""

    # ── Test delivery / email preview (no re-run) ──────────────────────────
    if args.test_delivery or args.preview_email:
        if not _CONTEXT_CACHE.exists():
            logger.error("No cached context found. Run without --test-delivery first to generate a report.")
            sys.exit(1)

        with _CONTEXT_CACHE.open("rb") as f:
            context = pickle.load(f)
        logger.info("Loaded cached report context (%s)", context.generated_at)

        from delivery.digest import build_digest
        digest = build_digest(context, report_url=report_url)

        if args.preview_email:
            preview_path = Path("output/email_preview.html")
            preview_path.write_text(digest["html"], encoding="utf-8")
            logger.info("Email preview written to %s", preview_path)
            import webbrowser
            webbrowser.open(str(preview_path.resolve()))
            return

        if args.test_delivery:
            _run_delivery(delivery_config, subscribers, digest, report_url)
            return

    # ── Full report generation ─────────────────────────────────────────────
    anthropic_key = _require_env("ANTHROPIC_API_KEY")
    fmp_key = os.environ.get("FMP_API_KEY", "").strip()
    wsj_cookie = os.environ.get("WSJ_COOKIE", "").strip() or None

    ticker_configs: list[dict] = config.get("tickers", [])
    report_settings: dict = config.get("report_settings", {})
    themes: list[dict] = config.get("themes", [])
    supply_chain_detail: dict = config.get("supply_chain_detail", {})

    if not ticker_configs:
        logger.error("No tickers defined in config/stocks.json")
        sys.exit(1)

    # Auto-bootstrap supply chain for tickers that have no data yet
    for tc in ticker_configs:
        sym = tc["symbol"]
        if not tc.get("upstream") and sym not in supply_chain_detail:
            logger.info("Auto-discovering supply chain for %s", sym)
            try:
                from agents.supply_chain_agent import SupplyChainAgent
                sc_agent = SupplyChainAgent(anthropic_api_key=anthropic_key)
                result = sc_agent.discover(sym, tc.get("name", sym), tc.get("sector", ""))
                supply_chain_detail[sym] = result
                tc["upstream"] = [r["ticker"] for r in result.get("upstream", [])]
                tc["downstream"] = [r["ticker"] for r in result.get("downstream", [])]
            except Exception as exc:
                logger.warning("Supply chain auto-bootstrap failed for %s: %s", sym, exc)

    if wsj_cookie:
        logger.info("WSJ cookie present — will attempt full article fetches")
    else:
        logger.info("WSJ_COOKIE not set — WSJ headlines only")

    output_path = args.output
    output_dir = str(Path(output_path).parent)

    from agents.orchestrator import Orchestrator
    orchestrator = Orchestrator(
        anthropic_api_key=anthropic_key,
        fmp_api_key=fmp_key,
        wsj_cookie=wsj_cookie,
        report_settings=report_settings,
        delivery_config=delivery_config,
        report_output_dir=output_dir,
        lang=args.lang,
    )

    logger.info("Generating report for %d tickers...", len(ticker_configs))
    context = orchestrator.run(ticker_configs, themes=themes, supply_chain_detail=supply_chain_detail)

    if context.errors:
        logger.warning("Completed with %d errors: %s", len(context.errors), context.errors)

    # Cache context for --test-delivery / --preview-email
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with _CONTEXT_CACHE.open("wb") as f:
        pickle.dump(context, f)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    initial_html = orchestrator.render_html(
        context=context,
        template_dir="templates",
        output_path=output_path,
        github_repo=github_repo,
        archive_dates=[],
    )
    archive_dates = orchestrator.save_archive(initial_html, output_dir, date_str)
    html = orchestrator.render_html(
        context=context,
        template_dir="templates",
        output_path=output_path,
        github_repo=github_repo,
        archive_dates=archive_dates,
    )
    orchestrator.save_archive(html, output_dir, date_str)

    # Generate trigger page
    if github_repo:
        _render_trigger_page(output_dir, github_repo)

    from delivery.digest import build_digest
    digest = build_digest(context, report_url=report_url)
    _run_delivery(delivery_config, subscribers, digest, report_url)

    logger.info("Done. Report: %s", output_path)


def _refresh_supply_chain(config_path: Path, anthropic_key: str) -> None:
    """
    Runs SupplyChainAgent for each ticker in config.
    Updates config['supply_chain_detail'] and config['tickers'][i]['upstream'/'downstream']
    with the ticker symbols from the discovered relationships.
    Saves config back to config_path.
    """
    from agents.supply_chain_agent import SupplyChainAgent

    config = _load_config(config_path)
    sc_agent = SupplyChainAgent(anthropic_api_key=anthropic_key)
    supply_chain_detail: dict = config.get("supply_chain_detail", {})
    ticker_configs: list[dict] = config.get("tickers", [])

    for tc in ticker_configs:
        sym = tc["symbol"]
        name = tc.get("name", sym)
        sector = tc.get("sector", "")
        logger.info("Discovering supply chain for %s", sym)
        result = sc_agent.discover(sym, name, sector)
        supply_chain_detail[sym] = result
        tc["upstream"] = [r["ticker"] for r in result.get("upstream", [])]
        tc["downstream"] = [r["ticker"] for r in result.get("downstream", [])]

    config["supply_chain_detail"] = supply_chain_detail
    config["supply_chain_last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with config_path.open("w") as f:
        json.dump(config, f, indent=2)

    logger.info("Supply chain updated for %d tickers", len(ticker_configs))


def _render_trigger_page(output_dir: str, github_repo: str) -> None:
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    html = env.get_template("trigger.html.j2").render(github_repo=github_repo)
    out = Path(output_dir) / "trigger.html"
    out.write_text(html, encoding="utf-8")
    logger.info("Trigger page written to %s", out)


def _run_delivery(delivery_config: dict, subscribers: dict, digest: dict, report_url: str) -> None:
    delivered_any = False

    email_addresses = [e for e in subscribers.get("email", []) if e and "@" in e and "your@" not in e]
    if email_addresses and delivery_config.get("smtp_user") and "your@" not in delivery_config.get("smtp_user", ""):
        from delivery.email_sender import EmailSender
        sender = EmailSender(
            smtp_host=delivery_config["smtp_host"],
            smtp_port=int(delivery_config.get("smtp_port", 587)),
            username=delivery_config["smtp_user"],
            password=delivery_config.get("smtp_password", ""),
        )
        ok = sender.send(
            to_addresses=email_addresses,
            subject=digest["subject"],
            html_body=digest["html"],
            text_body=digest["text"],
        )
        if ok:
            logger.info("Email delivered to %s", email_addresses)
            delivered_any = True

    wa_key = delivery_config.get("whatsapp_apikey", "").strip()
    wa_numbers = [n for n in subscribers.get("whatsapp", []) if n and "+" in n and "1234" not in n]
    if wa_key and "your_" not in wa_key and wa_numbers:
        from delivery.whatsapp_sender import WhatsAppSender
        ok = WhatsAppSender(api_key=wa_key).send(phone_numbers=wa_numbers, text=digest["text"])
        if ok:
            logger.info("WhatsApp delivered to %s", wa_numbers)
            delivered_any = True

    if not delivered_any:
        logger.info("No delivery channels configured — skipping. Set subscribers in config/stocks.json and credentials in .env")


if __name__ == "__main__":
    main()
