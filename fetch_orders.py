# Function to fetch all orders for the account
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

# Integrate this function after placing all orders
def main():
    access_token = get_latest_token()
    encrypted_account_number = get_encrypted_account_number(access_token)

    # Example trades
    trades = [
        {"order_type": "BUY", "symbol": "AAPL", "quantity": 1, "price": 150.00},
        {"order_type": "SELL", "symbol": "TSLA", "quantity": 1, "price": 250.00},
        {"order_type": "SELL_SHORT", "symbol": "MSFT", "quantity": 1},
        {"order_type": "BUY_TO_COVER", "symbol": "GOOGL", "quantity": 1}
    ]

    for trade in trades:
        payload = get_order_payload(
            trade["order_type"], trade["symbol"], trade["quantity"], trade.get("price")
        )
        place_order(access_token, encrypted_account_number, payload)

    # Fetch all orders to validate
    orders = fetch_all_orders(access_token, encrypted_account_number)
    if orders:
        for order in orders:
            logging.info(f"Order Status: {order['status']}, Symbol: {order['orderLegCollection'][0]['instrument']['symbol']}")
