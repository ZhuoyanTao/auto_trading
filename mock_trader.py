import json
import logging
import boto3
import requests

# Set up logging
logging.basicConfig(level=logging.INFO)

import requests
import logging

import logging
from datetime import datetime
import pytz

def check_market_hours():
    """Check current market session and return its type."""
    logging.debug("Checking market hours...")
    endpoint = "marketdata/v1/markets?markets=equity"
    date_today = datetime.now().strftime("%Y-%m-%d")
    data = make_api_request("GET", f"{endpoint}&date={date_today}")

    if not data:
        logging.error("Failed to fetch market hours data.")
        return None

    try:
        equity_data = data.get("equity", {}).get("EQ", {})
        sessions = equity_data.get("sessionHours", {})
        now = datetime.now(pytz.utc)  # Ensure UTC for accurate comparisons

        logging.info(f"Current UTC time: {now}")
        logging.info("Market session details fetched:")
        logging.info(equity_data)

        for session_type, periods in sessions.items():
            for session in periods:
                start = datetime.fromisoformat(session["start"]).astimezone(pytz.utc)
                end = datetime.fromisoformat(session["end"]).astimezone(pytz.utc)

                logging.info(
                    f"Session type: {session_type}, Start: {start}, End: {end}"
                )

                if start <= now <= end:
                    logging.info(f"Current session: {session_type}")
                    return session_type

        logging.info("Market is currently closed.")
        return None  # Market is closed
    except Exception as e:
        logging.error(f"Error parsing market hours: {e}")
        return None



