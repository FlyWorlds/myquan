"""Command workflow for the HK/US consensus revision radar."""

from __future__ import annotations

import argparse
import json
import math
import numbers
import os
import secrets
import shlex
import socket
import time
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.analysis import (
    HORIZONS, build_consensus_states, build_eligibility_funnels,
    build_quality_summary, build_rankings, compute_metrics,
)
from scripts.auth_session import (
    AuthenticationError, CredentialError, Credentials, SessionGrant,
    adopt_authenticated_session, authenticate, read_credentials, resolve_credentials,
)
from scripts.data_pipeline import MARKET_APIS, collect_market_data, normalize_market_frames
from scripts.event_context import EVENT_APIS, collect_market_events, resolve_event_reference_date
from scripts.report import render_report


@dataclass
class WorkflowOptions:
    markets: list[str] = field(default_factory=lambda: ["hk", "us"])
    symbols: dict[str, list[str]] = field(default_factory=dict)
    horizon: str = "1month"
    min_analysts: int = 5
    min_recommendations: int = 5
    revision_threshold: float = 0.01
    ranking_limit: int = 20
    include_events: bool = True
    event_past_days: int = 30
    event_future_days: int = 30
    event_discovery_days: int = 730
    start_date: str | None = None
    end_date: str | None = None
    output_dir: Path = Path("output")


def _validate_options(options: WorkflowOptions) -> None:
    invalid_markets = sorted(set(options.markets) - {"hk", "us"})
    if invalid_markets:
        raise ValueError(f"unsupported markets: {', '.join(invalid_markets)}")
    if options.horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of: {', '.join(HORIZONS)}")
    if options.min_analysts < 1:
        raise ValueError("min_analysts must be at least 1")
    if options.min_recommendations < 1:
        raise ValueError("min_recommendations must be at least 1")
    if not 0 <= options.revision_threshold <= 1:
        raise ValueError("revision_threshold must be between 0 and 1")
    if options.ranking_limit < 1:
        raise ValueError("ranking_limit must be at least 1")
    if not 0 <= options.event_past_days <= 365:
        raise ValueError("event_past_days must be between 0 and 365")
    if not 0 <= options.event_future_days <= 365:
        raise ValueError("event_future_days must be between 0 and 365")
    if not options.event_past_days <= options.event_discovery_days <= 3650:
        raise ValueError(
            "event_discovery_days must be between event_past_days and 3650"
        )


def _records(frame: pd.DataFrame, *, normalize_evidence: bool = True) -> list[dict]:
    if frame.empty:
        return []
    serialized = json.loads(
        frame.to_json(orient="records", date_format="iso", force_ascii=False)
    )
    if not normalize_evidence:
        return serialized
    return _normalize_payload_value(frame.to_dict(orient="records"), serialized)


def _is_nonfinite_number(value: object) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and not math.isfinite(value)
    )


def _contains_nonfinite_number(value: object) -> bool:
    if _is_nonfinite_number(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_nonfinite_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nonfinite_number(item) for item in value)
    return False


def _normalize_payload_value(raw: object, serialized: object) -> object:
    """Keep report-only output evidence consistent with JSON-safe values."""
    if isinstance(raw, Mapping) and isinstance(serialized, Mapping):
        normalized = {
            key: _normalize_payload_value(value, serialized.get(key))
            for key, value in raw.items()
        }
        raw_states = raw.get("consensus_states")
        serialized_states = serialized.get("consensus_states")
        if isinstance(raw_states, list) and isinstance(serialized_states, list):
            normalized["consensus_states"] = [
                _normalize_payload_value(state, safe_state)
                for state, safe_state in zip(raw_states, serialized_states)
                if not _contains_nonfinite_number(state.get("evidence"))
            ]
        direction_inputs = {
            "revision_direction": ("tp_revision",),
            "rating_direction": ("rating_change",),
        }
        for direction, inputs in direction_inputs.items():
            if direction in normalized and any(
                _is_nonfinite_number(raw.get(input)) for input in inputs
            ):
                normalized[direction] = "unavailable"
        for key in raw:
            if key.startswith("tp_direction_"):
                change = f"tp_revision_{key.removeprefix('tp_direction_')}"
                if _is_nonfinite_number(raw.get(change)):
                    normalized[key] = "unavailable"
            if key.startswith("rating_direction_"):
                change = f"rating_change_{key.removeprefix('rating_direction_')}"
                if _is_nonfinite_number(raw.get(change)):
                    normalized[key] = "unavailable"
        if "direction" in normalized and any(
            _is_nonfinite_number(raw.get(key))
            for key in ("current", "historical", "change")
        ):
            normalized["direction"] = "unavailable"
        return normalized
    if isinstance(raw, list) and isinstance(serialized, list):
        return [
            _normalize_payload_value(value, safe_value)
            for value, safe_value in zip(raw, serialized)
        ]
    return serialized


