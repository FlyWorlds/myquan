"""Phase R1 remote paper state tests — memory port + local inventory (no live Postgres)."""

from __future__ import annotations

import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_state.errors import (  # noqa: E402
    DuplicateExecutionError,
    LeaseConflictError,
    RemoteUnavailableError,
    StateConflictError,
    StaleWriterError,
)
from paper_state.local_json import (  # noqa: E402
    LocalJsonPaperStateAdapter,
    holdings_to_full_state,
    state_content_hash,
)
from paper_state.memory import MemoryPaperStateAdapter  # noqa: E402
from paper_state.models import (  # noqa: E402
    AccountSnapshot,
    PaperTrade,
    PositionRecord,
)
from paper_state.port import (  # noqa: E402
    DEFAULT_LEASE_TTL_SEC,
    create_paper_state_port,
)
from paper_state.postgres import PostgresPaperStateAdapter  # noqa: E402


def _seed(port: MemoryPaperStateAdapter, cash: float = 100_000.0) -> None:
    port.replace_full_state(
        holdings_to_full_state(
            {
                "account_cash": cash,
                "paper_equity_base": 300_000.0,
                "account_total_open": 300_000.0,
                "account_total_open_session": "2026-09-21",
                "last_session": "2026-09-21",
                "positions": {
                    "600522": {
                        "qty": 2000,
                        "cost": 37.01,
                        "available": 2000,
                        "buy_time": "2026-09-21 09:35:00",
                        "peak_high": 38.0,
                        "overnight_peak": 37.5,
                        "stop_noted": False,
                        "tp_stage": 0,
                    }
                },
                "realized_today": {},
                "closed_today": {},
                "slot_queue": {"session": "2026-09-21", "freed_at": []},
                "factor_memory": {},
                "factor2": {},
                "portfolio_pool": ["600522"],
                "daily_settlements": {},
            },
            trades_rows=[],
        ),
        require_lease=False,
    )


