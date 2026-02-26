import duckdb

# --- Inputs ---
start_ts = "2025-11-01 00:00:00+00:00"
end_ts = "2025-12-01 00:00:00+00:00"
parquet_glob = "data/curated/bars_daily/**/*.parquet"

def _connect_duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4;")
    con.execute("PRAGMA enable_object_cache=true;")
    return con

con = _connect_duckdb()

print(con.execute(f"""
DESCRIBE SELECT * FROM read_parquet('{parquet_glob}');
""").df()
)

print(con.execute(f"""
SELECT COUNT(*) AS n
FROM read_parquet('{parquet_glob}')
WHERE ts_utc >= '{start_ts}' AND ts_utc <= '{end_ts}';
""").fetchone())

import duckdb

# Define your parameters
# DuckDB will parse these strings as UTC-offset timestamps automatically
start_ts = "2025-11-01 00:00:00+00:00"
end_ts = "2025-12-01 00:00:00+00:00"
parquet_glob = "data/curated/bars_daily/**/*.parquet"

con = duckdb.connect()

# Optimized Query: No casting needed on the column side!
query = f"""
    SELECT
        symbol,
        MIN(ts_utc) AS min_ts,
        MAX(ts_utc) AS max_ts,
        COUNT(*) AS rows_total
    FROM read_parquet('{parquet_glob}')

    GROUP BY symbol
    ORDER BY symbol
"""

# Pass the parameters directly into the ? placeholders
agg = con.execute(query).df()

print(agg)

print(con.execute("""
SELECT symbol, COUNT(*)
FROM read_parquet('data/curated/bars_daily/**/*.parquet')
WHERE year = 2025
GROUP BY symbol
ORDER BY 2 DESC
LIMIT 5;
""").df())