def _trajectory_value(row: pd.Series, column: str) -> float | None:
    value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
    return None if pd.isna(value) or not math.isfinite(value) else float(value)


def _trajectory(
    row: pd.Series, prefix: str, horizon: str, revision_threshold: float,
) -> list[dict[str, object]]:
    current_column = "tp_mean" if prefix == "tp_mean" else "rec_mean"
    current = _trajectory_value(row, current_column)
    trajectory: list[dict[str, object]] = []
    for period in HORIZONS:
        historical = _trajectory_value(row, f"{prefix}_{period}")
        if current is None or historical is None or (prefix == "tp_mean" and historical == 0):
            change = None
            direction = "unavailable"
        elif prefix == "tp_mean":
            change = current / historical - 1
            direction = (
                "positive" if change > revision_threshold
                else "negative" if change < -revision_threshold else "flat"
            )
        else:
            change = historical - current
            direction = (
                "positive" if change > revision_threshold
                else "negative" if change < -revision_threshold else "flat"
            )
        trajectory.append({
            "horizon": period,
            "current": current,
            "historical": historical,
            "change": change,
            "direction": direction,
            "threshold": revision_threshold,
        })
    return trajectory


def _trajectory_matrix(
    metrics: pd.DataFrame, revision_threshold: float,
) -> list[dict[str, object]]:
    core_universe = metrics.get(
        "universe_eligible", pd.Series(False, index=metrics.index),
    ).fillna(False).astype(bool)
    rows: list[dict[str, object]] = []
    for _, row in metrics.loc[core_universe].sort_values("symbol", kind="mergesort").iterrows():
        rows.append({
            "name": row.get("name"),
            "symbol": row.get("symbol"),
            "industry_group": row.get("industry_group"),
            "target_price_trajectory": _trajectory(
                row, "tp_mean", "target_price", revision_threshold,
            ),
            "rating_trajectory": _trajectory(
                row, "rec_mean", "rating", revision_threshold,
            ),
            "dispersion": _trajectory_value(row, "dispersion"),
            "coverage": {
                "estimates_num": _trajectory_value(row, "estimates_num"),
                "included_estimates_num": _trajectory_value(row, "included_estimates_num"),
                "recommendations_num": _trajectory_value(row, "recommendations_num"),
            },
            "consensus_states": row.get("consensus_states", []),
            "dispersion_p75": _trajectory_value(row, "dispersion_p75"),
            "dispersion_sample_count": _trajectory_value(row, "dispersion_sample_count"),
        })
    return _records(pd.DataFrame(rows))


