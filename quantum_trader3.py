import boto3
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import logging

# Set up Python logging (basicConfig for simplicity, or you can use loguru, etc.)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

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

    logging.info("Fetching latest token and account from Secrets Manager...")
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])
    access_token = secret_dict.get("access_token")
    account_number = secret_dict.get("account_number")

    logging.info(f"Retrieved account_number: {account_number[:4]}***")  # Partial mask
    return access_token, account_number


# Global variables (populated dynamically)
_, ACCOUNT_NUMBER = get_latest_token_and_account()


def make_api_request(method, endpoint, params=None, payload=None):
    """Make API requests to Schwab endpoints with retries."""
    ACCESS_TOKEN, _ = get_latest_token_and_account()
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    url = f"{API_BASE}/{endpoint}"
    retries = 3

    logging.debug(
        f"Preparing {method} request to {url} with payload={payload} and params={params}"
    )
    for attempt in range(retries):
        try:
            response = requests.request(
                method, url, headers=headers, params=params, json=payload
            )
            response.raise_for_status()
            logging.debug(f"Response from {endpoint}: {response.text}")
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                logging.warning(
                    f"API error (attempt {attempt+1}/{retries}): {e}. Retrying in 5s..."
                )
                time.sleep(5)
            else:
                logging.error(f"API error: {e}. Exceeded retry limit.")
                return None


def fetch_realtime_price(symbol):
    """Fetch real-time price from Schwab API."""
    logging.info(f"Fetching real-time price for {symbol}...")
    endpoint = f"marketdata/v1/quotes/{symbol}"
    data = make_api_request("GET", endpoint)
    if data and symbol in data:
        price = data[symbol].get("quote", {}).get("lastPrice")
        logging.info(f"Current price for {symbol}: {price}")
        return price
    else:
        logging.warning(f"No price data found for {symbol}.")
        return None


def check_market_hours():
    """Check if the market is open."""
    logging.debug("Checking if market is open...")
    endpoint = "marketdata/v1/markets/equity"
    data = make_api_request("GET", endpoint)
    if data:
        sessions = data.get("equity", {}).get("EQ", {}).get("sessionHours", {})
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for session_type in ["preMarket", "regularMarket", "postMarket"]:
            for session in sessions.get(session_type, []):
                if session["start"] <= now <= session["end"]:
                    logging.info(f"Market is currently in {session_type}.")
                    return True
    logging.info("Market is closed.")
    return False


def place_order(symbol, action, quantity):
    """Place a market order."""
    logging.info(f"Placing order: {action} {quantity} shares of {symbol}...")
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
        logging.info(
            f"Order placed successfully: {action} {quantity} shares of {symbol}"
        )
        return True
    logging.error(f"Failed to place order for {symbol}")
    return False


def should_enter_trade(prices, threshold):
    """Determine if entry conditions are met."""
    neighborhood = prices[-neighborhood_size:]
    local_min = min(neighborhood)
    local_max = max(neighborhood)

    current_price = prices[-1]
    rise_from_min = (current_price - local_min) / local_min if local_min > 0 else 0
    drop_from_max = (local_max - current_price) / local_max if local_max > 0 else 0

    logging.debug(
        f"[TradeEntryCheck] lastPrice={current_price}, localMin={local_min}, localMax={local_max}, "
        f"riseFromMin={rise_from_min:.4f}, dropFromMax={drop_from_max:.4f}"
    )

    if rise_from_min > threshold:
        logging.info(
            f"Entry condition: LONG (rise_from_min={rise_from_min:.4f} > threshold={threshold})"
        )
        return "long"
    elif drop_from_max > threshold:
        logging.info(
            f"Entry condition: SHORT (drop_from_max={drop_from_max:.4f} > threshold={threshold})"
        )
        return "short"
    else:
        return None


