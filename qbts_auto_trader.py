import requests
import time
import json
import os
from datetime import datetime

# Constants
CLIENT_ID = "wLMziC17JM03DaUMFpeT6AOglG0uo4CX"  # Replace with your Schwab App Client ID
CLIENT_SECRET = "mMxGRw4zzCSi13Oz"  # Replace with your Client Secret
REFRESH_TOKEN = "your-refresh-token"  # Replace with your Refresh Token
REDIRECT_URI = "https://127.0.0.1"
TRADE_SYMBOL = "QBTS"  # Stock to trade
TRADE_AMOUNT = 500.0  # Initial fixed trading amount
BALANCE_FILE = "balance.json"  # File to track balance and trades

# Schwab OAuth Endpoint
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

# Initialize balance tracking
def initialize_balance():
    if not os.path.exists(BALANCE_FILE):
        with open(BALANCE_FILE, "w") as f:
            json.dump({"balance": TRADE_AMOUNT, "trades": []}, f)

def load_balance():
    with open(BALANCE_FILE, "r") as f:
        return json.load(f)

def save_balance(data):
    with open(BALANCE_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Get access token
def get_access_token():
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise Exception(f"Error obtaining access token: {response.text}")

# Fetch the current price of QBTS
def fetch_stock_price(access_token):
    url = f"https://api.schwabapi.com/v1/quotes/{TRADE_SYMBOL}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        price = response.json()["lastPrice"]  # Replace key with exact API response
        return float(price)
    else:
        raise Exception(f"Error fetching stock price: {response.text}")

# Place trade (BUY or SHORT)
def place_trade(access_token, action, quantity):
    url = f"https://api.schwabapi.com/v1/accounts/your_account_id/orders"  # Replace 'your_account_id'
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "symbol": TRADE_SYMBOL,
        "action": action,  # BUY or SHORT
        "quantity": quantity,
        "orderType": "MARKET",
        "duration": "DAY",
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 201:
        print(f"Trade successful: {action} {quantity} shares of {TRADE_SYMBOL}")
        return True
    else:
        print(f"Trade failed: {response.text}")
        return False

# Main logic
def trading_bot():
    print("Starting QBTS Trading Bot...\n")
    initialize_balance()
    data = load_balance()
    balance = data["balance"]
    access_token = get_access_token()
    last_price = None

    while True:
        try:
            current_price = fetch_stock_price(access_token)
            print(f"{datetime.now()}: Current QBTS Price: ${current_price:.2f}")

            # Only trade if we have a previous price to compare with
            if last_price:
                price_change = ((current_price - last_price) / last_price) * 100
                print(f"Price Change: {price_change:.2f}%")

                if price_change > 3:  # Buy condition
                    shares_to_buy = round(balance / current_price, 2)
                    if place_trade(access_token, "BUY", shares_to_buy):
                        balance -= shares_to_buy * current_price
                        data["trades"].append(
                            {"action": "BUY", "price": current_price, "shares": shares_to_buy, "timestamp": str(datetime.now())}
                        )
                        print(f"Bought {shares_to_buy} shares at ${current_price:.2f}")
                
                elif price_change < -3:  # Short condition
                    shares_to_short = round(balance / current_price, 2)
                    if place_trade(access_token, "SHORT", shares_to_short):
                        balance += shares_to_short * current_price
                        data["trades"].append(
                            {"action": "SHORT", "price": current_price, "shares": shares_to_short, "timestamp": str(datetime.now())}
                        )
                        print(f"Shorted {shares_to_short} shares at ${current_price:.2f}")

                # Update balance file
                data["balance"] = round(balance, 2)
                save_balance(data)

            last_price = current_price
            print(f"Updated Balance: ${balance:.2f}\n")
            time.sleep(300)  # Wait 5 minutes before checking again

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)  # Wait 1 minute on error and retry

# Run the bot
if __name__ == "__main__":
    trading_bot()
