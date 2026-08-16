from pathlib import Path
import json
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_quant_skills_v8_repository_contract():
    for name in (
        "SKILL.md",
        "README.md",
        "README.en.md",
        "LICENSE",
        "skill.json",
        "agents/openai.yaml",
        "agents/cursor-rule.mdc",
        "agents/portable-loader.md",
        "references/api_guide.md",
        "references/buffett_methodology.md",
        "scripts/build.py",
        "scripts/test.py",
        "scripts/portfolio.py",
        "scripts/feasibility.py",
        "scripts/v9_backtest.py",
        "scripts/us_strategy.py",
        "scripts/render_soft_report.py",
        "scripts/reporting.py",
    ):
        assert (ROOT / name).is_file(), name

    skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(skill_text.split("---", 2)[1])
    assert frontmatter["name"] == "build-Q44"
    assert frontmatter["license"] == "GPL-3.0-only"
    assert frontmatter["metadata"]["repository"] == "skill-buffett-moat-screener"
    assert set(frontmatter["quantSkills"]["platforms"]) == {
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
    }
    assert "使用此 skill" in frontmatter["description"] or "Use when" in frontmatter["description"]
    assert "A 股" in skill_text
    assert "research_candidate" in skill_text
    assert "不生成订单" in skill_text
    assert "retrospective_diagnostic" in skill_text
    assert "美股" in skill_text
    for stale in ("港股", "13F", "holdings_ledger"):
        assert stale not in skill_text


def test_manifest_and_runtime_requirements_are_current():
    manifest = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "build-Q44"
    assert manifest["version"] == "9.4.0"
    assert manifest["entrypoint"] == "scripts.build:run"
    assert manifest["license"] == "GPL-3.0-only"
    assert manifest["metadata"]["organization"] == "QuantSkills"
    assert set(manifest["platforms"]) == {
        "claude-code",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
    }

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "panda_data==0.0.12" in requirements


def test_community_readmes_license_and_runtime_adapters():
    readme_zh = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    openai = yaml.safe_load((ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    cursor = (ROOT / "agents" / "cursor-rule.mdc").read_text(encoding="utf-8")
    portable = (ROOT / "agents" / "portable-loader.md").read_text(encoding="utf-8")

    assert "[English](README.en.md)" in readme_zh
    assert "QuantSkills Community Project" in readme_zh
    assert "[简体中文](README.md)" in readme_en
    assert "not official, certified, verified, endorsed" in readme_en
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    assert openai["interface"]["default_prompt"].startswith("Use $build-Q44")
    assert "SKILL.md" in cursor
    assert "Hermes" in portable and "OpenClaw" in portable


def test_removed_cross_market_and_experiment_products_are_absent():
    removed = (
        "scripts/coverage.py",
        "scripts/cross_market_validation.py",
        "scripts/experiment.py",
        "scripts/holdings_analytics.py",
        "scripts/holdings_validation.py",
        "scripts/portfolio_data.py",
        "scripts/dashboard_model.py",
        "scripts/dashboard_charts.py",
        "scripts/render_html.py",
        "scripts/render_preview.py",
        "生产产物/validation_dashboard.html",
        ".playwright-cli",
    )
    assert not [name for name in removed if (ROOT / name).exists()]


def test_production_file_is_v8_or_immutable_v7_baseline_until_migrated():
    files = list((ROOT / "生产产物").glob("*.parquet"))
    if not files:
        return
    import pandas as pd

    frame = pd.read_parquet(files[0])
    versions = set(frame["data_version"].astype(str))
    assert versions in ({"7.0.0"}, {"8.0.0"}, {"9.4.0"})
    if versions == {"7.0.0"}:
        baseline = pd.read_parquet(ROOT / "validation" / "v7_baseline" / "database_v7.parquet")
        pd.testing.assert_frame_equal(frame, baseline)
    assert set(frame["schema_version"]) == {"3.0.0"}
    assert frame["target_id"].str.match(
        r"^(\d{6}\.(SH|SZ|BJ)|CASH\.CNY|UNIVERSE\.ALL_A|Q44-BUFFETT-(?:A-SHARE|A-ROSTER|US-ROSTER)(?:-V8|-V9)?(?:-VALIDATION)?)$"
    ).all()
    assert set(frame["result_type"]) == {
        "buffett_research_candidate",
        "portfolio_target_weight",
        "portfolio_summary",
        "strategy_validation",
        "qualitative_review",
        "portfolio_state_transition",
        "universe_summary",
    }


def test_repository_does_not_embed_credentials():
    for path in ROOT.rglob("*"):
        if path.resolve() == Path(__file__).resolve():
            continue
        if not path.is_file() or path.suffix.lower() in {".mp4", ".png", ".parquet", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert ("PANDA_DATA_PASSWORD" + "=") not in text
        assert ("PANDA_DATA_USERNAME" + "=") not in text


def test_shared_secure_worker_uses_v6_environment_contract():
    worker = ROOT / "secure_panda_worker.py"
    assert worker.is_file()
    text = worker.read_text(encoding="utf-8")
    assert '"symbols": ["600519.SH"]' in text
    assert "consume_environment_credentials" in text
    assert "import scripts.panda_adapter as panda_adapter" in text
    assert "import scripts.build as build" in text


def test_build_cli_can_be_executed_directly():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