def should_exit_trade(position, prices, entry_price, stop_loss_percent):
    """Determine if exit conditions are met."""
    peak_price = max(prices) if position == "long" else min(prices)
    current_price = prices[-1]
    if position == "long":
        if current_price <= peak_price * (1 - stop_loss_percent):
            logging.info(
                f"Exit condition: LONG STOP-LOSS triggered. current_price={current_price:.2f}, peak_price={peak_price:.2f}"
            )
            return True
    elif position == "short":
        if current_price >= peak_price * (1 + stop_loss_percent):
            logging.info(
                f"Exit condition: SHORT STOP-LOSS triggered. current_price={current_price:.2f}, minPrice={peak_price:.2f}"
            )
            return True
    return False


def trade_logic():
    """Execute trading logic in real-time."""
    global capital
    logging.info("Starting trading logic...")
    for ticker in tickers:
        prices = []  # Price buffer for each ticker
        position = None
        entry_price = 0

        while True:
            if not check_market_hours():
                logging.info("Market closed. Waiting 60s...")
                time.sleep(60)
                continue

            price = fetch_realtime_price(ticker)
            if price is None:
                logging.warning(f"Price unavailable for {ticker}, skipping for 60s.")
                time.sleep(60)
                continue

            prices.append(price)
            if len(prices) > neighborhood_size:
                prices.pop(0)  # Keep buffer size fixed

            logging.info(f"{datetime.now()} | {ticker} | Current Price: {price:.2f}")

            if len(prices) < neighborhood_size:
                logging.info(
                    f"Not enough price data for {ticker} yet. Need {neighborhood_size}, have {len(prices)}."
                )
                time.sleep(60)
                continue

            # Enter trade logic
            if position is None:
                decision = should_enter_trade(prices, threshold)
                quantity = int(capital // price)

                if decision == "long" and quantity > 0:
                    logging.info(
                        f"Attempting a LONG position for {ticker} with quantity={quantity}..."
                    )
                    if place_order(ticker, "BUY", quantity):
                        position = "long"
                        entry_price = price
                        positions[ticker]["shares"] += quantity
                        positions[ticker]["entry_price"] = price
                        capital_cost = quantity * price * (1 + transaction_cost)
                        capital -= capital_cost
                        logging.info(
                            f"LONG entered: cost={capital_cost:.2f}, new capital={capital:.2f}"
                        )

                elif decision == "short" and quantity > 0:
                    logging.info(
                        f"Attempting a SHORT position for {ticker} with quantity={quantity}..."
                    )
                    if place_order(ticker, "SELL_SHORT", quantity):
                        position = "short"
                        entry_price = price
                        positions[ticker]["borrowed_shares"] += quantity
                        positions[ticker]["entry_price"] = price
                        proceeds = quantity * price * (1 - transaction_cost)
                        capital += proceeds
                        logging.info(
                            f"SHORT entered: proceeds={proceeds:.2f}, new capital={capital:.2f}"
                        )

            # Exit trade logic
            elif position == "long":
                if should_exit_trade(position, prices, entry_price, stop_loss_percent):
                    quantity = positions[ticker]["shares"]
                    logging.info(
                        f"Exiting LONG position for {ticker} with quantity={quantity}..."
                    )
                    if place_order(ticker, "SELL", quantity):
                        proceeds = quantity * price * (1 - transaction_cost)
                        capital += proceeds
                        positions[ticker]["shares"] = 0
                        positions[ticker]["entry_price"] = 0
                        position = None
                        logging.info(
                            f"LONG exit: proceeds={proceeds:.2f}, new capital={capital:.2f}"
                        )

            elif position == "short":
                if should_exit_trade(position, prices, entry_price, stop_loss_percent):
                    quantity = abs(positions[ticker]["borrowed_shares"])
                    logging.info(
                        f"Exiting SHORT position for {ticker} with quantity={quantity}..."
                    )
                    if place_order(ticker, "BUY_TO_COVER", quantity):
                        cost = quantity * price * (1 + transaction_cost)
                        capital -= cost
                        positions[ticker]["borrowed_shares"] = 0
                        positions[ticker]["entry_price"] = 0
                        position = None
                        logging.info(
                            f"SHORT exit: cost={cost:.2f}, new capital={capital:.2f}"
                        )

            time.sleep(60)


if __name__ == "__main__":
    trade_logic()
