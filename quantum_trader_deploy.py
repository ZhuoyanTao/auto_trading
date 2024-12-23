import logging
import time
from datetime import datetime
from mock_trader import (
    get_encrypted_account_number,
    get_latest_token_and_account,
    fetch_market_price,
    place_order_with_validation,
    check_market_hours,
    make_api_request
)

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

# Configure RotatingFileHandler
file_size_handler = RotatingFileHandler(
    "trader_log.log", maxBytes=5 * 1024 * 1024, backupCount=3
)  # 5MB per file, keep 3 backups
file_size_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_size_handler.setFormatter(file_size_formatter)

# Configure TimedRotatingFileHandler
daily_rotation_handler = TimedRotatingFileHandler(
    "trader_log_daily.log", when="midnight", interval=1, backupCount=7
)  # Rotate daily, keep logs for 7 days
daily_rotation_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
daily_rotation_handler.setFormatter(daily_rotation_formatter)

# Set up the logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_size_handler)
logger.addHandler(daily_rotation_handler)

# Example usage
logger.info("Logger initialized with both file size and daily rotation handlers.")


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

    # Initialize price buffers and positions for each ticker
    prices_buffers = {ticker: [] for ticker in tickers}
    positions = {
        ticker: {
            "shares": 0,
            "borrowed_shares": 0,
            "entry_price": 0,
            "position": None  # Tracks "long", "short", or None
        }
        for ticker in tickers
    }

    while True:  # Continuous trading loop
        for ticker in tickers:  # Iterate through tickers
            session_type = check_market_hours(access_token)
            if not session_type:
                logging.info("Market is closed. Waiting 60s...")
                continue

            price = fetch_market_price(ticker, access_token)
            if price is None:
                logging.warning(f"Price unavailable for {ticker}, skipping for 60s.")
                continue

            # Update the price buffer for the current ticker
            prices_buffers[ticker].append(price)
            if len(prices_buffers[ticker]) > neighborhood_size:
                prices_buffers[ticker].pop(0)  # Keep buffer size fixed

            logging.info(
                f"{datetime.now()} | {ticker} | Current Price: {price:.2f} | Session: {session_type}"
            )

            # Skip trading logic if not enough data
            if len(prices_buffers[ticker]) < neighborhood_size:
                logging.info(
                    f"Not enough price data for {ticker} yet. Need {neighborhood_size}, have {len(prices_buffers[ticker])}."
                )
                continue

            # Only place orders during regular market hours
            if session_type == "regularMarket":
                # Use ticker-specific buffer and positions
                prices = prices_buffers[ticker]

                # Enter trade logic
                if positions[ticker]["position"] is None:
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
                            positions[ticker]["shares"] += quantity
                            positions[ticker]["entry_price"] = price
                            positions[ticker]["position"] = "long"
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
                            positions[ticker]["borrowed_shares"] += quantity
                            positions[ticker]["entry_price"] = price
                            positions[ticker]["position"] = "short"
                            proceeds = quantity * price * (1 - transaction_cost)
                            capital += proceeds
                            logging.info(
                                f"SHORT entered: proceeds={proceeds:.2f}, new capital={capital:.2f}"
                            )

                # Exit trade logic
                elif positions[ticker]["position"] == "long":
                    if should_exit_trade("long", prices, positions[ticker]["entry_price"], stop_loss_percent):
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
                            positions[ticker]["position"] = None
                            logging.info(
                                f"LONG exit: proceeds={proceeds:.2f}, new capital={capital:.2f}"
                            )

                elif positions[ticker]["position"] == "short":
                    if should_exit_trade("short", prices, positions[ticker]["entry_price"], stop_loss_percent):
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
                            positions[ticker]["position"] = None
                            logging.info(
                                f"SHORT exit: cost={cost:.2f}, new capital={capital:.2f}"
                            )
        logger.info('End of True iteration, waiting 60s.')
        time.sleep(60)  # Wait before processing the next ticker



if __name__ == "__main__":
    trade_logic()
