from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cli.ingest_corporate_actions import ingest_dividend_corporate_actions
from src.ingestion.alpaca_corporate_actions_client import CorporateActionRecord

DEFAULT_EXAMPLE_OUTPUT_ROOT = Path("artifacts/examples/corporate_actions_dividends")


class SampleCorporateActionsClient:
    """Small fake client for CI-safe example runs."""

    def __init__(self) -> None:
        self.records = [
            CorporateActionRecord.from_payload(
                {
                    "id": "sample-cash-dividend-1",
                    "symbol": "AAPL",
                    "type": "cash_dividend",
                    "process_date": "2024-02-15",
                    "declaration_date": "2024-02-01",
                    "ex_date": "2024-02-09",
                    "record_date": "2024-02-12",
                    "payable_date": "2024-02-29",
                    "cash_amount": "0.24",
                    "stock_amount": None,
                    "currency": "USD",
                }
            ),
            CorporateActionRecord.from_payload(
                {
                    "id": "sample-stock-dividend-1",
                    "symbol": "MSFT",
                    "type": "stock_dividend",
                    "process_date": "2024-03-15",
                    "declaration_date": "2024-03-01",
                    "ex_date": "2024-03-08",
                    "record_date": "2024-03-11",
                    "payable_date": "2024-03-29",
                    "cash_amount": None,
                    "stock_amount": "0.05",
                    "currency": None,
                }
            ),
        ]

    def fetch_corporate_actions(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
        types: Sequence[str],
        limit: int,
        sort: str,
    ) -> list[CorporateActionRecord]:
        requested_symbols = set(symbols)
        requested_types = set(types)
        return [
            record
            for record in self.records
            if record.symbol in requested_symbols and record.type in requested_types
        ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a CI-safe sample dividend corporate-actions ingestion with fixed local data."
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_EXAMPLE_OUTPUT_ROOT),
        help="Repository-relative output root for sample corporate-actions dividends data",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = ingest_dividend_corporate_actions(
        symbols=["AAPL", "MSFT"],
        start="2024-01-01",
        end="2024-12-31",
        types=["cash_dividend", "stock_dividend"],
        output_root=args.output_root,
        client=SampleCorporateActionsClient(),
    )
    print(json.dumps(result.as_dict(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
