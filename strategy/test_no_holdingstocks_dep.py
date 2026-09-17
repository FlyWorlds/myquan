"""Phase 1A：strategy 生产代码不得依赖 holdingStocks；板规单元测试。"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STRATEGY = _ROOT / "strategy"


def _strategy_prod_py_files() -> list[Path]:
    """排除 test_*.py（验收范围：生产模块零反向依赖）。"""
    out: list[Path] = []
    for p in _STRATEGY.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p.name.startswith("test_"):
            continue
        out.append(p)
    return out


def _imports_holding_stocks(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "holdingStocks" or alias.name.startswith("holdingStocks."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "holdingStocks" or mod.startswith("holdingStocks."):
                hits.append(mod)
    return hits


class TestNoStrategyHoldingStocksImport(unittest.TestCase):
    def test_zero_holding_stocks_imports(self) -> None:
        bad: list[str] = []
        for path in _strategy_prod_py_files():
            for hit in _imports_holding_stocks(path):
                bad.append(f"{path.relative_to(_ROOT)}: {hit}")
        self.assertEqual(bad, [], msg="strategy → holdingStocks 反向依赖未清零:\n" + "\n".join(bad))


class TestBoardRules(unittest.TestCase):
    def test_limit_pct_mainboard_vs_chi_next(self) -> None:
        from strategy.board_rules import limit_down_pct_of, limit_up_pct_of, sina_of

        self.assertEqual(limit_down_pct_of("600552"), 0.10)
        self.assertEqual(limit_up_pct_of("300001"), 0.20)
        self.assertEqual(limit_up_pct_of("688001"), 0.20)
        self.assertEqual(sina_of("600552"), "sh600552")
        self.assertEqual(sina_of("000001"), "sz000001")

    def test_research_watchlist_nonempty(self) -> None:
        from strategy.watch_universe import WATCHLIST, research_watchlist

        rows = research_watchlist()
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(len(rows), len(WATCHLIST))
        codes = {str(r["code"]) for r in rows}
        self.assertIn("600552", codes)
        self.assertIn("600330", codes)


if __name__ == "__main__":
    unittest.main()
