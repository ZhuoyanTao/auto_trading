import boto3
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time

# Constant base URLs
API_BASE = "https://api.schwabapi.com"
ACCOUNT_API_BASE = f"{API_BASE}/trader/v1/accounts"
MARKET_API_BASE = f"{API_BASE}/marketdata/v1"

# Trading Parameters
tickers = ["RGTI", "QUBT", "QBTS", "IONQ"]  # removed IONQ in comment
transaction_cost = 0.0005  # 0.05%
capital = 2000  # Starting capital
neighborhood_size = 12
threshold = 0.01
stop_loss_percent = 0.06

# Keep track of positions
positions = {
    ticker: {"shares": 0, "entry_price": 0, "borrowed_shares": 0} for ticker in tickers
}


def get_latest_token_and_account():
    """
    Always fetch the latest from Secrets Manager each time this is called.
    """
    secret_name = "SchwabAPI_Credentials"  # Replace as needed
    region_name = "us-east-2"  # Replace as needed
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])
    return secret_dict.get("access_token"), secret_dict.get("account_number")


# Global variables (populated dynamically)
_, ACCOUNT_NUMBER = get_latest_token_and_account()


def make_api_request(method, endpoint, params=None, payload=None):
    """Make API requests to Schwab endpoints with retries."""
    ACCESS_TOKEN, _ = get_latest_token_and_account()
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    url = f"{API_BASE}/{endpoint}"
    retries = 3
    for attempt in range(retries):
        try:
            response = requests.request(
                method, url, headers=headers, params=params, json=payload
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                print(f"API error: {e}. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"API error: {e}. Exceeded retry limit.")
                return None


def fetch_realtime_price(symbol):
    """Fetch real-time price from Schwab API."""
    endpoint = f"marketdata/v1/quotes/{symbol}"
    data = make_api_request("GET", endpoint)
    if data and symbol in data:
        return data[symbol].get("quote", {}).get("lastPrice")
    return None


def check_market_hours():
    """Check if the market is open."""
    endpoint = "marketdata/v1/markets/equity"
    data = make_api_request("GET", endpoint)
    if data:
        sessions = data.get("equity", {}).get("EQ", {}).get("sessionHours", {})
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for session_type in ["preMarket", "regularMarket", "postMarket"]:
            for session in sessions.get(session_type, []):
                if session["start"] <= now <= session["end"]:
                    return True
    return False


def place_order(symbol, action, quantity):
    """Place a market order."""
    endpoint = f"trader/v1/accounts/{ACCOUNT_NUMBER}/orders"
    payload = {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderLegCollection": [
            {
                "instrument": {"symbol": symbol, "type": "EQUITY"},
                "instruction": action,  # BUY or SELL
                "quantity": quantity,
            }
        ],
    }
    response = make_api_request("POST", endpoint, payload=payload)
    if response:
        print(f"Order placed: {action} {quantity} shares of {symbol}")
        return True
    print(f"Failed to place order for {symbol}")
    return False


def should_enter_trade(prices, threshold):
    """Determine if entry conditions are met."""
    neighborhood = prices[-neighborhood_size:]
    local_min = min(neighborhood)
    local_max = max(neighborhood)

    rise_from_min = (prices[-1] - local_min) / local_min if local_min > 0 else 0
    drop_from_max = (local_max - prices[-1]) / local_max if local_max > 0 else 0

    if rise_from_min > threshold:
        return "long"
    elif drop_from_max > threshold:
        return "short"
    return None


def should_exit_trade(position, prices, entry_price, stop_loss_percent):
    """Determine if exit conditions are met."""
    peak_price = max(prices) if position == "long" else min(prices)
    if position == "long" and prices[-1] <= peak_price * (1 - stop_loss_percent):
        return True
    elif position == "short" and prices[-1] >= peak_price * (1 + stop_loss_percent):
        return True
    return False


def trade_logic():
    """Execute trading logic in real-time."""
    global capital
    for ticker in tickers:
        prices = []  # Price buffer for each ticker
        position = None
        entry_price = 0

        while True:
            if not check_market_hours():
                print("Market closed. Waiting...")
                time.sleep(60)
                continue

            price = fetch_realtime_price(ticker)
            if price is None:
                print(f"Price unavailable for {ticker}, skipping...")
                time.sleep(60)
                continue

            prices.append(price)
            if len(prices) > neighborhood_size:
                prices.pop(0)  # Keep buffer size fixed

            print(f"{datetime.now()} | {ticker} | Current Price: {price:.2f}")

            if len(prices) < neighborhood_size:
                time.sleep(60)
                continue

            # Enter trade logic
            if position is None:
                decision = should_enter_trade(prices, threshold)
                quantity = int(capital // price)

                if decision == "long" and quantity > 0:
                    if place_order(ticker, "BUY", quantity):
                        position = "long"
                        entry_price = price
                        positions[ticker]["shares"] += quantity
                        positions[ticker]["entry_price"] = price
                        capital -= quantity * price * (1 + transaction_cost)

                elif decision == "short" and quantity > 0:
                    if place_order(ticker, "SELL_SHORT", quantity):
                        position = "short"
                        entry_price = price
                        positions[ticker]["borrowed_shares"] += quantity
                        positions[ticker]["entry_price"] = price
                        capital += (
                            quantity * price * (1 - transaction_cost)
                        )  # Add proceeds

            # Exit trade logic
            elif position == "long":
                if should_exit_trade(position, prices, entry_price, stop_loss_percent):
                    quantity = positions[ticker]["shares"]
                    if place_order(ticker, "SELL", quantity):
                        capital += quantity * price * (1 - transaction_cost)
                        positions[ticker]["shares"] = 0
                        positions[ticker]["entry_price"] = 0
                        position = None

            elif position == "short":
                if should_exit_trade(position, prices, entry_price, stop_loss_percent):
                    quantity = abs(positions[ticker]["borrowed_shares"])
                    if place_order(ticker, "BUY_TO_COVER", quantity):
                        capital -= (
                            quantity * price * (1 + transaction_cost)
                        )  # Repay borrowed shares
                        positions[ticker]["borrowed_shares"] = 0
                        positions[ticker]["entry_price"] = 0
                        position = None

            time.sleep(60)


if __name__ == "__main__":
    trade_logic()
