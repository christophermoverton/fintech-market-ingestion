from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from dotenv import load_dotenv

from src.ingestion.alpaca_client import AlpacaConfig


SUPPORTED_DIVIDEND_ACTION_TYPES = frozenset({"cash_dividend", "stock_dividend"})
SUPPORTED_SORT_ORDERS = frozenset({"asc", "desc"})


@dataclass(frozen=True)
class CorporateActionRecord:
    """Stable low-level record for downstream corporate-action normalization."""

    id: Optional[str]
    symbol: Optional[str]
    type: Optional[str]
    process_date: Optional[str]
    raw: Dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "CorporateActionRecord":
        return cls(
            id=payload.get("id"),
            symbol=payload.get("symbol"),
            type=payload.get("type"),
            process_date=payload.get("process_date"),
            raw=dict(payload),
        )

    def as_dict(self) -> Dict[str, Any]:
        """Return the original Alpaca payload fields for normalization/storage layers."""
        return dict(self.raw)


class AlpacaCorporateActionsClient:
    """Alpaca corporate-actions source client.

    This client is intentionally separate from OHLCV market data ingestion. M3.1 only
    supports Alpaca dividend action types: cash_dividend and stock_dividend.
    """

    def __init__(self, cfg: AlpacaConfig, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": cfg.api_key_id,
                "APCA-API-SECRET-KEY": cfg.api_secret_key,
            }
        )

    @staticmethod
    def from_env() -> "AlpacaCorporateActionsClient":
        load_dotenv()
        api_key = os.getenv("ALPACA_API_KEY_ID")
        api_secret = os.getenv("ALPACA_API_SECRET_KEY")
        base_url = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
        feed = os.getenv("ALPACA_FEED", "iex")

        if not api_key or not api_secret:
            raise ValueError("Missing ALPACA_API_KEY_ID or ALPACA_API_SECRET_KEY in environment")

        return AlpacaCorporateActionsClient(
            AlpacaConfig(
                api_key_id=api_key,
                api_secret_key=api_secret,
                data_base_url=base_url,
                feed=feed,
            )
        )

    def _sleep_backoff(self, attempt: int) -> None:
        base = self.cfg.backoff_base_s * (2**attempt)
        jitter = random.uniform(0, 0.25 * base)
        sleep_s = min(self.cfg.backoff_max_s, base + jitter)
        time.sleep(sleep_s)

    def _request_with_retries(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Optional[Exception] = None

        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.cfg.timeout_s)

                if resp.status_code == 429:
                    self._sleep_backoff(attempt)
                    continue

                if 500 <= resp.status_code <= 599:
                    self._sleep_backoff(attempt)
                    continue

                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise RuntimeError(f"Unexpected Alpaca corporate-actions response: {payload!r}")
                return payload

            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                self._sleep_backoff(attempt)
                continue
            except requests.HTTPError as e:
                raise RuntimeError(
                    "Alpaca corporate-actions request failed: "
                    f"status={resp.status_code} url={url} params={params} body={resp.text[:500]}"
                ) from e

        raise RuntimeError(
            f"Alpaca corporate-actions request failed after retries: url={url} params={params}"
        ) from last_err

    def fetch_corporate_actions(
        self,
        symbols: Sequence[str] | str,
        start: str,
        end: str,
        types: Optional[Sequence[str] | str] = None,
        limit: int = 1000,
        sort: str = "asc",
    ) -> List[CorporateActionRecord]:
        """Fetch historical Alpaca corporate action records.

        Args:
            symbols: Symbol or symbols to request. Sent as Alpaca's comma-delimited
                symbols parameter.
            start/end: Inclusive process_date interval in YYYY-MM-DD format.
            types: Supported M3.1 action types: cash_dividend, stock_dividend.
            limit: Max corporate actions per response page. Alpaca supports 1-1000.
            sort: Alpaca sort order, either asc or desc.
        """
        requested_symbols = _normalize_values(symbols)
        requested_types = _normalize_values(types) or sorted(SUPPORTED_DIVIDEND_ACTION_TYPES)
        _validate_symbols(requested_symbols)
        _validate_action_types(requested_types)
        _validate_limit(limit)
        _validate_sort(sort)

        params: Dict[str, Any] = {
            "symbols": ",".join(requested_symbols),
            "types": ",".join(requested_types),
            "start": start,
            "end": end,
            "limit": limit,
            "sort": sort,
        }

        url = f"{self.cfg.data_base_url}/v1/corporate-actions"
        all_records: List[CorporateActionRecord] = []
        page_token: Optional[str] = None

        while True:
            if page_token:
                params["page_token"] = page_token
            else:
                params.pop("page_token", None)

            payload = self._request_with_retries(url, params=params)
            rows = payload.get("corporate_actions") or []
            all_records.extend(CorporateActionRecord.from_payload(row) for row in rows)

            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return all_records

    def fetch_dividends(
        self,
        symbols: Sequence[str] | str,
        start: str,
        end: str,
        limit: int = 1000,
        sort: str = "asc",
    ) -> List[CorporateActionRecord]:
        """Fetch cash and stock dividend corporate actions."""
        return self.fetch_corporate_actions(
            symbols=symbols,
            start=start,
            end=end,
            types=sorted(SUPPORTED_DIVIDEND_ACTION_TYPES),
            limit=limit,
            sort=sort,
        )


def _normalize_values(values: Sequence[str] | str | None) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        parts = values.split(",")
    else:
        parts = list(values)
    return [part.strip() for part in parts if part and part.strip()]


def _validate_symbols(symbols: Sequence[str]) -> None:
    if not symbols:
        raise ValueError("At least one symbol is required for Alpaca corporate actions")


def _validate_action_types(types: Iterable[str]) -> None:
    unsupported = sorted(set(types) - SUPPORTED_DIVIDEND_ACTION_TYPES)
    if unsupported:
        supported = ", ".join(sorted(SUPPORTED_DIVIDEND_ACTION_TYPES))
        raise ValueError(f"Unsupported corporate action type(s): {unsupported}. Supported: {supported}")


def _validate_limit(limit: int) -> None:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000 for Alpaca corporate actions")


def _validate_sort(sort: str) -> None:
    if sort not in SUPPORTED_SORT_ORDERS:
        raise ValueError("sort must be either 'asc' or 'desc'")
