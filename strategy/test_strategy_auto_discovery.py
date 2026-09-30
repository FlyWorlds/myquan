"""Strategy auto-discovery：注册表与手工时代一致。"""

from __future__ import annotations

import unittest

# 手工列表时代（commit 前）的正式策略 id
_EXPECTED_IDS = frozenset(
    {
        "strategy1",
        "strategy2",
        "strategy3",
        "strategy4",
        "strategy5",
        "strategy6",
        "strategy7",
        "strategy8",
        "strategy9",
        "strategy12",
        "strategy15",
        "strategy16",
        "strategy16b",
        "strategy17",
    }
)


class TestStrategyAutoDiscovery(unittest.TestCase):
    def test_registry_ids_match_legacy_set(self) -> None:
        import strategy.strategies as plugins
        from strategy.core.strategy_registry import list_strategy_specs

        ids = {s.id for s in list_strategy_specs()}
        self.assertEqual(ids, _EXPECTED_IDS)
        self.assertEqual(set(plugins._DISCOVERED), _EXPECTED_IDS)
        self.assertIn("strategy13", plugins._SKIP_AUTO_IMPORT)
        self.assertNotIn("strategy13", ids)

    def test_default_strategy16_still_marked(self) -> None:
        from strategy.core.strategy_registry import get_strategy_spec

        spec = get_strategy_spec("strategy16")
        self.assertTrue(spec.meta.get("default") is True)

    def test_strategy16b_registered_next_to_strategy16(self) -> None:
        from strategy.core.strategy_registry import get_strategy_spec

        spec = get_strategy_spec("strategy16b")
        self.assertEqual(spec.name, "策略十六B·条件选股")
        self.assertTrue(spec.meta.get("watch_tab") is True)
        self.assertTrue(spec.meta.get("custom_select_ui") is True)


if __name__ == "__main__":
    unittest.main()
