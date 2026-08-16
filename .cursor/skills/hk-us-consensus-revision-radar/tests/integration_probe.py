"""Small real-service probe; requires credentials in the process environment."""

from pathlib import Path

import panda_data

from scripts.run_report import WorkflowOptions, run_workflow


def main() -> None:
    output = run_workflow(
        WorkflowOptions(
            markets=["hk", "us"],
            symbols={"hk": ["0700.HK", "9988.HK"], "us": ["AAPL", "NVDA"]},
            horizon="1month",
            min_analysts=5,
            output_dir=Path("output") / "integration",
        ),
        panda_data,
    )
    print(output)


if __name__ == "__main__":
    main()
