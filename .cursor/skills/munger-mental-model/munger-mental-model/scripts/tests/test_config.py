"""
Tests for config.py configuration module.
Verifies environment variable loading, constants, and credential management.
"""

import os
import pytest
from config import (
    DATA_VERSION,
    DIM_KEYS,
    VERDICTS,
    FINA_FIELDS,
    pass_threshold,
    pledge_max,
    ir_months,
    get_credentials,
)


class TestConstants:
    """Test configuration constants."""

    def test_data_version(self):
        """DATA_VERSION is literal 'real-v1'."""
        assert DATA_VERSION == "real-v1"
        assert isinstance(DATA_VERSION, str)

    def test_dim_keys(self):
        """DIM_KEYS is exactly ('fin', 'comp', 'incentive', 'psych', 'neg')."""
        assert DIM_KEYS == ("fin", "comp", "incentive", "psych", "neg")
        assert isinstance(DIM_KEYS, tuple)

    def test_verdicts(self):
        """VERDICTS is frozenset {'pass', 'fail', 'veto', 'insufficient_data'}."""
        assert VERDICTS == frozenset({"pass", "fail", "veto", "insufficient_data"})
        assert isinstance(VERDICTS, frozenset)

    def test_fina_fields_exists(self):
        """FINA_FIELDS is a dict mapping logical to SDK field names."""
        assert isinstance(FINA_FIELDS, dict)
        assert len(FINA_FIELDS) > 0  # Non-empty mapping


class TestEnvThresholds:
    """Test environment variable threshold loading."""

    def test_pass_threshold_default(self):
        """pass_threshold() returns 60.0 when MUNGER_PASS_THRESHOLD not set."""
        os.environ.pop("MUNGER_PASS_THRESHOLD", None)
        assert pass_threshold() == 60.0

    def test_pass_threshold_env(self):
        """pass_threshold() reads from MUNGER_PASS_THRESHOLD env var."""
        os.environ["MUNGER_PASS_THRESHOLD"] = "75.5"
        assert pass_threshold() == 75.5
        os.environ.pop("MUNGER_PASS_THRESHOLD")

    def test_pledge_max_default(self):
        """pledge_max() returns 0.50 when MUNGER_PLEDGE_MAX not set."""
        os.environ.pop("MUNGER_PLEDGE_MAX", None)
        assert pledge_max() == 0.50

    def test_pledge_max_env(self):
        """pledge_max() reads from MUNGER_PLEDGE_MAX env var."""
        os.environ["MUNGER_PLEDGE_MAX"] = "0.65"
        assert pledge_max() == 0.65
        os.environ.pop("MUNGER_PLEDGE_MAX")

    def test_ir_months_default(self):
        """ir_months() returns 12 when MUNGER_IR_MONTHS not set."""
        os.environ.pop("MUNGER_IR_MONTHS", None)
        assert ir_months() == 12

    def test_ir_months_env(self):
        """ir_months() reads from MUNGER_IR_MONTHS env var."""
        os.environ["MUNGER_IR_MONTHS"] = "24"
        assert ir_months() == 24
        os.environ.pop("MUNGER_IR_MONTHS")


class TestCredentials:
    """Test credential loading from environment."""

    def test_get_credentials_success(self):
        """get_credentials() returns (username, password) tuple from env vars."""
        os.environ["PANDA_DATA_USERNAME"] = "testuser"
        os.environ["PANDA_DATA_PASSWORD"] = "testpass"
        username, password = get_credentials()
        assert username == "testuser"
        assert password == "testpass"
        os.environ.pop("PANDA_DATA_USERNAME")
        os.environ.pop("PANDA_DATA_PASSWORD")

    def test_get_credentials_missing_username(self):
        """get_credentials() raises RuntimeError if PANDA_DATA_USERNAME not set."""
        os.environ.pop("PANDA_DATA_USERNAME", None)
        os.environ["PANDA_DATA_PASSWORD"] = "testpass"
        with pytest.raises(RuntimeError):
            get_credentials()
        os.environ.pop("PANDA_DATA_PASSWORD")

    def test_get_credentials_missing_password(self):
        """get_credentials() raises RuntimeError if PANDA_DATA_PASSWORD not set."""
        os.environ["PANDA_DATA_USERNAME"] = "testuser"
        os.environ.pop("PANDA_DATA_PASSWORD", None)
        with pytest.raises(RuntimeError):
            get_credentials()
        os.environ.pop("PANDA_DATA_USERNAME")

    def test_get_credentials_both_missing(self):
        """get_credentials() raises RuntimeError if both env vars not set."""
        os.environ.pop("PANDA_DATA_USERNAME", None)
        os.environ.pop("PANDA_DATA_PASSWORD", None)
        with pytest.raises(RuntimeError):
            get_credentials()
