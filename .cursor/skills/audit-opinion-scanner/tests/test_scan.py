"""Integration-style tests for the scan pipeline (scripts/scan.py)."""

import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import scan


class TestResolveQuarter:
    def test_valid_format(self):
        q = scan._resolve_quarter("2024q4")
        assert q == "2024q4"

    def test_default_returns_valid_format(self):
        q = scan._resolve_quarter(None)
        assert "q" in q
        assert len(q) == 6

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            scan._resolve_quarter("2024-Q4")

    def test_invalid_quarter_number(self):
        with pytest.raises(ValueError):
            scan._resolve_quarter("2024q5")


class TestValidateQuarter:
    def test_valid(self):
        scan._validate_quarter("2024q1")
        scan._validate_quarter("2024Q4")  # uppercase ok

    def test_invalid(self):
        with pytest.raises(ValueError):
            scan._validate_quarter("2024q5")
        with pytest.raises(ValueError):
            scan._validate_quarter("24q1")
        with pytest.raises(ValueError):
            scan._validate_quarter("2024q")


class TestResolveQuarters:
    def test_both_provided(self):
        s, e = scan._resolve_quarters("2024q1", "2024q4", "2024q3")
        assert s == "2024q1"
        assert e == "2024q4"

    def test_only_start(self):
        s, e = scan._resolve_quarters("2024q2", None, "2024q3")
        assert s == "2024q2"
        assert e == "2024q2"

    def test_only_end(self):
        s, e = scan._resolve_quarters(None, "2024q4", "2024q3")
        assert s == "2024q4"
        assert e == "2024q4"

    def test_default(self):
        s, e = scan._resolve_quarters(None, None, "2024q3")
        assert s == "2024q3"
        assert e == "2024q3"

    def test_invalid_start_raises(self):
        with pytest.raises(ValueError):
            scan._resolve_quarters("bad", None, "2024q3")


class TestBuildClassified:
    def test_basic_classification(self, sample_opinions_df, universe_symbols):
        name_map = {
            "000001.SZ": "平安银行",
            "000002.SZ": "万科A",
            "600519.SH": "贵州茅台",
            "300750.SZ": "宁德时代",
        }
        df = scan._build_classified(
            opinions_df=sample_opinions_df,
            universe_symbols=universe_symbols,
            include_internal_control=False,
            name_map=name_map,
        )
        assert not df.empty
        assert "risk_level" in df.columns
        assert "risk_label" in df.columns
        assert "name" in df.columns

        # 300750.SZ has qualified_opinion → should be high risk
        row = df[df["symbol"] == "300750.SZ"]
        assert len(row) == 1
        from scripts.rules import RISK_HIGH
        assert row["risk_level"].iloc[0] == RISK_HIGH

        # internal_control rows should be excluded by default
        assert "internal_control" not in df["audit_type"].values

    def test_include_internal_control(self, sample_opinions_df, universe_symbols):
        name_map = {}
        df = scan._build_classified(
            opinions_df=sample_opinions_df,
            universe_symbols=universe_symbols,
            include_internal_control=True,
            name_map=name_map,
        )
        assert "internal_control" in df["audit_type"].values

    def test_universe_filter(self, sample_opinions_df):
        """Symbols not in universe should be excluded."""
        name_map = {}
        df = scan._build_classified(
            opinions_df=sample_opinions_df,
            universe_symbols=["000001.SZ", "600519.SH"],  # only 2 of 4
            include_internal_control=False,
            name_map=name_map,
        )
        assert set(df["symbol"].unique()) == {"000001.SZ", "600519.SH"}

    def test_empty_opinions(self, universe_symbols):
        df = pd.DataFrame(columns=["symbol", "quarter", "date", "agency", "audit_type", "opinion"])
        result = scan._build_classified(df, universe_symbols, False, {})
        assert result.empty


