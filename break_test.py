from alpha_vantage.timeseries import TimeSeries
import pandas as pd
import numpy as np

# Replace with your Alpha Vantage API key
API_KEY = "BC0I5G0I7X8G06CO"

# Initialize Alpha Vantage API
ts = TimeSeries(key=API_KEY, output_format='pandas')

# Fetch intraday stock data for specific tickers
tickers = ['RGTI', 'QUBT', 'QBTS', 'IONQ']
adj_close = pd.DataFrame()

# Specify the interval for intraday data (e.g., '1min', '5min', '15min')
interval = '5min'

for ticker in tickers:
    print(f"Fetching data for {ticker}...")
    data, _ = ts.get_intraday(symbol=ticker, interval=interval, outputsize='compact')
    adj_close[ticker] = data['4. close']  # Extract closing prices

# Sort by time to ensure data is ordered correctly
adj_close = adj_close.sort_index()

# Compute intraday percentage changes
returns = adj_close.pct_change().dropna()

# Backtest thresholds
def backtest_thresholds(returns, thresholds):
    results = {}
    for threshold in thresholds:
        total_profit = 0
        for ticker in returns.columns:
            signal = returns[ticker][abs(returns[ticker]) > threshold]
            profit = signal.sum()
            total_profit += profit
        results[threshold] = total_profit
    return results

# Test thresholds
thresholds = np.arange(0.005, 0.10, 0.0025)  # Smaller thresholds for intraday data (e.g., 0.5% to 5%)
threshold_results = backtest_thresholds(returns, thresholds)

# Print results
print(pd.Series(threshold_results).sort_index())
