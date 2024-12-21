from concurrent.futures import ProcessPoolExecutor, as_completed
import yfinance as yf
import pandas as pd
import numpy as np
import os

# Local directory to save/load data
data_dir = "stock_data"
os.makedirs(data_dir, exist_ok=True)

# List of tickers and interval
tickers = ['RGTI', 'QUBT', 'QBTS']
interval = "5m"  # '5m' for 5-minute data
adj_close = pd.DataFrame()


def fetch_or_load_data(ticker, interval, data_dir):
    """Fetch data from Yahoo Finance or load from local file."""
    file_path = os.path.join(data_dir, f"{ticker}_{interval}.csv")
    # if os.path.exists(file_path):
    #     print(f"Loading data for {ticker} from local file...")
    #     # Skip extra rows to handle headers correctly
    #     df = pd.read_csv(file_path, skiprows=2, index_col=0)
    #     df.index = pd.to_datetime(df.index, errors='coerce')  # Parse timestamps
    #     df = df.dropna()  # Drop invalid rows with NaT index or NaN values
    #     print(f"Loaded data for {ticker}:\n{df.head()}")
    #     return df
    
    print(f"Fetching data for {ticker} from Yahoo Finance...")
    df = yf.download(ticker, interval=interval, period="5d")
    if not df.empty:
        df.to_csv(file_path)
        print(f"Data for {ticker} saved to {file_path}.")
    return df if not df.empty else None


def backtest_single_combination(args):
    """Backtest for a single combination of parameters."""
    transaction_cost = 0.0005  # 0.05% per trade
    neighborhood_size, threshold, stop_loss_percent, adj_close = args
    total_profit = 0
    trade_count = 0  # Count the number of trades executed

    for ticker in adj_close.columns:
        prices = adj_close[ticker]
        position = None  # 'long' or 'short'
        entry_price = 0
        peak_price = 0

        print(f"Testing: {ticker}, Neighborhood={neighborhood_size}, Threshold={threshold}, Stop-Loss={stop_loss_percent}")

        for i in range(neighborhood_size, len(prices)):
            neighborhood = prices.iloc[i - neighborhood_size:i]
            local_min = neighborhood.min()
            local_max = neighborhood.max()

            rise_from_min = (prices.iloc[i] - local_min) / local_min if local_min > 0 else 0
            drop_from_max = (local_max - prices.iloc[i]) / local_max if local_max > 0 else 0

            # Check for entry points
            if position is None:
                if rise_from_min > threshold:
                    position = 'long'
                    entry_price = prices.iloc[i]
                    peak_price = prices.iloc[i]
                    trade_count += 1
                    print(f"LONG ENTRY: {ticker} at {prices.index[i]}, Price={entry_price:.2f}")
                elif drop_from_max > threshold:
                    position = 'short'
                    entry_price = prices.iloc[i]
                    peak_price = prices.iloc[i]
                    trade_count += 1
                    print(f"SHORT ENTRY: {ticker} at {prices.index[i]}, Price={entry_price:.2f}")

            # Check for exit points
            elif position == 'long':
                peak_price = max(peak_price, prices.iloc[i])
                if prices.iloc[i] <= peak_price * (1 - stop_loss_percent):
                    profit = (prices.iloc[i] - entry_price) / entry_price - transaction_cost
                    total_profit += profit
                    print(f"LONG EXIT: {ticker} at {prices.index[i]}, Exit Price={prices.iloc[i]:.2f}, Profit={profit:.4f}")
                    position = None

            elif position == 'short':
                peak_price = min(peak_price, prices.iloc[i])
                if prices.iloc[i] >= peak_price * (1 + stop_loss_percent):
                    profit = (entry_price - prices.iloc[i]) / entry_price - transaction_cost
                    total_profit += profit
                    print(f"SHORT EXIT: {ticker} at {prices.index[i]}, Exit Price={prices.iloc[i]:.2f}, Profit={profit:.4f}")
                    position = None

    print(f"Completed: Neighborhood={neighborhood_size}, Threshold={threshold}, Stop-Loss={stop_loss_percent}, Total Profit={total_profit:.4f}, Trades={trade_count}")
    return neighborhood_size, threshold, stop_loss_percent, total_profit


if __name__ == '__main__':
    # Load data for each ticker
    for ticker in tickers:
        df = fetch_or_load_data(ticker, interval, data_dir)
        if df is not None:
            adj_close[ticker] = df['Close']

    # Drop tickers with no data
    adj_close = adj_close.dropna(axis=1, how='all').sort_index()
    print("Sample Adj Close Data:")
    print(adj_close.head())

    thresholds = np.arange(0.001, 0.201, 0.001)  # Thresholds: 0.1% to 5%
    stop_loss_range = np.arange(0.01, 0.21, 0.005)  # Stop-loss: 1% to 10%
    neighborhood_sizes = np.arange(10, 15, 1)  # Neighborhood sizes: 10 to 30 intervals



    # Prepare arguments for multiprocessing
    args_list = [
        (neighborhood_size, threshold, stop_loss, adj_close)
        for neighborhood_size in neighborhood_sizes
        for threshold in thresholds
        for stop_loss in stop_loss_range
    ]

    # Run backtest in parallel
    print("Starting parallel backtesting...")
    results = []
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(backtest_single_combination, args): args for args in args_list}
        for future in as_completed(futures):
            results.append(future.result())

    # Convert results to DataFrame
    results_df = pd.DataFrame(results, columns=['Neighborhood Size', 'Threshold', 'Stop-Loss', 'Profit'])
    print("\nBacktest Results:")
    print(results_df)

    # Display top results
    print("\nTop Results:")
    print(results_df.sort_values(by='Profit', ascending=False).head(10))
