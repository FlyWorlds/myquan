import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class SkillDeclarationTests(unittest.TestCase):
    def test_repository_and_frontmatter_metadata(self):
        self.assertEqual(ROOT.name, "skill-hk-us-consensus-revision-radar")
        content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        for expected in (
            "name: skill-hk-us-consensus-revision-radar",
            "organization: QuantSkills",
            "repository: skill-hk-us-consensus-revision-radar",
            "project_type: skill",
            "collection: consensus-intelligence",
        ):
            self.assertIn(expected, content)

    def test_skill_declares_source_parameters_limits_and_status(self):
        combined = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "README.md", "README.en.md")
        )
        for expected in (
            "PandaData",
            "Community Project",
            "data source",
            "known limitations",
            "risk boundaries",
            "PANDADATA_USERNAME",
            "PANDADATA_PASSWORD",
            "not been reviewed or endorsed",
        ):
            self.assertIn(expected.lower(), combined.lower())
        self.assertNotRegex(
            combined.lower(),
            r"quantskills official|official quantskills|certified by|production-ready",
        )

    def test_skill_documents_safe_visible_credential_window(self):
        content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("visible platform login window", content)
        self.assertIn("parent Codex/terminal process", content)
        self.assertIn("Never request or accept a password in chat", content)
        self.assertIn("optional automation", content)
        self.assertIn("desktop-capable session", content)
        self.assertIn("11-digit mainland mobile username", content)
        self.assertIn("requested", content)

        for expected in (
            "key-findings brief",
            "data-completeness block",
            "reduced-motion",
            "Never render missing numeric values as zero",
        ):
            self.assertIn(expected, content)

    def test_skill_requires_identity_fallback_evidence_and_method_disclosure(self):
        combined = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in (
                "SKILL.md",
                "references/methodology.md",
                "references/pandadata-api-map.md",
            )
        )
        for expected in (
            "get_hk_detail",
            "get_us_detail",
            "14 calendar days",
            "revision_threshold",
            "aggregate consensus",
            "revision breadth",
            "price match rate",
            "name · symbol",
            "min_recommendations",
            "active ordinary shares",
            "regardless of the overall match rate",
            "recommendation bucket",
        ):
            self.assertIn(expected.lower(), combined.lower())

    def test_task5_event_contracts_declared(self):
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        api_map = (ROOT / "references/pandadata-api-map.md").read_text(encoding="utf-8")
        methodology = (ROOT / "references/methodology.md").read_text(encoding="utf-8")

        for token in (
            "get_stock_dividend_event",
            "get_stock_financial_event",
            "get_stock_dividend_activity",
            "get_stock_financial_activity",
            "get_stock_market_event",
            "get_stock_meeting_event",
            "get_stock_ir_event",
            "get_stock_market_activity",
            "get_stock_meeting_activity",
            "get_stock_ir_activity",
        ):
            self.assertIn(token, skill_text, f"Missing event interface in SKILL: {token}")
            self.assertIn(token, api_map, f"Missing event interface in API map: {token}")

        for token in (
            "--event-past-days",
            "--event-future-days",
            "--event-discovery-days",
            "--no-events",
            "announcement date",
            "execution date",
            "does not affect ranking",
        ):
            self.assertIn(token, skill_text)

        for endpoint in (
            "get_stock_dividend_event",
            "get_stock_market_event",
            "get_stock_meeting_event",
            "get_stock_financial_event",
            "get_stock_ir_event",
            "get_stock_dividend_activity",
            "get_stock_market_activity",
            "get_stock_meeting_activity",
            "get_stock_financial_activity",
            "get_stock_ir_activity",
        ):
            self.assertIn(endpoint, api_map)

        for expected in (
            "`publish_date`",
            "`excute_date`",
            "`info_date`",
            "`start_date`",
            "`end_date`",
            "`is_estimated`",
            "market-symbol-category-event_type-start_date-end_date-title",
            "730-day",
            "30/30",
            "available",
            "partial",
            "unavailable",
            "disabled",
            "announcement discovery",
            "execution date",
            "does not affect ranking",
        ):
            self.assertTrue(
                expected in api_map or expected in methodology or expected in skill_text,
                f"Missing expected declaration: {expected}",
            )

    def test_task4_documents_trajectory_states_and_aggregate_limits_in_chinese(self):
        combined = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "references/methodology.md")
        )
        for expected in (
            "周度、1个月、3个月、6个月、12个月",
            "持续上修", "上修加速", "上修减速", "趋势反转待核验",
            "目标价与评级共振改善", "目标价与评级信号冲突",
            "高分歧待核验", "覆盖变化待核验",
            "评级均值越低代表评级更积极",
            "历史评级均值 − 当前评级均值越大代表评级改善/更积极",
            "有效核心样本 P75", "不改变榜单排序", "不是分析师个人修订",
            "PandaData 聚合数据", "精确历史时间戳", "个人分析师信息",
        ):
            self.assertIn(expected, combined)
        self.assertNotIn("评级变化数值越低代表评级更积极", combined)

    def test_readmes_document_external_open_source_usage_and_boundaries(self):
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")

        for text in (chinese, english):
            for expected in (
                "PandaData",
                "--desktop-login-window",
                "get_last_trade_date",
                "references/pandadata-api-map.md",
                "references/methodology.md",
            ):
                self.assertIn(expected, text)

        for expected in (
            "修订轨迹矩阵",
            "事件仅作解释上下文，不改变排名",
            "不构成投资建议",
        ):
            self.assertIn(expected, chinese)
        for expected in (
            "Revision Trajectory Matrix",
            "Event context is explanatory only and does not change rankings",
            "not investment advice",
        ):
            self.assertIn(expected, english)

    def test_required_files_and_eval_prompts_exist(self):
        for name in (
            "README.md",
            "README.en.md",
            "LICENSE",
            "requirements.txt",
            ".gitignore",
            "evals/evals.json",
            "references/methodology.md",
            "references/pandadata-api-map.md",
            "config/defaults.json",
            "agents/openai.yaml",
            "agents/cursor-rule.mdc",
            "agents/portable-loader.md",
        ):
            self.assertTrue((ROOT / name).is_file(), name)
        eval_text = (ROOT / "evals" / "evals.json").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(re.findall(r'"prompt"\s*:', eval_text)), 4)

    def test_skill_declares_execution_contract_and_ui_metadata(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        ui = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        for expected in (
            "--desktop-login-window",
            "desktop Codex / non-TTY",
            "collapsed by default",
            "JavaScript is unavailable",
            "case-insensitive contains search",
            "trajectory_matrix",
            "Hong Kong and US price match rates",
            "14-day price fallback",
            "event-context availability and windows",
        ):
            self.assertIn(expected, skill)

        for expected in (
            'display_name: "港美股一致预期修订雷达：轨迹矩阵与状态机"',
            'short_description: "修订轨迹矩阵、状态机与可审计 HTML 雷达"',
            "default_prompt:",
            "$skill-hk-us-consensus-revision-radar",
        ):
            self.assertIn(expected, ui)

    def test_community_runtime_adapters_and_gpl_license_are_declared(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cursor = (ROOT / "agents" / "cursor-rule.mdc").read_text(encoding="utf-8")
        hermes = (ROOT / "agents" / "portable-loader.md").read_text(encoding="utf-8")
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        readmes = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("README.md", "README.en.md")
        )

        self.assertIn("license: GPL-3.0-only", skill)
        self.assertIn("../SKILL.md", cursor)
        self.assertIn("../SKILL.md", hermes)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn("GPL-3.0-only", readmes)
        self.assertNotIn("MIT License", readmes)


if __name__ == "__main__":
    unittest.main()