class PaperRemoteStateR1Tests(unittest.TestCase):
    def test_repository_roundtrip(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        full = port.load_full_state()
        self.assertEqual(full.account.account_cash, 100_000.0)
        self.assertEqual(len(full.open_positions()), 1)
        self.assertEqual(full.open_positions()[0].symbol, "600522")

    def test_position_roundtrip(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        pos = port.list_positions()[0]
        self.assertEqual(pos.qty, 2000)
        self.assertAlmostEqual(float(pos.cost or 0), 37.01)
        self.assertAlmostEqual(float(pos.peak_high or 0), 38.0)
        self.assertAlmostEqual(float(pos.overnight_peak or 0), 37.5)

    def test_trade_append(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        lease = port.acquire_writer_lease(
            account_id="default", writer_id="w1", hostname="win-test"
        )
        acc = port.get_account()
        assert acc is not None
        trade = PaperTrade(
            trade_id="t-buy-1",
            account_id="default",
            symbol="000001",
            side="buy",
            qty=100,
            fill_price=10.0,
            trading_session_date="2026-09-21",
            executed_at="2026-09-21T01:30:00Z",
            execution_id="exec-buy-1",
        )
        pos = PositionRecord(
            account_id="default", symbol="000001", qty=100, cost=10.0, available=0
        )
        new_acc = AccountSnapshot(
            account_id="default",
            account_cash=99_000.0,
            paper_equity_base=300_000.0,
            account_total_open=300_000.0,
            trading_session_date="2026-09-21",
            version=acc.version,
        )
        port.apply_trade_mutation(
            account_id="default",
            trade=trade,
            position=pos,
            account=new_acc,
            expected_account_version=acc.version,
            writer_id=lease.writer_id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        self.assertEqual(len(port.list_trades()), 1)
        self.assertEqual(port.list_trades()[0].trade_id, "t-buy-1")

    def test_trade_idempotency(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        lease = port.acquire_writer_lease(
            account_id="default", writer_id="w1", hostname="win-test"
        )
        acc = port.get_account()
        assert acc is not None
        trade = PaperTrade(
            trade_id="t-idem",
            account_id="default",
            symbol="000001",
            side="buy",
            qty=100,
            fill_price=10.0,
            trading_session_date="2026-09-21",
            executed_at="2026-09-21T01:30:00Z",
            execution_id="exec-idem",
        )
        pos = PositionRecord(account_id="default", symbol="000001", qty=100, cost=10.0)
        new_acc = AccountSnapshot(
            account_id="default",
            account_cash=99_000.0,
            version=acc.version,
        )
        port.apply_trade_mutation(
            account_id="default",
            trade=trade,
            position=pos,
            account=new_acc,
            expected_account_version=acc.version,
            writer_id=lease.writer_id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        with self.assertRaises(DuplicateExecutionError):
            port.apply_trade_mutation(
                account_id="default",
                trade=trade,
                position=pos,
                account=AccountSnapshot(
                    account_id="default", account_cash=98_000.0, version=acc.version + 1
                ),
                expected_account_version=acc.version + 1,
                writer_id=lease.writer_id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
        self.assertEqual(len(port.list_trades()), 1)
        self.assertEqual(port.get_account().account_cash, 99_000.0)

    def test_transaction_rollback_on_conflict(self) -> None:
        """Conflict before mutation leaves prior state intact (atomic semantics)."""
        port = MemoryPaperStateAdapter()
        _seed(port)
        lease = port.acquire_writer_lease(
            account_id="default", writer_id="w1", hostname="win-test"
        )
        before_cash = port.get_account().account_cash
        before_trades = len(port.list_trades())
        with self.assertRaises(StateConflictError):
            port.apply_trade_mutation(
                account_id="default",
                trade=PaperTrade(
                    trade_id="t-bad",
                    account_id="default",
                    symbol="000001",
                    side="buy",
                    qty=100,
                    fill_price=10.0,
                    trading_session_date="2026-09-21",
                    executed_at="2026-09-21T01:30:00Z",
                    execution_id="exec-bad",
                ),
                position=PositionRecord(
                    account_id="default", symbol="000001", qty=100, cost=10.0
                ),
                account=AccountSnapshot(account_id="default", account_cash=1.0),
                expected_account_version=999,  # wrong
                writer_id=lease.writer_id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
        self.assertEqual(port.get_account().account_cash, before_cash)
        self.assertEqual(len(port.list_trades()), before_trades)

    def test_optimistic_concurrency(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        lease = port.acquire_writer_lease(
            account_id="default", writer_id="w1", hostname="win-test"
        )
        acc = port.get_account()
        assert acc is not None
        # First write succeeds and bumps version
        port.apply_trade_mutation(
            account_id="default",
            trade=PaperTrade(
                trade_id="t-oc-1",
                account_id="default",
                symbol="000002",
                side="buy",
                qty=100,
                fill_price=5.0,
                trading_session_date="2026-09-21",
                executed_at="2026-09-21T01:30:00Z",
                execution_id="exec-oc-1",
            ),
            position=PositionRecord(
                account_id="default", symbol="000002", qty=100, cost=5.0
            ),
            account=AccountSnapshot(
                account_id="default", account_cash=99_500.0, version=acc.version
            ),
            expected_account_version=acc.version,
            writer_id=lease.writer_id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        with self.assertRaises(StateConflictError):
            port.apply_trade_mutation(
                account_id="default",
                trade=PaperTrade(
                    trade_id="t-oc-2",
                    account_id="default",
                    symbol="000003",
                    side="buy",
                    qty=100,
                    fill_price=5.0,
                    trading_session_date="2026-09-21",
                    executed_at="2026-09-21T01:31:00Z",
                    execution_id="exec-oc-2",
                ),
                position=PositionRecord(
                    account_id="default", symbol="000003", qty=100, cost=5.0
                ),
                account=AccountSnapshot(account_id="default", account_cash=99_000.0),
                expected_account_version=acc.version,  # stale
                writer_id=lease.writer_id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )

    def test_writer_lease(self) -> None:
        port = MemoryPaperStateAdapter()
        lease = port.acquire_writer_lease(
            account_id="default", writer_id="win-1", hostname="WIN-PC"
        )
        self.assertEqual(lease.fencing_token, 1)
        self.assertIsNotNone(port.get_writer_lease())
        port.release_writer_lease(
            account_id="default", writer_id="win-1", lease_token=lease.lease_token
        )
        self.assertIsNone(port.get_writer_lease())

    def test_second_writer_rejected(self) -> None:
        port = MemoryPaperStateAdapter()
        port.acquire_writer_lease(
            account_id="default", writer_id="win-1", hostname="WIN-PC"
        )
        with self.assertRaises(LeaseConflictError) as ctx:
            port.acquire_writer_lease(
                account_id="default", writer_id="mac-1", hostname="MAC-PC"
            )
        self.assertIn("ACTIVE_WRITER_EXISTS", str(ctx.exception))

    def test_lease_expiry_takeover(self) -> None:
        port = MemoryPaperStateAdapter()
        lease = port.acquire_writer_lease(
            account_id="default",
            writer_id="win-1",
            hostname="WIN-PC",
            ttl_sec=1,
        )
        self.assertEqual(lease.fencing_token, 1)
        time.sleep(1.2)
        lease2 = port.acquire_writer_lease(
            account_id="default",
            writer_id="mac-1",
            hostname="MAC-PC",
            ttl_sec=DEFAULT_LEASE_TTL_SEC,
        )
        self.assertEqual(lease2.fencing_token, 2)
        self.assertEqual(lease2.writer_id, "mac-1")

    def test_stale_writer_write_rejected(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        old = port.acquire_writer_lease(
            account_id="default", writer_id="win-1", hostname="WIN-PC", ttl_sec=1
        )
        time.sleep(1.2)
        new = port.acquire_writer_lease(
            account_id="default", writer_id="mac-1", hostname="MAC-PC"
        )
        acc = port.get_account()
        assert acc is not None
        with self.assertRaises(StaleWriterError):
            port.apply_trade_mutation(
                account_id="default",
                trade=PaperTrade(
                    trade_id="t-stale",
                    account_id="default",
                    symbol="000001",
                    side="buy",
                    qty=100,
                    fill_price=10.0,
                    trading_session_date="2026-09-21",
                    executed_at="2026-09-21T01:30:00Z",
                    execution_id="exec-stale",
                ),
                position=PositionRecord(
                    account_id="default", symbol="000001", qty=100, cost=10.0
                ),
                account=AccountSnapshot(account_id="default", account_cash=1.0),
                expected_account_version=acc.version,
                writer_id=old.writer_id,
                lease_token=old.lease_token,
                fencing_token=old.fencing_token,
            )
        # new writer ok
        port.apply_trade_mutation(
            account_id="default",
            trade=PaperTrade(
                trade_id="t-new",
                account_id="default",
                symbol="000001",
                side="buy",
                qty=100,
                fill_price=10.0,
                trading_session_date="2026-09-21",
                executed_at="2026-09-21T01:30:00Z",
                execution_id="exec-new",
            ),
            position=PositionRecord(
                account_id="default", symbol="000001", qty=100, cost=10.0
            ),
            account=AccountSnapshot(
                account_id="default", account_cash=99_000.0, version=acc.version
            ),
            expected_account_version=acc.version,
            writer_id=new.writer_id,
            lease_token=new.lease_token,
            fencing_token=new.fencing_token,
        )
        self.assertEqual(len(port.list_trades()), 1)

    def test_network_failure_no_local_write(self) -> None:
        pg = PostgresPaperStateAdapter("")
        with self.assertRaises(RemoteUnavailableError):
            pg.apply_trade_mutation(
                account_id="default",
                trade=PaperTrade(
                    trade_id="x",
                    account_id="default",
                    symbol="000001",
                    side="buy",
                    qty=1,
                    fill_price=1.0,
                    trading_session_date="2026-09-21",
                    executed_at="2026-09-21T00:00:00Z",
                ),
                position=PositionRecord(account_id="default", symbol="000001", qty=1),
                account=AccountSnapshot(account_id="default"),
                expected_account_version=0,
                writer_id="w",
                lease_token="t",
                fencing_token=1,
            )
        local = LocalJsonPaperStateAdapter(ROOT)
        with self.assertRaises(RemoteUnavailableError):
            local.assert_no_local_fallback_write()

    def test_windows_mac_same_state(self) -> None:
        """Two machines loading the same remote snapshot see identical durable state."""
        win = MemoryPaperStateAdapter()
        mac = MemoryPaperStateAdapter()
        _seed(win, cash=88_888.0)
        snap = win.load_full_state()
        mac.replace_full_state(snap, require_lease=False)
        self.assertEqual(state_content_hash(win.load_full_state()), state_content_hash(mac.load_full_state()))
        self.assertEqual(win.get_account().account_cash, mac.get_account().account_cash)

    def test_same_day_restart(self) -> None:
        port = MemoryPaperStateAdapter()
        _seed(port)
        h1 = state_content_hash(port.load_full_state())
        # simulate process restart: new adapter hydrate from exported full state
        port2 = MemoryPaperStateAdapter()
        port2.replace_full_state(port.load_full_state(), require_lease=False)
        self.assertEqual(h1, state_content_hash(port2.load_full_state()))
        self.assertEqual(
            port2.get_account().trading_session_date,
            "2026-09-21",
        )

    def test_friday_monday_session(self) -> None:
        """trading_session_date is explicit A-share session, not OS timezone."""
        port = MemoryPaperStateAdapter()
        fri = holdings_to_full_state(
            {
                "account_cash": 1.0,
                "paper_equity_base": 300000.0,
                "account_total_open": 300000.0,
                "account_total_open_session": "2026-09-18",
                "last_session": "2026-09-18",
                "positions": {},
                "realized_today": {},
                "daily_settlements": {
                    "2026-09-18": {
                        "account_open": 300000.0,
                        "final": True,
                        "settled_at": "2026-09-18T07:00:00Z",
                    }
                },
            }
        )
        port.replace_full_state(fri, require_lease=False)
        daily = port.get_daily_state("default", "2026-09-18")
        self.assertIsNotNone(daily)
        assert daily is not None
        self.assertTrue(daily.settled)
        # Monday session is a different key — no auto-derive from Mac/Windows TZ
        self.assertIsNone(port.get_daily_state("default", "2026-09-21"))
        mon = fri
        mon.account.trading_session_date = "2026-09-21"
        mon.account.account_total_open_session = "2026-09-21"
        mon.account.last_session = "2026-09-21"
        port.replace_full_state(mon, require_lease=False)
        self.assertEqual(port.get_account().trading_session_date, "2026-09-21")

    def test_factory_backends(self) -> None:
        mem = create_paper_state_port("memory")
        self.assertEqual(mem.backend_name(), "memory")
        local = create_paper_state_port("local_json", local_root=str(ROOT))
        self.assertEqual(local.backend_name(), "local_json")
        pg = create_paper_state_port("postgres", database_url="")
        self.assertEqual(pg.backend_name(), "postgres")

    def test_fencing_token_monotonic(self) -> None:
        port = MemoryPaperStateAdapter()
        a = port.acquire_writer_lease(
            account_id="default", writer_id="a", hostname="h", ttl_sec=1
        )
        time.sleep(1.2)
        b = port.acquire_writer_lease(
            account_id="default", writer_id="b", hostname="h2"
        )
        self.assertEqual(a.fencing_token + 1, b.fencing_token)

    def test_local_inventory_dry_run_hash(self) -> None:
        """Windows holdings.json loads into FullPaperState with stable hash (read-only)."""
        holdings_path = ROOT / "holdings.json"
        if not holdings_path.is_file():
            self.skipTest("holdings.json missing")
        adapter = LocalJsonPaperStateAdapter(ROOT)
        full = adapter.load_full_state()
        self.assertGreaterEqual(len(full.open_positions()), 1)
        h = state_content_hash(full)
        self.assertEqual(len(h), 16)


if __name__ == "__main__":
    unittest.main()
