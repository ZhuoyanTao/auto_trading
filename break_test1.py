from alpha_vantage.timeseries import TimeSeries
import pandas as pd
import numpy as np

# Replace with your Alpha Vantage API key
# API_KEY = "BC0I5G0I7X8G06CO"
API_KEY = "TAONZJP6WL26F0PK"


# Initialize Alpha Vantage API
ts = TimeSeries(key=API_KEY, output_format='pandas')

# Fetch intraday stock data for specific tickers
tickers = ['RGTI', 'QUBT', 'QBTS', 'IONQ']
adj_close = pd.DataFrame()

# Specify the interval for intraday data (e.g., '5min', '15min')
interval = '5min'

for ticker in tickers:
    print(f"Fetching data for {ticker}...")
    data, _ = ts.get_intraday(symbol=ticker, interval=interval, outputsize='compact')
    adj_close[ticker] = data['4. close']

# Sort data to ensure correct time order
adj_close = adj_close.sort_index()

# Backtest thresholds with a range of stop-loss percentages
def backtest_with_stop_loss(adj_close, thresholds, stop_loss_range):
    results = []
    for threshold in thresholds:
        for stop_loss_percent in stop_loss_range:
            total_profit = 0
            for ticker in adj_close.columns:
                prices = adj_close[ticker]
                position = None  # 'long' or 'short'
                entry_price = 0
                peak_price = 0

                for i in range(1, len(prices)):
                    price_change = (prices.iloc[i] - prices.iloc[i-1]) / prices.iloc[i-1]

                    if position is None:  # Look for a buy/short entry signal
                        if price_change > threshold:  # Buy signal
                            position = 'long'
                            entry_price = prices.iloc[i]
                            peak_price = prices.iloc[i]
                        elif price_change < -threshold:  # Short signal
                            position = 'short'
                            entry_price = prices.iloc[i]
                            peak_price = prices.iloc[i]

                    elif position == 'long':  # Long position
                        peak_price = max(peak_price, prices.iloc[i])
                        if prices.iloc[i] <= peak_price * (1 - stop_loss_percent):
                            total_profit += (prices.iloc[i] - entry_price) / entry_price
                            position = None

                    elif position == 'short':  # Short position
                        peak_price = min(peak_price, prices.iloc[i])
                        if prices.iloc[i] >= peak_price * (1 + stop_loss_percent):
                            total_profit += (entry_price - prices.iloc[i]) / entry_price
                            position = None

            # Save the results
            results.append((threshold, stop_loss_percent, total_profit))
    return results

# Define thresholds and stop-loss percentages
thresholds = np.arange(0.005, 0.05, 0.005)  # Entry thresholds from 0.5% to 5%
stop_loss_range = np.arange(0.05, 0.16, 0.01)  # Stop-loss thresholds from 5% to 15%

# Run backtest
results = backtest_with_stop_loss(adj_close, thresholds, stop_loss_range)

# Convert results to a DataFrame for easier visualization
results_df = pd.DataFrame(results, columns=['Threshold', 'Stop-Loss', 'Profit'])
print("\nBacktest Results:")
print(results_df)

# Display results sorted by profit
print("\nTop Results:")
print(results_df.sort_values(by='Profit', ascending=False).head(10))
