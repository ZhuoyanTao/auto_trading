from concurrent.futures import ProcessPoolExecutor
import yfinance as yf
import pandas as pd
import numpy as np
import os

# Local directory to save/load data
data_dir = "stock_data"
os.makedirs(data_dir, exist_ok=True)

# List of tickers and interval
tickers = ['RGTI', 'QUBT', 'QBTS', 'IONQ']
interval = "5m"  # '5m' for 5-minute data
adj_close = pd.DataFrame()


def fetch_or_load_data(ticker, interval, data_dir):
    file_path = os.path.join(data_dir, f"{ticker}_{interval}.csv")
    if os.path.exists(file_path):
        print(f"Loading data for {ticker} from local file...")
        df = pd.read_csv(file_path, index_col=0)
        df.index = pd.to_datetime(df.index, format='%Y-%m-%d %H:%M:%S', errors='coerce')
        df = df.dropna().apply(pd.to_numeric, errors='coerce').dropna()
        return df
    else:
        print(f"Fetching data for {ticker} from Yahoo Finance...")
        df = yf.download(ticker, interval=interval, period="5d")
        if not df.empty:
            df.to_csv(file_path)
        return df if not df.empty else None


def backtest_single_combination(args):
    """Backtest for a single combination of parameters."""
    neighborhood_size, threshold, stop_loss_percent, adj_close = args
    total_profit = 0
    for ticker in adj_close.columns:
        prices = adj_close[ticker]
        position = None  # 'long' or 'short'
        entry_price = 0
        peak_price = 0

        for i in range(neighborhood_size, len(prices)):
            neighborhood = prices.iloc[i - neighborhood_size:i]
            local_min = neighborhood.min()
            local_max = neighborhood.max()

            rise_from_min = (prices.iloc[i] - local_min) / local_min
            drop_from_max = (local_max - prices.iloc[i]) / local_max

            if position is None:
                if rise_from_min > threshold:
                    position = 'long'
                    entry_price = prices.iloc[i]
                    peak_price = prices.iloc[i]
                elif drop_from_max > threshold:
                    position = 'short'
                    entry_price = prices.iloc[i]
                    peak_price = prices.iloc[i]
            elif position == 'long' and prices.iloc[i] <= peak_price * (1 - stop_loss_percent):
                total_profit += (prices.iloc[i] - entry_price) / entry_price
                position = None
            elif position == 'short' and prices.iloc[i] >= peak_price * (1 + stop_loss_percent):
                total_profit += (entry_price - prices.iloc[i]) / entry_price
                position = None

    return neighborhood_size, threshold, stop_loss_percent, total_profit


if __name__ == '__main__':
    # Load data for each ticker
    for ticker in tickers:
        df = fetch_or_load_data(ticker, interval, data_dir)
        if df is not None:
            adj_close[ticker] = df['Close']

    # Drop tickers with no data
    adj_close = adj_close.dropna(axis=1, how='all').sort_index()

    # Parameters
    thresholds = np.arange(0.005, 0.10, 0.005)
    stop_loss_range = np.arange(0.05, 0.16, 0.01)
    neighborhood_sizes = np.arange(1, 100, 1)

    # Prepare arguments for multiprocessing
    args_list = [
        (neighborhood_size, threshold, stop_loss, adj_close)
        for neighborhood_size in neighborhood_sizes
        for threshold in thresholds
        for stop_loss in stop_loss_range
    ]

    # Run backtest in parallel
    print("Starting parallel backtesting...")
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(backtest_single_combination, args_list))

    # Convert results to DataFrame
    results_df = pd.DataFrame(results, columns=['Neighborhood Size', 'Threshold', 'Stop-Loss', 'Profit'])
    print("\nBacktest Results:")
    print(results_df)

    # Display top results
    print("\nTop Results:")
    print(results_df.sort_values(by='Profit', ascending=False).head(10))
