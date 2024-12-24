import logging
import time
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
from datetime import datetime, timezone, timedelta

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

def get_clear_time(market_hours):
    """
    Calculate the time to clear all positions (5 minutes before market close).

    Args:
        market_hours (dict): Market hours data from the API.

    Returns:
        datetime: The clear time, or None if market close time is unavailable.
    """
    try:
        market_close_str = market_hours.get("marketClose", None)
        if market_close_str:
            market_close = datetime.strptime(market_close_str, "%H:%M:%S")
            clear_time = market_close - timedelta(minutes=5)
            return clear_time
    except Exception as e:
        logging.error(f"Error calculating clear time: {e}")
    return None

def clear_all_positions(access_token, positions, ticker_list, encrypted_account_number, current_price_fetcher, prices_buffers):
    """
    Close all open positions, clear the prices buffer, and update capital.

    Args:
        access_token (str): The API access token.
        positions (dict): The positions data.
        ticker_list (list): List of tickers.
        encrypted_account_number (str): Encrypted account number.
        current_price_fetcher (func): Function to fetch the current price of a ticker.
        prices_buffers (dict): Dictionary of price buffers for each ticker.

    Returns:
        None
    """
    logging.info("Clearing all positions before market close...")
    for ticker in ticker_list:
        position = positions[ticker]["position"]
        quantity = positions[ticker]["shares"] if position == "long" else abs(positions[ticker]["borrowed_shares"])
        
        if position and quantity > 0:
            current_price = current_price_fetcher(ticker, access_token)
            if current_price is None:
                logging.warning(f"Unable to fetch price for {ticker}. Skipping clearing position.")
                continue

            trade = None
            if position == "long":
                trade = {"order_type": "SELL", "symbol": ticker, "quantity": quantity}
                proceeds = quantity * current_price * (1 - transaction_cost)
                capital += proceeds
            elif position == "short":
                trade = {"order_type": "BUY_TO_COVER", "symbol": ticker, "quantity": quantity}
                cost = quantity * current_price * (1 + transaction_cost)
                capital -= cost

            if trade and place_order_with_validation(access_token, encrypted_account_number, trade):
                logging.info(f"Cleared {position.upper()} position for {ticker} with quantity {quantity}.")
                positions[ticker]["shares"] = 0
                positions[ticker]["borrowed_shares"] = 0
                positions[ticker]["entry_price"] = 0
                positions[ticker]["position"] = None

    # Clear the prices buffer for all tickers
    for ticker in prices_buffers:
        prices_buffers[ticker] = []
    logging.info("Cleared all price buffers.")
    logging.info(f"Capital after clearing all positions: {capital:.2f}")

def get_session_type(market_hours):
    """
    Determine the current session type from market hours.

    Args:
        market_hours (dict): The market hours response.

    Returns:
        str: The session type ('preMarket', 'regularMarket', 'postMarket', or None).
    """
    try:
        # Extract session hours
        session_hours = market_hours.get('equity', {}).get('EQ', {}).get('sessionHours', {})
        current_time = datetime.now(timezone.utc)

        for session_type, periods in session_hours.items():
            for period in periods:
                # Parse start and end times of the session
                start = datetime.fromisoformat(period['start']).astimezone(timezone.utc)
                end = datetime.fromisoformat(period['end']).astimezone(timezone.utc)
                
                if start <= current_time <= end:
                    return session_type
    except Exception as e:
        logging.error(f"Error determining session type: {e}")
    
    return None  # Return None if no session is active

def trade_logic():
    """Execute trading logic in real-time."""
    logger.info("hellohello everyone!")
    global capital
    total_capital_used = 0  # Track total capital usage across all positions
    logging.info("Starting trading logic...")
    encrypted_account_number = 0

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
        access_token, account_number = get_latest_token_and_account()
        prev_encrypted_account_number = encrypted_account_number 
        encrypted_account_number = get_encrypted_account_number(access_token, prev_encrypted_account_number)

        for ticker in tickers:  # Iterate through tickers
            market_hours = check_market_hours(access_token)
            logger.info(f"Market hours are: {market_hours}")
            if market_hours:
                session_type = get_session_type(market_hours)  # Extract session type
                clear_time = get_clear_time(market_hours)
                if clear_time:
                    logging.info(f"Positions will be cleared at {clear_time.time()}.")
            else:
                session_type = None  # Set to None if market_hours fetch failed

            current_time = datetime.now().time()
            # Clear all positions 5 minutes before market close
            if clear_time and current_time >= clear_time:
                clear_all_positions(access_token, positions, tickers, encrypted_account_number, fetch_market_price, prices_buffers)
                total_capital_used = 0  # Reset total capital usage
                logging.info("All positions cleared. Exiting trading loop.")
                return  # Exit trading logic after clearing all positions

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

            # Only place orders during regular market hours
            if session_type == "regularMarket":
                # Use ticker-specific buffer and positions
                prices = prices_buffers[ticker]

                # Enter trade logic
                if positions[ticker]["position"] is None:
                    decision = should_enter_trade(prices, threshold)
                    quantity = int(capital // price)

                    # Calculate the cost or market value of the new position
                    if decision == "long":
                        potential_cost = quantity * price * (1 + transaction_cost)
                    elif decision == "short":
                        potential_cost = quantity * price  # Market value for shorts
                    else:
                        potential_cost = 0

                    # Check if total capital usage exceeds $2000
                    if (total_capital_used + potential_cost) > 2000:
                        logging.warning(
                            f"Trade skipped for {ticker}. "
                            f"Entering this position would exceed the $2000 capital limit."
                        )
                        continue  # Skip this trade

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
                            total_capital_used += capital_cost
                            logging.info(
                                f"LONG entered: cost={capital_cost:.2f}, new capital={capital:.2f}, "
                                f"total capital used={total_capital_used:.2f}"
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
                            total_capital_used += quantity * price  # Add market value to capital used
                            logging.info(
                                f"SHORT entered: market value={quantity * price:.2f}, "
                                f"total capital used={total_capital_used:.2f}"
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
                            total_capital_used -= positions[ticker]["shares"] * positions[ticker]["entry_price"]
                            positions[ticker]["shares"] = 0
                            positions[ticker]["entry_price"] = 0
                            positions[ticker]["position"] = None
                            logging.info(
                                f"LONG exit: proceeds={proceeds:.2f}, new capital={capital:.2f}, "
                                f"total capital used={total_capital_used:.2f}"
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
                            total_capital_used -= positions[ticker]["borrowed_shares"] * positions[ticker]["entry_price"]
                            positions[ticker]["borrowed_shares"] = 0
                            positions[ticker]["entry_price"] = 0
                            positions[ticker]["position"] = None
                            logging.info(
                                f"SHORT exit: cost={cost:.2f}, new capital={capital:.2f}, "
                                f"total capital used={total_capital_used:.2f}"
                            )

        logger.info('End of True iteration, waiting 60s.')
        time.sleep(60)  # Wait before processing the next ticker



if __name__ == "__main__":
    trade_logic()
