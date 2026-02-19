from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass
from typing import Optional,Dict,Any,List

import pandas as pd
import requests
from dotenv import load_dotenv

@dataclass
class AlpacaConfig:
    api_key_id: str
    api_secret_key: str
    data_base_url: str = "https://data.alpaca.markets"
    feed: str = "iex"
    max_retries: int = 5
    ttimeout_s: int = 30
    backoff_base_s: float = 1.0
    backoff_max_s: float = 30.0
    

class AlpacaMarketDataClient:
    """Minimal Alpaca Market Data client for historical bars (1Day, 1Min).
    
    Notes:
    - Uses requests
    - Handles retries with exponential backoff (429, 5xx, network errors)
    -Handles pagination via next_age_token if present
    """
    
    def __init__(self, cfg: AlpacaConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            "APCA-API-KEY-ID": cfg.api_key_id,
            "APCA-API-SECRET-KEY": cfg.api_secret_key,
        )
    
    @staticmethod
    def from_env() -> "AlpacaMarketDataClient":
        load_dotenv()
        api_key = os.getenv("ALPACA_API_KEY_ID")
        api_secret = os.getenv("ALPACA_API_SECRET_KEY")
        base_url = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
        feed = os.getenv("ALPACA_FEED", "iex")
        
        if not api_key or not api_secret:
            raise ValueError("Missing ALPACA_API_KEY_ID or ALPACA_API_SECRET_KEY in environment")
        
        cfg = AlpacaConfig(
            api_key_id = api_key,
            api_secret_key = api_secret,
            data_base_url=base_url,
            feed=feed,
        )
        
        return AlpacaMarketDataClient(cfg)
    
    def _sleep_backoff(self, attempt: int) -> None:
        #exponential backoff + jitter capped
        base = self.cfg.backoff_base_s * (2**attempt)
        jitter = random.uniform(0,0.25 * base)
        sleep_s = min(self.cfg.backoff_max_s, base + jitter)
        time.sleep(sleep_s)
        
    def _request_with_retries(self, url: str, params: Dict[str,Any]) -> Dict[str,Any]:
        last_err: Optional[Exception] = None
        
        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.cfg.timeout_s)
                
                #Rate limit
                if resp.status_code == 429:
                    self._sleep_backoff(attempt)
                    continue
                
                #Transient server errors
                if 500 <= resp.status_code <= 599:
                    self._sleep_backoff(attempt)
                    continue
                
                # Other errors
                resp.raise_for_status()
                return resp.json()
            
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                self._sleep_backoff(attempt)
                continue
            except requests.HTTPError as e:
                #Non-retryable HTTP errors
                raise RuntimeError(
                    f"Alpaca request failed: status={resp.status_code} url={url} params={params} body={resp.text[:500]}"
                ) from e
                
        raise RuntimeError(f"Alpaca request failed after retries: url={url} params = {params}") from last_err
    
    def fetch_bars(
        self,
        symbol: str,
        start: str,
        end: str,
        timeframe: str,
        feed: Optional[str] = None,
        limit: int = 10000,
        adjustment: str = "raw",
    ) -> pd.DataFrame:
        """_summary_
        Args:
            symbol: e.g. "AAPL"
            start/end: ISO8601 string or "YYYY-MM-DD" (Alpaca accepts RFC3339/ISO8601)
            timeframe: "1Day" or "1Min"
            feed: defaults to env ALPACA_FEED (iex)
            limit: max bars per page (endpoint max varies; use high and paginate)
            adjustment: "raw" or "split" or "dividend" or "all" (provider-dependent)
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        feed = feed or self.cfg.feed
        url = f"{self.cfg.data_base_url}/v2/stocks/{symbol}/bars"
        
        params: Dict[str,Any] = {
            "start": start,
            "end": end,
            "timeframe": timeframe,
            "feed": feed,
            "limit": limit,
            "adjustment": adjustment,
        }
        
        all_rows: List[Dict[str,Any]] = []
        page_token = Optional[str] = None
        
        while True:
            if page_token:
                params["page_token"] = page_token
            else:
                params.pop("page_token", None)

            payload = self._request_with_retries(url, params=params)

            # Alpaca returns list under "bars" and pagination under "next_page_token"
            bars = payload.get("bars", [])
            all_rows.extend(bars)

            page_token = payload.get("next_page_token")
            if not page_token:
                break

        if not all_rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_rows)

        # Standardize column names (Alpaca uses: t,o,h,l,c,v)
        rename_map = {
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
        df = df.rename(columns=rename_map)

        # Keep only expected columns if present
        cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[cols]

        return df
        