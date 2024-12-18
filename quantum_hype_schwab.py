import requests
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# Constants for API
API_BASE = "https://api.schwabapi.com/marketdata/v1"
ACCESS_TOKEN = "your_access_token"
RETRY_COUNT = 3
RETRY_DELAY = 5  # seconds

def make_api_request(method, endpoint, params=None, payload=None, retries=RETRY_COUNT):
    """
    Make an API request with error handling and retries.

    Args:
        method (str): HTTP method ('GET', 'POST', etc.)
        endpoint (str): API endpoint path
        params (dict): Query parameters
        payload (dict): JSON body payload
        retries (int): Number of retries for recoverable errors

    Returns:
        dict: Parsed JSON response or None if failed
    """
    url = f"{API_BASE}/{endpoint}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    for attempt in range(retries):
        try:
            response = requests.request(
                method=method, url=url, headers=headers, params=params, json=payload
            )

            # Log request details for debugging
            logging.info(f"Request {method} {url} | Params: {params} | Payload: {payload}")

            # Check response status
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logging.error("Unauthorized: Invalid or expired token. Refresh required.")
                # Handle token refresh here if necessary
                break
            elif response.status_code == 429:
                logging.warning("Rate limit hit. Retrying after delay...")
                time.sleep(RETRY_DELAY)
            else:
                logging.error(
                    f"Error: HTTP {response.status_code} | Details: {response.json()}"
                )
                break

        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed: {e}")
            time.sleep(RETRY_DELAY)

    logging.error("Max retries reached. Request failed.")
    return None


def fetch_quotes(symbols):
    """
    Fetch real-time quotes for a list of symbols.

    Args:
        symbols (list): List of stock symbols

    Returns:
        dict: Quotes data for the symbols
    """
    try:
        symbols_param = ",".join(symbols)
        response = make_api_request("GET", "quotes", params={"symbols": symbols_param})
        if response:
            return response
        else:
            logging.error(f"Failed to fetch quotes for symbols: {symbols}")
    except Exception as e:
        logging.error(f"Unexpected error in fetch_quotes: {e}")
    return {}


def place_order(account_number, symbol, action, quantity):
    """
    Place an order for a specific account.

    Args:
        account_number (str): Encrypted account number
        symbol (str): Stock symbol
        action (str): "BUY" or "SELL"
        quantity (int): Number of shares

    Returns:
        dict: Order confirmation or error details
    """
    try:
        payload = {
            "session": "NORMAL",
            "duration": "DAY",
            "orderType": "MARKET",
            "orderLegCollection": [
                {
                    "instrument": {"symbol": symbol, "type": "EQUITY"},
                    "instruction": action,
                    "quantity": quantity,
                }
            ],
        }
        response = make_api_request(
            "POST", f"accounts/{account_number}/orders", payload=payload
        )
        if response:
            logging.info(f"Order placed: {response}")
            return response
        else:
            logging.error(f"Failed to place order for {symbol}")
    except Exception as e:
        logging.error(f"Unexpected error in place_order: {e}")
    return {}


# Example usage
if __name__ == "__main__":
    # Replace with real values
    account_number = "your_account_number"
    symbols = ["AAPL", "TSLA"]
    
    # Fetch quotes
    quotes = fetch_quotes(symbols)
    if quotes:
        logging.info(f"Quotes: {quotes}")
    
    # Place an order
    order_response = place_order(account_number, "AAPL", "BUY", 10)
    if order_response:
        logging.info(f"Order Response: {order_response}")
