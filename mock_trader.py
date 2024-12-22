import boto3
import requests
import json
import time

# Replace these constants if needed:
SECRET_NAME = "SchwabAPI_Credentials"
REGION_NAME = "us-east-2"
API_BASE = "https://api.schwabapi.com"


def retrieve_schwab_credentials():
    """
    Grab the latest 'access_token' and 'account_number' from Secrets Manager.
    """
    client = boto3.client("secretsmanager", region_name=REGION_NAME)
    response = client.get_secret_value(SecretId=SECRET_NAME)
    secret_dict = json.loads(response["SecretString"])

    access_token = secret_dict.get("access_token")
    account_number = secret_dict.get("account_number")
    if not access_token or not account_number:
        raise ValueError("Secrets missing 'access_token' or 'account_number'.")
    return access_token, account_number


def place_order(account_number, access_token, symbol, instruction, quantity):
    """
    Place an order (BUY, SELL, SELL_SHORT, BUY_TO_COVER) for a given quantity of symbol.
    """
    # For a forced market order:
    payload = {
        "orderType": "MARKET",
        "session": "NORMAL",  # "NORMAL" session might queue if market is closed
        "duration": "DAY",  # Good for today's session
        "orderLegCollection": [
            {
                "instrument": {"symbol": symbol, "type": "EQUITY"},
                "instruction": instruction,  # e.g. "BUY", "SELL_SHORT"
                "quantity": quantity,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{API_BASE}/trader/v1/accounts/{account_number}/orders"

    print(f"Placing order: {instruction} {quantity} share(s) of {symbol} ...")
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 200 or resp.status_code == 201:
        print(f"Order placed successfully. Response:\n{resp.json()}")
    else:
        print(f"Order failed with status={resp.status_code}, reason={resp.reason}")
        print("Response text:", resp.text)


def main():
    # Retrieve credentials from Secrets Manager
    access_token, account_number = retrieve_schwab_credentials()

    # Example #1: BUY 1 share of "SCHX"
    place_order(
        account_number, access_token, symbol="SCHX", instruction="BUY", quantity=1
    )

    # Just wait a few seconds so you can see them as separate attempts in logs
    time.sleep(5)

    # Example #2: SELL_SHORT 1 share of "SCHX"
    place_order(
        account_number,
        access_token,
        symbol="SCHX",
        instruction="SELL_SHORT",
        quantity=1,
    )


if __name__ == "__main__":
    main()