def _quality_warnings(markets_payload: dict[str, dict]) -> list[str]:
    warnings: list[str] = []
    labels = {"hk": "HK", "us": "US"}
    for market, payload in markets_payload.items():
        label = labels.get(market, market.upper())
        quality = payload.get("quality", {})
        diagnostics = payload.get("diagnostics", {})
        match_rate = diagnostics.get("price_match_rate")
        universe = diagnostics.get("price_universe_symbols")
        matched = diagnostics.get("price_matched_symbols")
        if match_rate is not None and match_rate < 1:
            warnings.append(
                f"{label}: PandaData price match rate is "
                f"{match_rate:.1%} ({matched}/{universe}); missing prices "
                "remain missing."
            )
        if diagnostics.get("price_fallback_used"):
            warnings.append(
                f"{label}: PandaData latest-date price query was incomplete; "
                "the report fell back to the preceding 14 calendar days."
            )
        for key, text in (
            ("missing_name", "missing security names"),
            ("missing_price", "missing prices"),
            ("missing_history", "missing target-price history"),
            ("missing_recommendation", "missing recommendation data"),
            ("missing_coverage", "missing analyst coverage"),
            ("missing_recommendation_coverage", "missing recommendation coverage"),
        ):
            count = int(quality.get(key, 0) or 0)
            if count:
                warnings.append(f"{label}: PandaData {text}: {count}.")
        excluded = int(quality.get("excluded_universe_rows", 0) or 0)
        if excluded:
            warnings.append(
                f"{label}: {excluded} securities are retained for diagnostics but "
                "excluded from rankings by the core-universe rules."
            )
        validation_errors = int(quality.get("validation_error_rows", 0) or 0)
        if validation_errors:
            warnings.append(
                f"{label}: PandaData consistency validation errors: "
                f"{validation_errors}; affected rows are excluded only from dependent rankings."
            )
        currency_unverified = int(quality.get("currency_unverified_rows", 0) or 0)
        if currency_unverified:
            warnings.append(
                f"{label}: target/price currency comparability is unverified for "
                f"{currency_unverified} rows; price-divergence ranking excludes them."
            )
        event_context = payload.get("event_context", {})
        event_status = event_context.get("status")
        if event_status in {"partial", "unavailable"}:
            availability = "partially unavailable" if event_status == "partial" else "unavailable"
            warnings.append(
                f"{label}: PandaData event context is {availability}; "
                "consensus rankings are unchanged."
            )
    return warnings

def _notify_progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _print_progress(message: str) -> None:
    print(f"[PROGRESS] {message}", file=sys.stderr, flush=True)


