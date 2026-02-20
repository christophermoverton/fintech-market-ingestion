import duckdb
con = duckdb.connect()

df = con.execute("""
  SELECT symbol, MIN(ts_utc) AS min_ts, MAX(ts_utc) AS max_ts, COUNT(*) AS n
  FROM 'data/curated/bars_1m/**/*.parquet'
  GROUP BY symbol
  ORDER BY symbol
""").df()

print(df.head())