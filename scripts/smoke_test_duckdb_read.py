import duckdb
con = duckdb.connect()
df = con.execute("""
  SELECT symbol, min(ts_utc) AS min_ts, max(ts_utc) AS max_ts, count(*) AS n
  FROM 'data/curated/bars_daily/**/*.parquet'
  GROUP BY symbol
  ORDER BY symbol
""").df()
print(df.head())
