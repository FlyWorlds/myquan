"""因子5公开帖→主题候选池的离线回归测试。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from strategy import get_factor
from strategy.serenity_factor5 import active_theme_signals, build_candidates, write_snapshot


class Factor5SerenityTests(unittest.TestCase):
    def _posts_fixture(self, directory: Path) -> Path:
        path = directory / "posts.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "created_at", "text", "url"])
            writer.writeheader()
            writer.writerow(
                {
                    "id": "before-close",
                    "created_at": "2026-08-14T06:30:00+00:00",
                    "text": "CPO optical component demand is improving.",
                    "url": "https://x.example/before-close",
                }
            )
            writer.writerow(
                {
                    "id": "p0",
                    "created_at": "2026-08-15T09:00:00+00:00",
                    "text": (
                        "CPO supply remains tight: optical component capacity is the "
                        "AI networking bottleneck."
                    ),
                    "url": "https://x.example/p0",
                }
            )
            writer.writerow(
                {
                    "id": "p1",
                    "created_at": "2026-08-16T09:00:00+00:00",
                    "text": (
                        "High conviction photonics CPO bottleneck: optical laser capacity "
                        "is scarce and hyperscaler demand is ramping."
                    ),
                    "url": "https://x.example/p1",
                }
            )
            writer.writerow(
                {
                    "id": "p2",
                    "created_at": "2026-08-16T10:00:00+00:00",
                    "text": "I would sell $FAKE because the thesis is broken.",
                    "url": "https://x.example/p2",
                }
            )
        return path

    def test_factor5_is_registered_with_serenity_provenance(self) -> None:
        factor = get_factor("factor5")
        self.assertTrue(factor.implemented)
        self.assertEqual(factor.meta["source_skill"], "serenity-research-model")

    def test_forward_theme_maps_to_a_share_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = self._posts_fixture(Path(tmp))
            candidates = build_candidates(
                posts,
                asof="2026-08-16",
            )
            saturday_candidates = build_candidates(posts, asof="2026-08-15")
            no_new_post_candidates = build_candidates(posts, asof="2026-08-18")
        self.assertTrue(candidates)
        self.assertTrue(all(row["theme"] == "photonics-cpo" for row in candidates))
        self.assertEqual(len(candidates), 2)
        self.assertIn("300308", {row["code"] for row in candidates})
        self.assertTrue(all(row["source_post_count"] == 2 for row in candidates))
        self.assertTrue(all(row["source_post_count"] == 1 for row in saturday_candidates))
        self.assertFalse(no_new_post_candidates)

    def test_snapshot_has_auditable_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = write_snapshot(
                root / "picks.csv",
                posts_path=self._posts_fixture(root),
                asof="2026-08-16",
            )
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(rows)
            self.assertIn("source_claims", rows[0])
            self.assertEqual(rows[0]["source_skill"], "serenity-research-model")
            self.assertTrue(output.with_suffix(".json").exists())

    def test_weekend_window_starts_after_last_a_share_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp) / "posts.csv"
            with posts.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["created_at", "text"])
                writer.writeheader()
                writer.writerow(
                    {
                        "created_at": "2026-08-14T06:59:00+00:00",  # 14:59 Shanghai
                        "text": "CPO is a high conviction AI networking bottleneck.",
                    }
                )
                writer.writerow(
                    {
                        "created_at": "2026-08-14T07:01:00+00:00",  # 15:01 Shanghai
                        "text": "CPO capacity is a high conviction AI networking bottleneck.",
                    }
                )
            signals = active_theme_signals(
                posts,
                asof="2026-08-16T22:00:00+08:00",
                post_limit=10,
            )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["created_at"], "2026-08-14")


if __name__ == "__main__":
    unittest.main()