def fetch_quotes(access_token, symbols):
    """
    Fetch quotes for a list of symbols using Schwab's API.
    """
    api_url = "https://api.schwabapi.com/quotes"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    params = {
        "symbols": ",".join(symbols),
        "fields": "quote,reference",  # Modify as needed (e.g., "all" for full response)
        "indicative": "false"         # Include indicative quotes if required
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code == 200:
            quotes = response.json()
            logging.info(f"Quotes retrieved successfully for symbols: {symbols}")
            return quotes
        else:
            logging.error(f"Failed to fetch quotes: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        logging.error(f"Error occurred while fetching quotes: {e}")
        return None


def fetch_single_quote(access_token, symbol):
    """
    Fetch quote for a single symbol using Schwab's API.
    """
    api_url = f"https://api.schwabapi.com/{symbol}/quotes"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    params = {
        "fields": "quote,reference"  # Modify as needed
    }

    try:
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code == 200:
            quote = response.json()
            logging.info(f"Quote retrieved successfully for symbol: {symbol}")
            return quote
        else:
            logging.error(f"Failed to fetch quote for {symbol}: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        logging.error(f"Error occurred while fetching quote for {symbol}: {e}")
        return None


def fetch_market_price(symbol, access_token):
    """
    Fetch the market price for a given stock symbol using the Schwab API.

    Args:
        symbol (str): The stock symbol to fetch.
        access_token (str): The API access token for authorization.

    Returns:
        float: The market price if successful, None otherwise.
    """
    url = f"https://api.schwabapi.com/marketdata/v1/{symbol}/quotes"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json"
    }
    params = {
        "fields": "quote,reference"
    }

    logging.info(f"Fetching market price for symbol: {symbol}")
    logging.debug(f"API URL: {url}")
    logging.debug(f"Headers: {headers}")
    logging.debug(f"Params: {params}")

    try:
        # Send the GET request to the API
        response = requests.get(url, headers=headers, params=params)

        # Log the status code and response for debugging
        logging.info(f"API Response Status Code: {response.status_code}")
        logging.debug(f"API Response Body: {response.text}")

        if response.status_code == 200:
            # Parse and log the response
            data = response.json()
            logging.info(f"Successfully fetched data for {symbol}: {data}")

            # Extract and return the market price
            price = data.get("quote", {}).get("lastPrice", None)
            if price is not None:
                logging.info(f"Market price for {symbol}: {price}")
            else:
                logging.warning(f"Market price not found in response for {symbol}")

            return price
        else:
            # Log the error details for troubleshooting
            logging.error(f"Failed to fetch price for {symbol}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        # Log unexpected exceptions
        logging.error(f"Unexpected error fetching price for {symbol}: {e}")
        return None


def fetch_all_orders(access_token, encrypted_account_number):
    import datetime

    api_url = f"https://api.schwabapi.com/trader/v1/accounts/{encrypted_account_number}/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    # Define a 1-day range
    today = datetime.datetime.utcnow()
    from_time = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_time = today.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    params = {
        "fromEnteredTime": from_time,
        "toEnteredTime": to_time,
        "maxResults": 1000  # Increase if needed
    }

    logging.info("Fetching all orders for the account...")
    response = requests.get(api_url, headers=headers, params=params)

    if response.status_code == 200:
        orders = response.json()
        for order in orders:
            logging.info(f"Order: {json.dumps(order, indent=2)}")
        return orders
    else:
        logging.error(
            f"Failed to fetch orders: {response.status_code}, {response.text}"
        )
        return None

# Fetch latest access token and account number from AWS Secrets Manager
def get_latest_token_and_account():
    secret_name = "SchwabAPI_Credentials"  # Replace with your secret name
    region_name = "us-east-2"  # Replace with your region

    logging.info("Fetching latest token and account from Secrets Manager...")
    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])
    access_token = secret_dict.get("access_token")
    account_number = secret_dict.get("account_number")

    logging.info(f"Retrieved account_number: {account_number[:4]}***")
    return access_token, account_number

def get_encrypted_account_number(access_token):
    api_url = "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    logging.info("Fetching encrypted account number...")
    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        accounts = response.json()
        if accounts:
            logging.info("Encrypted account number retrieved successfully.")
            return accounts[0]["hashValue"]  # Assuming the first account
        else:
            logging.error("No accounts found.")
            raise ValueError("No accounts available.")
    else:
        logging.error(
            f"Failed to fetch encrypted account number: {response.status_code}, {response.text}"
        )
        raise ValueError("Failed to fetch encrypted account number.")

def place_order_with_validation(access_token, encrypted_account_number, trade):
    # Fetch market price if necessary
    if trade["order_type"] in ["BUY", "SELL"] and "price" not in trade:
        market_price = fetch_market_price(trade["symbol"], access_token)
        if market_price:
            trade["price"] = market_price

    payload = get_order_payload(
        trade["order_type"], trade["symbol"], trade["quantity"], trade.get("price")
    )
    place_order(access_token, encrypted_account_number, payload)

# Function to place an order
def place_order(access_token, encrypted_account_number, payload):
    api_url = f"https://api.schwabapi.com/trader/v1/accounts/{encrypted_account_number}/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    logging.info(f"Placing order: {json.dumps(payload, indent=2)}")
    response = requests.post(api_url, headers=headers, json=payload)

    if response.status_code == 201:
        logging.info("Order placed successfully!")
    else:
        logging.error(
            f"Failed to place order: {response.status_code}, {response.text}"
        )

# Prepare the JSON payload for each type of trade
def get_order_payload(order_type, symbol, quantity, price=None):
    payload = {
        "complexOrderStrategyType": "NONE",
        "orderType": "LIMIT" if price else "MARKET",
        "session": "NORMAL",
        "price": str(price) if price else None,  # Include price only for LIMIT orders
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": order_type,
                "quantity": quantity,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY"
                }
            }
        ]
    }

    # Remove None values to avoid API rejection
    payload = {k: v for k, v in payload.items() if v is not None}
    return payload
    

# Main function to test placing various orders
def main():
    access_token, account_number = get_latest_token_and_account()
    encrypted_account_number = get_encrypted_account_number(access_token)
    # Example trades
    trades = [
        {"order_type": "BUY", "symbol": "RGTI", "quantity": 1},
        {"order_type": "BUY", "symbol": "COST", "quantity": 1},
        {"order_type": "SELL", "symbol": "AAPL", "quantity": 1},
        {"order_type": "SELL_SHORT", "symbol": "QUBT", "quantity": 1},
        {"order_type": "BUY_TO_COVER", "symbol": "QUBT", "quantity": 1}
    ]

    for trade in trades:
        place_order_with_validation(access_token, encrypted_account_number, trade)

    orders = fetch_all_orders(access_token, encrypted_account_number)
    if orders:
        for order in orders:
            logging.info(f"Order Status: {order['status']}, Symbol: {order['orderLegCollection'][0]['instrument']['symbol']}")

if __name__ == "__main__":
    main()
