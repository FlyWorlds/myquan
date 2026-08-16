from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _skill_frontmatter() -> dict:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, _ = text.split("---", 2)
    return yaml.safe_load(frontmatter)


def test_skill_frontmatter_and_openai_metadata_are_current() -> None:
    metadata = _skill_frontmatter()
    assert set(metadata) == {"name", "description", "license", "metadata", "quantSkills"}
    assert metadata["name"] == "factor-grouped-wrapper"
    description = metadata["description"]
    assert "Pearson IC" in description
    assert "backward" in description.lower()
    assert "forward" in description.lower()

    registry = metadata["quantSkills"]
    assert registry["project_type"] == "skill"
    assert registry["category"] == "factor"
    assert registry["status"] == "active"
    assert registry["validation_level"] == "runnable"
    assert registry["maintainer_type"] == "community"
    assert set(registry["platforms"]) == {
        "codex",
        "claude-code",
        "cursor",
        "openclaw",
    }
    assert registry["requires"] == ["skill-factor-backtest"]

    interface = yaml.safe_load((ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))[
        "interface"
    ]
    assert set(interface) == {"display_name", "short_description", "default_prompt"}
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$factor-grouped-wrapper" in interface["default_prompt"]


def test_documented_repository_contract_files_exist() -> None:
    expected = [
        "README.md",
        "README.en.md",
        "agents/portable-loader.md",
        "agents/cursor-rule.mdc",
        "examples/config.yaml",
        "examples/smoke_config.yaml",
        "pipeline/framework.png",
        "pipeline/pipeline.png",
        "references/input_schema.md",
        "references/output_contract.md",
        "references/algorithm.md",
        "references/factor-backtest-integration.md",
        "references/source_boundary.md",
        "references/validation_notes.md",
        "scripts/make_smoke_fixture.py",
        "scripts/run_smoke.py",
    ]
    missing = [name for name in expected if not (ROOT / name).is_file()]
    assert not missing


def test_community_manifest_declares_status_platforms_and_license() -> None:
    manifest = yaml.safe_load((ROOT / "skill.yml").read_text(encoding="utf-8"))["metadata"]
    assert manifest["organization"] == "QuantSkills"
    assert manifest["repository"] == "skill-factor-grouped-wrapper"
    assert manifest["project_type"] == "skill"
    assert manifest["status"] == "active"
    assert manifest["validation_level"] == "runnable"
    assert manifest["license"] == "GPL-3.0-only"
    assert set(manifest["platforms"]) == {
        "codex",
        "claude-code",
        "cursor",
        "hermes",
        "openclaw",
    }
    assert manifest["maintainer"] == "X-Tech-group"
    assert manifest["maintainer_type"] == "community"


def test_public_docs_state_community_and_runtime_boundaries() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "QUANTSKILLS Community Project" in skill
    assert "not QUANTSKILLS certification" in skill

    for name in ("README.md", "README.en.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert "status: active" in readme
        assert "maintainer: community" in readme
        for platform in ("Codex", "Claude Code", "Cursor", "Hermes", "OpenClaw"):
            assert platform in readme


def test_public_config_uses_realistic_factor_prefixes() -> None:
    config = yaml.safe_load((ROOT / "examples" / "config.yaml").read_text(encoding="utf-8"))
    assert config["selection"]["forward_enabled"] is True
    assert config["data"]["external_factor_bank"]
    prefixes = config["grouping"]["source_prefixes"]
    assert prefixes == ["alpha191_", "alpha101_", "factormad_"]
    assert all("__" not in prefix for prefix in prefixes)
