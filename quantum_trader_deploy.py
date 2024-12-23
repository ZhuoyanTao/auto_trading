import logging
import time
from datetime import datetime
from mock_trader import (
    get_encrypted_account_number,
    get_latest_token_and_account,
    fetch_market_price,
    place_order_with_validation,
)
from quantum_trader3 import check_market_hours

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Trading parameters
tickers = ["RGTI", "QUBT", "QBTS", "IONQ"]
transaction_cost = 0.0005  # 0.05%
capital = 2000  # Starting capital
neighborhood_size = 60
threshold = 0.01
stop_loss_percent = 0.06

# Keep track of positions
positions = {
    ticker: {"shares": 0, "entry_price": 0, "borrowed_shares": 0} for ticker in tickers
}


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
    access_token, account_number = get_latest_token_and_account()
    encrypted_account_number = get_encrypted_account_number(access_token)

    for ticker in tickers:
        prices = []  # Price buffer for each ticker
        position = None
        entry_price = 0

        while True:
            if not check_market_hours():
                logging.info("Market closed. Waiting 60s...")
                time.sleep(60)
                continue

            price = fetch_market_price(ticker, access_token)
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
                    trade = {"order_type": "BUY", "symbol": ticker, "quantity": quantity}
                    if place_order_with_validation(
                        access_token, encrypted_account_number, trade
                    ):
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
                    trade = {
                        "order_type": "SELL_SHORT",
                        "symbol": ticker,
                        "quantity": quantity,
                    }
                    if place_order_with_validation(
                        access_token, encrypted_account_number, trade
                    ):
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
                    trade = {"order_type": "SELL", "symbol": ticker, "quantity": quantity}
                    if place_order_with_validation(
                        access_token, encrypted_account_number, trade
                    ):
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
                    trade = {
                        "order_type": "BUY_TO_COVER",
                        "symbol": ticker,
                        "quantity": quantity,
                    }
                    if place_order_with_validation(
                        access_token, encrypted_account_number, trade
                    ):
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
