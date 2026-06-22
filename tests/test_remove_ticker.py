"""
Tests for the remove-ticker path (main._filter_context and main._remove_ticker).

Run: python -m unittest tests.test_remove_ticker
"""

import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from models.report import (  # noqa: E402
    NewsSection,
    PeerRow,
    ReportContext,
    ShortData,
    TickerRatings,
)


def _make_context() -> ReportContext:
    """A minimal two-ticker context (NVDA, AAPL) touching every per-ticker field."""
    return ReportContext(
        generated_at="2026-06-22",
        watchlist_symbols=["NVDA", "AAPL"],
        ratings=[
            TickerRatings("NVDA", "NVIDIA", 100.0, [], "rationale"),
            TickerRatings("AAPL", "Apple", 200.0, [], "rationale"),
        ],
        news=NewsSection([], [], [], [], "summary"),
        financials=[],
        geopolitical_themes=[],
        geopolitical_summary="",
        earnings_events=[],
        insider_transactions={"NVDA": [], "AAPL": []},
        short_data={"NVDA": ShortData(1.0, 1.0, 1.0, "2026-06-22")},
        price_history={"NVDA": [], "AAPL": []},
        peer_table=[
            PeerRow("NVDA", "NVIDIA", 100.0, None, None, None, None, None, None, None, None, None),
            PeerRow("AAPL", "Apple", 200.0, None, None, None, None, None, None, None, None, None),
        ],
        supply_chain_detail={"NVDA": {"upstream": []}, "AAPL": {"upstream": []}},
    )


class FilterContextTests(unittest.TestCase):
    def test_removes_symbol_from_all_per_ticker_collections(self):
        ctx = main._filter_context(_make_context(), "NVDA")

        self.assertEqual(ctx.watchlist_symbols, ["AAPL"])
        self.assertEqual([r.symbol for r in ctx.ratings], ["AAPL"])
        self.assertEqual([p.symbol for p in ctx.peer_table], ["AAPL"])
        self.assertNotIn("NVDA", ctx.insider_transactions)
        self.assertNotIn("NVDA", ctx.short_data)
        self.assertNotIn("NVDA", ctx.price_history)
        self.assertNotIn("NVDA", ctx.supply_chain_detail)

    def test_keeps_other_symbols_intact(self):
        ctx = main._filter_context(_make_context(), "NVDA")
        self.assertIn("AAPL", ctx.watchlist_symbols)
        self.assertIn("AAPL", ctx.insider_transactions)
        self.assertIn("AAPL", ctx.supply_chain_detail)

    def test_is_case_insensitive(self):
        ctx = main._filter_context(_make_context(), "nvda")
        self.assertEqual(ctx.watchlist_symbols, ["AAPL"])


class RemoveTickerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.config_path = self.tmp / "stocks.json"
        self.config_path.write_text(json.dumps({
            "tickers": [
                {"symbol": "NVDA", "name": "NVIDIA", "upstream": [], "downstream": []},
                {"symbol": "AAPL", "name": "Apple", "upstream": ["NVDA"], "downstream": []},
            ],
            "supply_chain_detail": {"NVDA": {"upstream": []}, "AAPL": {"upstream": []}},
        }))
        self.output_path = self.tmp / "index.html"
        # Point the module's context cache at a temp pickle
        self._orig_cache = main._CONTEXT_CACHE
        main._CONTEXT_CACHE = self.tmp / ".last_context.pkl"
        with main._CONTEXT_CACHE.open("wb") as f:
            pickle.dump(_make_context(), f)

    def tearDown(self):
        main._CONTEXT_CACHE = self._orig_cache
        self._tmp.cleanup()

    def _config(self) -> dict:
        return json.loads(self.config_path.read_text())

    def test_drops_ticker_and_supply_chain_detail(self):
        main._remove_ticker(self.config_path, "NVDA", str(self.output_path), github_repo=None)
        config = self._config()
        self.assertEqual([t["symbol"] for t in config["tickers"]], ["AAPL"])
        self.assertNotIn("NVDA", config["supply_chain_detail"])

    def test_leaves_reference_in_other_tickers_supply_lists(self):
        main._remove_ticker(self.config_path, "NVDA", str(self.output_path), github_repo=None)
        aapl = next(t for t in self._config()["tickers"] if t["symbol"] == "AAPL")
        self.assertIn("NVDA", aapl["upstream"])

    def test_rerenders_html_without_removed_tab(self):
        main._remove_ticker(self.config_path, "NVDA", str(self.output_path), github_repo=None)
        html = self.output_path.read_text()
        self.assertIn('data-symbol="AAPL"', html)
        self.assertNotIn('data-symbol="NVDA"', html)

    def test_absent_symbol_is_noop(self):
        main._remove_ticker(self.config_path, "TSLA", str(self.output_path), github_repo=None)
        self.assertEqual([t["symbol"] for t in self._config()["tickers"]], ["NVDA", "AAPL"])
        self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
