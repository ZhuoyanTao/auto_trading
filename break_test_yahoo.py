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
        df = pd.read_csv(file_path, index_col=0)  # Load the CSV file
        df.index = pd.to_datetime(df.index, errors='coerce')  # Convert index to datetime
        df = df.dropna()  # Drop invalid rows with NaT index

        # Convert all columns to numeric, forcing errors to NaN and dropping non-numeric rows
        df = df.apply(pd.to_numeric, errors='coerce')
        df = df.dropna(how="any")  # Drop rows with non-numeric values

        print(f"First rows of cleaned {file_path}:\n{df.head()}")
        return df
    else:
        print(f"Fetching data for {ticker} from Yahoo Finance...")
        df = yf.download(ticker, interval=interval, period="5d")  # Fetch fresh data
        if not df.empty:
            df.to_csv(file_path)  # Save valid data
            print(f"Data saved to {file_path}")
        else:
            print(f"No data fetched for {ticker}. Skipping...")
        return df if not df.empty else None



# Load data for each ticker
for ticker in tickers:
    df = fetch_or_load_data(ticker, interval, data_dir)
    if df is not None:
        adj_close[ticker] = df['Close']

# Drop tickers with no data
adj_close = adj_close.dropna(axis=1, how='all')

# Sort data to ensure correct time order
adj_close = adj_close.sort_index()

def backtest_with_neighborhood_sizes(adj_close, thresholds, stop_loss_range, neighborhood_sizes):
    results = []
    intraday_profits = {}  # Dictionary to store intraday gains/losses

    for neighborhood_size in neighborhood_sizes:  # Iterate over neighborhood sizes
        for threshold in thresholds:
            for stop_loss_percent in stop_loss_range:
                total_profit = 0
                intraday_profits.clear()
                for ticker in adj_close.columns:
                    prices = adj_close[ticker]
                    position = None  # 'long' or 'short'
                    entry_price = 0
                    peak_price = 0

                    for i in range(neighborhood_size, len(prices)):
                        timestamp = prices.index[i]
                        neighborhood = prices.iloc[i - neighborhood_size:i]

                        # Find local min and max in the neighborhood
                        local_min = neighborhood.min()
                        local_max = neighborhood.max()

                        # Percentage rise/drop from local min/max
                        rise_from_min = (prices.iloc[i] - local_min) / local_min
                        drop_from_max = (local_max - prices.iloc[i]) / local_max

                        # Look for buy/short entry signals
                        if position is None:
                            if rise_from_min > threshold:  # Buy signal
                                position = 'long'
                                entry_price = prices.iloc[i]
                                peak_price = prices.iloc[i]
                            elif drop_from_max > threshold:  # Short signal
                                position = 'short'
                                entry_price = prices.iloc[i]
                                peak_price = prices.iloc[i]

                        elif position == 'long':  # Long position
                            peak_price = max(peak_price, prices.iloc[i])
                            if prices.iloc[i] <= peak_price * (1 - stop_loss_percent):
                                profit = (prices.iloc[i] - entry_price) / entry_price
                                total_profit += profit
                                intraday_profits[timestamp] = intraday_profits.get(timestamp, 0) + profit
                                position = None

                        elif position == 'short':  # Short position
                            peak_price = min(peak_price, prices.iloc[i])
                            if prices.iloc[i] >= peak_price * (1 + stop_loss_percent):
                                profit = (entry_price - prices.iloc[i]) / entry_price
                                total_profit += profit
                                intraday_profits[timestamp] = intraday_profits.get(timestamp, 0) + profit
                                position = None

                # Save the overall results for this threshold, stop-loss, and neighborhood size
                results.append((neighborhood_size, threshold, stop_loss_percent, total_profit))

                # Print intraday profit/loss breakdown
                print(f"\nIntraday Profit/Loss for Neighborhood {neighborhood_size}, "
                      f"Threshold {threshold}, Stop-Loss {stop_loss_percent}:")
                for timestamp, profit in sorted(intraday_profits.items()):
                    print(f"{timestamp}: {profit:.4f}")

    return results


# Define parameters
thresholds = np.arange(0.005, 0.05, 0.005)  # Entry thresholds: 0.5% to 5%
stop_loss_range = np.arange(0.05, 0.16, 0.01)  # Stop-loss percentages: 5% to 15%
neighborhood_sizes = np.arange(1, 100, 1) # Neighborhood sizes: 3, 5, 7, and 10 intervals

# Run backtest
results = backtest_with_neighborhood_sizes(adj_close, thresholds, stop_loss_range, neighborhood_sizes)

# Convert results to a DataFrame for easier analysis
results_df = pd.DataFrame(results, columns=['Neighborhood Size', 'Threshold', 'Stop-Loss', 'Profit'])
print("\nBacktest Results:")
print(results_df)

# Display top results
print("\nTop Results:")
print(results_df.sort_values(by='Profit', ascending=False).head(10))
