import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_required_entrypoints_exist(self):
        required = [
            "SKILL.md", "README.md", "README.en.md", "LICENSE", "HERMES.md",
            "agents/openai.yaml", "agents/cursor-rule.mdc", "agents/portable-loader.md",
        ]
        self.assertEqual([path for path in required if not (ROOT / path).is_file()], [])

    def test_skill_metadata_matches_adapters(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("platforms: [claude-code, codex, openclaw, cursor, hermes]", skill)
        self.assertIn("status: draft", skill)
        self.assertIn("validation_level: listed", skill)
        self.assertIn("requires: []", skill)

    def test_license_is_complete_gplv3(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(license_text), 35000)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)


if __name__ == "__main__":
    unittest.main()