class TestEndToEnd:
    """End-to-end pipeline test using synthetic data with mocked external APIs."""

    @pytest.fixture
    def mock_opinions(self):
        """Synthetic audit opinions covering standard + non-standard types."""
        return pd.DataFrame({
            "symbol": ["000001.SZ", "000002.SZ", "600519.SH", "300750.SZ", "000858.SZ"],
            "quarter": ["2024q4"] * 5,
            "date": ["20250430"] * 5,
            "agency": ["安永华明"] * 5,
            "audit_type": ["financial_statements"] * 5,
            "opinion": [
                "unqualified_opinion",
                "unqualified_opinion_with_emphasis",
                "unqualified_opinion",
                "qualified_opinion",
                "adverse_opinion",
            ],
        })

    @pytest.fixture
    def mock_weights(self):
        return pd.DataFrame({
            "index_symbol": ["000300.SH"] * 5,
            "date": ["20250401"] * 5,
            "stock_symbol": ["000001.SZ", "000002.SZ", "600519.SH", "300750.SZ", "000858.SZ"],
            "weight": [0.05, 0.04, 0.06, 0.07, 0.03],
        })

    @pytest.fixture
    def mock_name_map(self):
        return {
            "000001.SZ": "平安银行",
            "000002.SZ": "万科A",
            "600519.SH": "贵州茅台",
            "300750.SZ": "宁德时代",
            "000858.SZ": "五粮液",
        }

    def test_full_pipeline(self, mock_opinions, mock_weights, mock_name_map, monkeypatch):
        """End-to-end: opinions → universe filter → classify → summary → output CSV+MD."""
        import scripts.data as data_mod
        import scripts.universe as uni_mod

        # Mock external dependencies
        monkeypatch.setattr(data_mod, "load_audit_opinion",
                           lambda *a, **kw: mock_opinions)
        monkeypatch.setattr(data_mod, "load_index_weights",
                           lambda *a, **kw: mock_weights)
        monkeypatch.setattr(data_mod, "load_stock_names",
                           lambda syms: mock_name_map)
        monkeypatch.setattr(data_mod, "get_last_trade_date",
                           lambda ex="SH": "20250401")
        monkeypatch.setattr(data_mod, "init_panda_data", lambda: None)

        symbols = uni_mod.filter_universe(mock_weights)

        # Run the classification pipeline (steps 5-7 of scan.main)
        classified = scan._build_classified(
            opinions_df=mock_opinions,
            universe_symbols=symbols,
            include_internal_control=False,
            name_map=mock_name_map,
        )

        # Verify classification
        from scripts.rules import RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL
        assert len(classified) == 5
        assert classified["risk_level"].tolist() == [RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW, RISK_LOW]

        # Verify all output columns present
        for col in ["risk_level", "risk_label", "name"]:
            assert col in classified.columns
        assert not classified["name"].isna().all()

        # Write CSV + MD to temp dir
        import scripts.report as report_mod
        import scripts.rules as rules_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "audit_risk_2024q4.csv"
            md_path = Path(tmpdir) / "audit_risk_2024q4.md"
            report_mod.write_csv(classified, str(csv_path))
            report_mod.write_markdown(classified, str(md_path), quarter="2024q4",
                                      meta=rules_mod.summarize(classified))
            assert csv_path.exists()
            assert md_path.exists()
            # CSV should contain all 5 rows
            result = pd.read_csv(csv_path, encoding="utf-8-sig")
            assert len(result) == 5
            # MD should mention the quarter
            md_text = md_path.read_text()
            assert "2024q4" in md_text

    def test_empty_opinions_handled(self, monkeypatch):
        """Pipeline handles empty audit opinion data gracefully."""
        import scripts.data as data_mod

        monkeypatch.setattr(data_mod, "init_panda_data", lambda: None)
        monkeypatch.setattr(data_mod, "load_audit_opinion",
                           lambda *a, **kw: pd.DataFrame(
                               columns=["symbol", "quarter", "date", "agency", "audit_type", "opinion"]))
        monkeypatch.setattr(data_mod, "get_last_trade_date", lambda ex="SH": "20250401")

        df = data_mod.load_audit_opinion("2024q4", "2024q4")
        result = scan._build_classified(df, [], False, {})
        assert result.empty
        assert "risk_level" in result.columns  # schema preserved even when empty

    def test_unknown_opinion_warning(self, mock_name_map):
        """Unknown opinion values should be classified as unknown, not crash."""
        df = pd.DataFrame({
            "symbol": ["000001.SZ"],
            "quarter": ["2024q4"],
            "date": ["20250430"],
            "agency": ["某事务所"],
            "audit_type": ["financial_statements"],
            "opinion": ["some_new_opinion_type_never_seen"],
        })
        result = scan._build_classified(df, ["000001.SZ"], False, mock_name_map)
        assert len(result) == 1
        from scripts.rules import RISK_UNKNOWN
        assert result["risk_level"].iloc[0] == RISK_UNKNOWN
        assert result["risk_label"].iloc[0]  # not empty
