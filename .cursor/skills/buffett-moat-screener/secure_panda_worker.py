"""Run one repository with credentials supplied only to the child process."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback


def _repository_inputs(name: str) -> tuple[dict, dict]:
    if name == "skill-buffett-moat-screener":
        production = {
            "as_of_date": "20260714",
            "symbols": ["600519.SH"],
        }
        return production, {}
    if name == "skill-dalio-all-weather":
        return {"as_of_date": "20260630"}, {"as_of_date": "20260630", "start_date": "20140101"}
    if name == "skill-klarman-special-situations":
        production = {"as_of_date": "20260630", "start_date": "20140101"}
        feasibility = {"as_of_date": "20260630", "start_date": "20140101"}
        return production, feasibility
    raise ValueError(f"Unsupported repository: {name}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: secure_panda_worker.py <repository-path>")
    repository = Path(sys.argv[1]).resolve()
    credentials = None

    if repository.name == "skill-buffett-moat-screener":
        sys.path.insert(0, str(repository))
        import scripts.panda_adapter as panda_adapter
        import scripts.build as build

        try:
            panda_adapter.consume_environment_credentials()
            production_input, _ = _repository_inputs(repository.name)
            production = build.run(production_input, {"materialize": True})
            print(json.dumps({
                "repository": repository.name,
                "production_status": production.get("status"),
                "production_path": production.get("production_path"),
                "data_version": production.get("data_version"),
                "market": production.get("source", {}).get("market"),
            }, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(json.dumps({
                "repository": repository.name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }, ensure_ascii=False))
            return 1
        finally:
            panda_adapter.clear_process_credentials()

    sys.path.insert(0, str(repository / "scripts"))
    import panda_adapter
    import build

    credentials = json.loads(sys.stdin.readline())
    import feasibility
    import holdings_validation
    import coverage
    import cross_market_validation

    production_input, feasibility_input = _repository_inputs(repository.name)
    try:
        panda_adapter.configure_process_credentials(
            credentials["username"], credentials["password"], credentials.get("base_url")
        )
        production = build.run(production_input, {"materialize": True})
        validation = feasibility.run_feasibility(
            feasibility_input, {"output_dir": repository / "validation"}
        )
        capabilities = coverage.run_coverage_probe(
            {"start_date": "20140101", "end_date": "20260630", "markets": ["cn", "hk", "us"]}
        )
        cross_market = cross_market_validation.run_cross_market_validation(
            {"start_date": "20140101", "end_date": "20260630", "markets": ["cn", "hk", "us"]},
            {"capabilities": capabilities.get("markets", {})},
        )
        (repository / "validation" / "market_capabilities.json").write_text(
            json.dumps(capabilities, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (repository / "validation" / "cross_market_summary.json").write_text(
            json.dumps(cross_market, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        holdings_input = {"as_of_date": "20260714"}
        if repository.name == "skill-buffett-moat-screener":
            holdings_input["selected_symbols"] = [
                row["target_id"]
                for row in production.get("records", [])
                if row.get("result_value") == "pass"
                and str(row.get("target_id", "")).endswith(".NB")
            ]
        holdings = holdings_validation.run_holdings_validation(
            holdings_input,
            {"snapshot_path": next((repository / "validation" / "benchmarks").glob("*.parquet"))},
        )
        (repository / "validation" / "holdings_comparison.json").write_text(
            json.dumps(holdings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "repository": repository.name,
            "production_status": production.get("status"),
            "production_path": production.get("production_path"),
            "data_version": production.get("data_version"),
            "feasibility_status": validation.get("status"),
            "point_in_time": validation.get("point_in_time"),
            "holdings_type": holdings.get("comparison_type"),
            "holdings_coverage": holdings.get("coverage_status"),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "repository": repository.name,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }, ensure_ascii=False))
        return 1
    finally:
        panda_adapter.clear_process_credentials()
        if credentials is not None:
            credentials.clear()


if __name__ == "__main__":
    raise SystemExit(main())
