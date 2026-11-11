"""Strategy auto-discovery：注册表与手工时代一致。"""

from __future__ import annotations

import unittest

# 当前注册的正式策略 id
_EXPECTED_IDS = frozenset(
    {
        "strategy1",
        "strategy2",
        "strategy3",
        "strategy4",
        "strategy5",
        "strategy6",
        "strategy7",
        "strategy9",
        "strategy12",
        "strategy17",
        "strategy35",
        "strategy36",
        "strategy37",
        "strategy38",
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

    def test_default_strategy1_is_marked(self) -> None:
        from strategy.core.strategy_registry import get_strategy_spec

        spec = get_strategy_spec("strategy1")
        self.assertTrue(spec.meta.get("default") is True)


if __name__ == "__main__":
    unittest.main()