def _progress_status_reporter(destination: Path) -> Callable[[str], None]:
    """Emit progress to stderr and retain only the latest credential-free status."""
    destination = Path(destination)

    def report(message: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "message": message,
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
        _print_progress(message)

    return report


@dataclass(frozen=True)
class _ProgressRelay:
    host: str
    port: int
    token: str

    def _send(self, event: dict[str, object]) -> None:
        payload = {'token': self.token, **event}
        with socket.create_connection((self.host, self.port), timeout=30) as connection:
            connection.sendall(
                (json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8')
            )

    def progress(self, message: str) -> None:
        self._send({'kind': 'progress', 'message': message})
        _print_progress(message)

    def auth_failure(self, message: str = 'PandaData 登录失败，请重新输入账号和密码。') -> None:
        self._send({'kind': 'auth_failure', 'message': message})
        _print_progress(message)

    def authenticated_session(self, grant: SessionGrant) -> None:
        self._send({
            'kind': 'authenticated_session',
            'access_token': grant.access_token,
            'username': grant.username,
            'base_url': grant.base_url,
            'expires_in_seconds': grant.expires_in_seconds,
        })

    def complete(self, output: Path, warnings: list[str]) -> None:
        self._send({
            'kind': 'complete',
            'output': str(output),
            'warnings': warnings,
        })

    def error(self, message: str) -> None:
        self._send({'kind': 'error', 'message': message})


def _handle_parent_event(
    event: dict[str, object],
    token: str,
    progress_callback: Callable[[str], None] | None = None,
) -> int | SessionGrant | None:
    if event.get('token') != token:
        return None
    report_progress = progress_callback or _print_progress
    kind = event.get('kind')
    if kind == 'progress':
        report_progress(str(event.get('message', '')))
        return None
    if kind == 'auth_failure':
        report_progress(str(event.get('message', 'PandaData login failed; waiting for a new username and password...')))
        return None
    if kind == 'authenticated_session':
        access_token = str(event.get('access_token', ''))
        username = str(event.get('username', '')).strip()
        base_url = str(event.get('base_url', '')).strip()
        try:
            expires_in_seconds = int(event.get('expires_in_seconds', 0))
        except (TypeError, ValueError):
            expires_in_seconds = 0
        if not access_token or not username or not base_url or expires_in_seconds <= 0:
            print('PandaData login helper returned incomplete session data.', file=sys.stderr)
            return 1
        report_progress('PandaData 登录成功，主进程将复用已验证会话。')
        return SessionGrant(access_token, username, base_url, expires_in_seconds)
    if kind == 'complete':
        output = str(event.get('output', '')).strip()
        if not output:
            print('Report generation failed: missing output path', file=sys.stderr)
            return 1
        print(output)
        for warning in event.get('warnings', []) or []:
            print(f'DATA QUALITY WARNING: {warning}', file=sys.stderr)
        return 0
    if kind == 'error':
        print(f'Report generation failed: {event.get("message", "unknown error")}', file=sys.stderr)
        return 1
    return None

def _market_payload(
    metrics: pd.DataFrame,
    min_analysts: int,
    limit: int,
    diagnostics: dict[str, object],
    revision_threshold: float,
    min_recommendations: int = 5,
) -> dict:
    horizon = (
        str(metrics["analysis_horizon"].iloc[0])
        if not metrics.empty and "analysis_horizon" in metrics
        else "1month"
    )
    state_metrics = build_consensus_states(
        metrics, revision_threshold=revision_threshold, horizon=horizon,
    )
    rankings = build_rankings(
        metrics,
        min_analysts=min_analysts,
        min_recommendations=min_recommendations,
        limit=limit,
    )
    market = str(metrics["market"].iloc[0]) if not metrics.empty else ""
    market_rankings = rankings.get(market, {})
    eligible = market_rankings.get("eligible", pd.DataFrame())
    revision_eligible = market_rankings.get("revision_eligible", pd.DataFrame())
    revision_direction = revision_eligible.get(
        "revision_direction",
        pd.Series(pd.NA, index=revision_eligible.index, dtype="object"),
    )
    eligibility_funnels = build_eligibility_funnels(
        metrics,
        horizon=horizon,
        min_analysts=min_analysts,
        min_recommendations=min_recommendations,
    )
    if eligibility_funnels["target_revision"][-1]["count"] != len(revision_eligible):
        raise RuntimeError("target revision eligibility funnel is inconsistent")
    rating_eligible = market_rankings.get("rating_eligible", pd.DataFrame())
    if eligibility_funnels["rating"][-1]["count"] != len(rating_eligible):
        raise RuntimeError("rating eligibility funnel is inconsistent")
    overview = {
        "eligible_rows": int(len(eligible)),
        "revision_eligible_rows": int(len(revision_eligible)),
        "rating_eligible_rows": int(len(rating_eligible)),
        "upgrade_rows": int(revision_direction.eq("upgrade").sum()),
        "downgrade_rows": int(revision_direction.eq("downgrade").sum()),
        "min_analysts": min_analysts,
        "min_recommendations": min_recommendations,
    }
    categories = (
        "upgrades",
        "downgrades",
        "high_dispersion",
        "rating_changes",
        "price_consensus_divergence",
    )
    sources = []
    for column in (
        "source_ncycl", "source_recommendation", "source_price", "source_detail"
    ):
        if column in metrics:
            sources.extend(metrics[column].dropna().astype(str).unique().tolist())
    api = MARKET_APIS.get(market, {"detail": "", "ncycl": "", "recommendation": "", "daily": ""})
    source_interfaces = [
        {"interface": api["detail"], "purpose": "证券名称、状态、类型与行业身份"},
        {"interface": api["ncycl"], "purpose": "目标价一致预期"},
        {"interface": api["recommendation"], "purpose": "评级一致预期"},
        {"interface": api["daily"], "purpose": "收盘价与日行情"},
    ]
    source_interfaces = [item for item in source_interfaces if item["interface"]]
    if diagnostics.get("requested_latest_date"):
        source_interfaces.append({
            "interface": "get_last_trade_date",
            "purpose": "最近交易日探测",
        })
    return {
        "rows": _records(state_metrics),
        "trajectory_matrix": _trajectory_matrix(state_metrics, revision_threshold),
        "rankings": {
            key: _records(
                market_rankings.get(key, pd.DataFrame()),
                normalize_evidence=False,
            )
            for key in categories
        },
        "overview": overview,
        "quality": build_quality_summary(
            metrics,
            min_analysts=min_analysts,
            min_recommendations=min_recommendations,
        ),
        "eligibility_funnels": eligibility_funnels,
        "diagnostics": diagnostics,
        "methodology": {
            "revision_threshold": revision_threshold,
            "revision_formula": "current_target_mean / historical_target_mean - 1",
            "price_distance_formula": "current_target_mean / latest_close - 1",
            "consensus_level": "aggregate",
        },
        "sources": sorted(set(sources)),
        "source_interfaces": source_interfaces,
    }


def _event_scope_symbols(
    market_payload: dict, explicit_symbols: list[str],
) -> list[str]:
    categories = (
        "upgrades",
        "downgrades",
        "high_dispersion",
        "rating_changes",
        "price_consensus_divergence",
    )
    symbols = {
        str(row["symbol"]).strip()
        for category in categories
        for row in market_payload.get("rankings", {}).get(category, [])
        if row.get("symbol") is not None and str(row["symbol"]).strip()
    }
    symbols.update(
        str(symbol).strip()
        for symbol in explicit_symbols
        if symbol is not None and str(symbol).strip()
    )
    return sorted(symbols)


def run_workflow(
    options: WorkflowOptions,
    panda_module,
    env: Mapping[str, str] | None = None,
    *,
    credentials: Credentials | None = None,
    session_grant: SessionGrant | None = None,
    quality_warnings: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Authenticate, query PandaData, and create one timestamped offline report."""
    _validate_options(options)
    if session_grant is not None:
        session = adopt_authenticated_session(panda_module, session_grant)
    else:
        active_credentials = credentials
        if active_credentials is None:
            active_credentials = read_credentials(os.environ if env is None else env)
        session = authenticate(panda_module, active_credentials)
    try:
        _notify_progress(progress_callback, "PandaData 连接成功，开始获取数据。")
        markets_payload = {}
        for index, market in enumerate(options.markets, 1):
            label = market.upper()
            _notify_progress(
                progress_callback,
                f"正在获取 {label} 数据（{index}/{len(options.markets)}）...",
            )
            raw = collect_market_data(
                panda_module,
                market,
                symbols=options.symbols.get(market),
                horizon=options.horizon,
                start_date=options.start_date,
                end_date=options.end_date,
                progress_callback=progress_callback,
            )
            _notify_progress(progress_callback, f"{label} 数据获取完成，正在分析...")
            normalized = normalize_market_frames(raw)
            metrics = compute_metrics(
                normalized,
                options.horizon,
                revision_threshold=options.revision_threshold,
            )
            _notify_progress(progress_callback, f"{label} 分析完成。")
            market_payload = _market_payload(
                metrics,
                min_analysts=options.min_analysts,
                min_recommendations=options.min_recommendations,
                limit=options.ranking_limit,
                diagnostics=raw.diagnostics,
                revision_threshold=options.revision_threshold,
            )
            event_symbols = _event_scope_symbols(
                market_payload, options.symbols.get(market, []),
            )
            reference_date = resolve_event_reference_date(metrics)
            if options.include_events:
                event_categories = {
                    interface: category
                    for category, (interface, _) in EVENT_APIS[market].items()
                }
                completed_event_interfaces = 0

                def event_progress(interface: str) -> None:
                    nonlocal completed_event_interfaces
                    completed_event_interfaces += 1
                    _notify_progress(
                        progress_callback,
                        f"{label} event context: "
                        f"{event_categories.get(interface, interface)} "
                        f"{completed_event_interfaces}/{len(event_categories)}",
                    )

                event_bundle = collect_market_events(
                    panda_module,
                    market=market,
                    symbols=event_symbols,
                    reference_date=reference_date,
                    past_days=options.event_past_days,
                    future_days=options.event_future_days,
                    discovery_days=options.event_discovery_days,
                    progress_callback=event_progress,
                )
                market_payload["events"] = _records(event_bundle.events)
                market_payload["event_context"] = event_bundle.diagnostics
                market_payload["source_interfaces"].extend(
                    event_bundle.source_interfaces
                )
            else:
                market_payload["events"] = []
                market_payload["event_context"] = {
                    "status": "disabled",
                    "event_reference_date": reference_date,
                    "event_past_days": options.event_past_days,
                    "event_future_days": options.event_future_days,
                    "event_discovery_days": options.event_discovery_days,
                    "requested_symbol_count": len(event_symbols),
                }
            event_context = market_payload["event_context"]
            _notify_progress(
                progress_callback,
                f"{label} event collection complete: "
                f"{event_context['requested_symbol_count']} symbols, "
                f"{event_context.get('display_event_rows', 0)} events "
                f"({event_context['status']})",
            )
            markets_payload[market] = market_payload

        _notify_progress(progress_callback, "正在写入报告...")
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        payload = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S %z"),
            "horizon": options.horizon,
            "min_analysts": options.min_analysts,
            "min_recommendations": options.min_recommendations,
            "revision_threshold": options.revision_threshold,
            "markets": markets_payload,
        }
        options.output_dir.mkdir(parents=True, exist_ok=True)
        timestamped = options.output_dir / f"consensus_revision_{now:%Y%m%d_%H%M%S}.html"
        result = render_report(payload, timestamped)
        render_report(payload, options.output_dir / "latest.html")
        if quality_warnings is not None:
            quality_warnings.extend(_quality_warnings(markets_payload))
        _notify_progress(progress_callback, f"报告已生成：{result}")
        return result
    finally:
        session.close()


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _login_child_args(host: str, port: int, token: str) -> list[str]:
    return [
        '--login-helper', '--interactive-login', '--no-login-window',
        '--progress-host', host,
        '--progress-port', str(port),
        '--progress-token', token,
    ]


def _build_login_window_command(
    argv: list[str],
    root: Path,
    python_executable: str,
    host: str,
    port: int,
    token: str,
) -> tuple[list[str], dict[str, object]]:
    del argv
    child_args = _login_child_args(host, port, token)
    if sys.platform.startswith('win'):
        command_args = ' '.join(_powershell_quote(value) for value in child_args)
        command = (
            f'Set-Location -LiteralPath {_powershell_quote(str(root))}; '
            f'& {_powershell_quote(python_executable)} -m scripts.run_report '
            f'{command_args}; '
            '$code = $LASTEXITCODE; exit $code'
        )
        creationflags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
        return [
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Normal', '-Command', command,
        ], {'creationflags': creationflags}
    if sys.platform == 'darwin':
        command_args = shlex.join(child_args)
        shell_command = (
            f'cd {shlex.quote(str(root))} && '
            f'{shlex.quote(python_executable)} -m scripts.run_report '
            f'{command_args}; '
            'exit $?'
        )
        apple_script = (
            'tell application "Terminal" to activate\n'
            f'tell application "Terminal" to do script {json.dumps(shell_command)}'
        )
        return ['osascript', '-e', apple_script], {}
    raise OSError(f'interactive login window is unsupported on {sys.platform}')


def _launch_login_window(
    argv: list[str],
    progress_callback: Callable[[str], None] | None = None,
) -> SessionGrant | Credentials | int:
    root = Path(__file__).resolve().parent.parent
    token = secrets.token_urlsafe(32)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    server.listen(5)
    host, port = server.getsockname()
    try:
        try:
            command, kwargs = _build_login_window_command(
                argv, root, str(Path(sys.executable).resolve()), host, port, token,
            )
            process = subprocess.Popen(command, **kwargs)
        except OSError:
            print('Unable to launch PandaData login window.', file=sys.stderr, flush=True)
            return 1
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            server.settimeout(0.5)
            try:
                connection, _ = server.accept()
            except socket.timeout:
                exit_code = process.poll()
                if exit_code is not None:
                    print(
                        f'PandaData login helper exited before authentication (exit code {exit_code}).',
                        file=sys.stderr,
                        flush=True,
                    )
                    return int(exit_code or 1)
                continue
            with connection:
                raw = connection.recv(65536)
            for line in raw.splitlines():
                try:
                    event = json.loads(line.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                result = _handle_parent_event(event, token, progress_callback)
                if result is not None:
                    return result
        return int(process.poll() or 1)
    finally:
        server.close()


def _run_login_helper(relay: _ProgressRelay | None) -> int:
    if relay is None:
        print('PandaData login helper requires a parent progress relay.', file=sys.stderr)
        return 1
    while True:
        try:
            credentials = resolve_credentials(
                {'PANDADATA_USERNAME': '', 'PANDADATA_PASSWORD': ''},
                interactive=True,
                status_writer=relay.progress,
            )
            import panda_data
            session = authenticate(panda_data, credentials)
        except AuthenticationError as exc:
            relay.auth_failure(str(exc))
            continue
        except CredentialError as exc:
            relay.error(f'PandaData login failed: {exc}')
            return 1
        except Exception as exc:
            relay.error(f'PandaData login failed: {exc}')
            return 1
        try:
            relay.progress('PandaData 登录成功，正在启动报告任务...')
            relay.authenticated_session(session.grant)
        finally:
            session.close()
        return 0
def _parse_symbols(value: str | None, markets: list[str]) -> dict[str, list[str]]:
    if not value:
        return {}
    symbols = [item.strip() for item in value.split(",") if item.strip()]
    if len(markets) == 1:
        return {markets[0]: symbols}
    return {
        "hk": [item for item in symbols if item.upper().endswith(".HK")],
        "us": [item for item in symbols if not item.upper().endswith(".HK")],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an offline HK/US consensus report")
    parser.add_argument(
        "--interactive-login",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--login-helper",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-login-window",
        action="store_true",
        help="fail instead of opening a platform login window",
    )
    parser.add_argument(
        "--desktop-login-window",
        action="store_true",
        help="request the local login window from a GUI-capable desktop session",
    )
    parser.add_argument("--market", choices=("hk", "us", "both"), default="both")
    parser.add_argument("--symbols", help="comma-separated symbols; .HK suffix routes to HK")
    parser.add_argument("--horizon", choices=HORIZONS, default="1month")
    parser.add_argument("--min-analysts", type=int, default=5)
    parser.add_argument("--min-recommendations", type=int, default=5)
    parser.add_argument("--revision-threshold", type=float, default=0.01)
    parser.add_argument("--ranking-limit", type=int, default=20)
    parser.add_argument("--event-past-days", type=int, default=30)
    parser.add_argument("--event-future-days", type=int, default=30)
    parser.add_argument("--event-discovery-days", type=int, default=730)
    parser.add_argument("--no-events", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--progress-file",
        help="write the latest credential-free run status to this local JSON file",
    )
    parser.add_argument("--progress-host", help=argparse.SUPPRESS)
    parser.add_argument("--progress-port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--progress-token", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    progress_reporter = (
        _progress_status_reporter(Path(args.progress_file))
        if args.progress_file
        else _print_progress
    )
    relay = None
    if args.progress_host and args.progress_port and args.progress_token:
        relay = _ProgressRelay(args.progress_host, args.progress_port, args.progress_token)
    if args.login_helper:
        return _run_login_helper(relay)
    markets = ['hk', 'us'] if args.market == 'both' else [args.market]
    options = WorkflowOptions(
        markets=markets,
        symbols=_parse_symbols(args.symbols, markets),
        horizon=args.horizon,
        min_analysts=args.min_analysts,
        min_recommendations=args.min_recommendations,
        revision_threshold=args.revision_threshold,
        ranking_limit=args.ranking_limit,
        include_events=not args.no_events,
        event_past_days=args.event_past_days,
        event_future_days=args.event_future_days,
        event_discovery_days=args.event_discovery_days,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
    )
    credentials: Credentials | None = None
    pending_credentials: Credentials | None = None
    pending_session_grant: SessionGrant | None = None
    quality_warnings: list[str] = []
    interactive = args.interactive_login
    try:
        retry_after_auth_failure = False
        while True:
            session_grant: SessionGrant | None = None
            if pending_session_grant is not None:
                session_grant = pending_session_grant
                pending_session_grant = None
                credentials = None
            elif pending_credentials is not None:
                credentials = pending_credentials
                pending_credentials = None
            else:
                try:
                    credentials = (
                        resolve_credentials(
                            {"PANDADATA_USERNAME": "", "PANDADATA_PASSWORD": ""},
                            interactive=True,
                            status_writer=progress_reporter,
                        )
                        if retry_after_auth_failure
                        else resolve_credentials(
                            os.environ,
                            interactive=interactive,
                            status_writer=progress_reporter,
                        )
                    )
                except CredentialError:
                    if args.no_login_window or interactive:
                        raise
                    if not (
                        args.desktop_login_window
                        or (sys.stdin.isatty() and sys.stderr.isatty())
                    ):
                        print(
                            'PandaData credentials are missing. Configure '
                            'PANDADATA_USERNAME/PANDADATA_PASSWORD or rerun from '
                            'a GUI-capable desktop session using '
                            '--desktop-login-window.',
                            file=sys.stderr,
                        )
                        return 1
                    progress_reporter('已请求打开 PandaData 登录窗口，等待本地认证...')
                    login_result = _launch_login_window(
                        raw_argv,
                        progress_callback=progress_reporter,
                    )
                    if isinstance(login_result, SessionGrant):
                        pending_session_grant = login_result
                        continue
                    if isinstance(login_result, Credentials):
                        pending_credentials = login_result
                        continue
                    return int(login_result or 1)
            if relay is None:
                progress_reporter("PandaData credentials received; validating login...")
                _print_progress('宸茶幏鍙栬处鍙峰瘑鐮侊紝姝ｅ湪杩炴帴 PandaData...')
            import panda_data
            if relay is None:
                progress_reporter("PandaData SDK loaded; validating login...")
                _print_progress('PandaData SDK 宸插姞杞斤紝姝ｅ湪楠岃瘉鐧诲綍...')

            try:
                output = run_workflow(
                    options,
                    panda_data,
                    credentials=credentials,
                    session_grant=session_grant,
                    quality_warnings=quality_warnings,
                    progress_callback=relay.progress if relay else progress_reporter,
                )
            except AuthenticationError:
                if not interactive:
                    raise
                retry_after_auth_failure = True
                if relay is not None:
                    relay.auth_failure()
                else:
                    _print_progress('PandaData connection failed; waiting for a new username and password...')
                continue
            break
    except AuthenticationError as exc:
        if relay is None:
            progress_reporter("PandaData connection failed; please retry authentication.")
        if relay is not None:
            relay.error('PandaData 连接失败')
            print('PandaData connection failed.', file=sys.stderr, flush=True)
        else:
            print(f'PandaData 连接失败：{exc}', file=sys.stderr, flush=True)
        return 1
    except CredentialError as exc:
        if relay is None:
            progress_reporter("PandaData login failed; please retry authentication.")
        if relay is not None:
            relay.error(f'PandaData login failed: {exc}')
            print('PandaData login failed.', file=sys.stderr, flush=True)
            return 1
        print(f'Report generation failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        if relay is None:
            progress_reporter("报告生成失败，请查看本地终端。")
        if relay is not None:
            relay.error(f'Report generation failed: {exc}')
            return 1
        print(f'Report generation failed: {exc}', file=sys.stderr)
        return 1
    finally:
        credentials = None

    if relay is not None:
        relay.complete(output, quality_warnings)
        return 0
    print(output)
    for warning in quality_warnings:
        print(f'DATA QUALITY WARNING: {warning}', file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
