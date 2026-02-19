from dotenv import load_dotenv
import os

load_dotenv()

required = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ALPACA_DATA_BASE_URL", "ALPACA_FEED"]
missing = [k for k in required if not os.getenv(k)]

if missing:
    raise SystemExit(f"Missing env vars: {missing}")

print("Env. OK.")