from src.ingestion.alpaca_client import AlpacaMarketDataClient

client = AlpacaMarketDataClient.from_env()

df = client.fetch_bars(
    symbol="AAPL",
    start="2025-01-01T00:00:00Z",
    end="2025-02-01T00:00:00Z",
    timeframe="1Day",
)

print(df.head())
print("rows:", len(df))
