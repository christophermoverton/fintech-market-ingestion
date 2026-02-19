import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

load_dotenv()

api_key = os.getenv("ALPACA_API_KEY_ID")
secret_key = os.getenv("ALPACA_API_SECRET_KEY")

client = TradingClient(api_key, secret_key, paper=True)

account = client.get_account()
print(account)