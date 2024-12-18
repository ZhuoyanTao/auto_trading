import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time

# Schwab API Configuration
API_BASE = "https://api.schwabapi.com"
ACCOUNT_API_BASE = f"{API_BASE}/trader/v1/accounts"
MARKET_API_BASE = f"{API_BASE}/marketdata/v1"
ACCESS_TOKEN = "your_access_token"  # Replace with your Schwab API token
ACCOUNT_NUMBER = "your_account_number"  # Replace with your account number

# Trading Parameters
tickers = ["RGTI", "QUBT", "QBTS", "IONQ"]
transaction_cost = 0.0005  # 0.05%
capital = 2000  # Starting capital
neighborhood_size = 12
threshold = 0.01
stop_loss_percent = 0.06

positions = {ticker: {"shares": 0, "entry_price": 0} for ticker in tickers}


def make_api_request(method, endpoint, params=None, payload=None):
    """Make API requests to Schwab endpoints."""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    url = f"{API_BASE}/{endpoint}"
    try:
        response = requests.request(method, url, headers=headers, params=params, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API Request Error: {e}")
        return None


def fetch_realtime_price(symbol):
    """Fetch real-time price from Schwab API."""
    endpoint = f"marketdata/v1/quotes/{symbol}"
    data = make_api_request("GET", endpoint)
    if data and symbol in data:
        return data[symbol].get("quote", {}).get("lastPrice")
    return None


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
        ]
    }
    response = make_api_request("POST", endpoint, payload=payload)
    if response:
        print(f"Order placed: {action} {quantity} shares of {symbol}")
    else:
        print(f"Failed to place order for {symbol}")


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

            if position is None:
                decision = should_enter_trade(prices, threshold)
                if decision == "long":
                    quantity = int(capital // price)
                    place_order(ticker, "BUY", quantity)
                    position = "long"
                    entry_price = price
                    positions[ticker]["shares"] += quantity
                    positions[ticker]["entry_price"] = price
                    capital -= quantity * price
                elif decision == "short":
                    quantity = int(capital // price)
                    place_order(ticker, "SELL", quantity)
                    position = "short"
                    entry_price = price
                    positions[ticker]["shares"] -= quantity
                    positions[ticker]["entry_price"] = price

            elif should_exit_trade(position, prices, entry_price, stop_loss_percent):
                quantity = positions[ticker]["shares"]
                if position == "long":
                    place_order(ticker, "SELL", quantity)
                    capital += quantity * price
                elif position == "short":
                    place_order(ticker, "BUY", abs(quantity))
                    capital -= quantity * price

                positions[ticker]["shares"] = 0
                positions[ticker]["entry_price"] = 0
                position = None

            time.sleep(60)

if __name__ == "__main__":
    trade_logic()
