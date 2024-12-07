import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import requests
import numpy as np
import pandas_ta as ta
import time

# Initialize FastAPI app
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging setup
logging.basicConfig(
    filename="activity.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("uvicorn").setLevel(logging.WARNING)

# Replace with your credentials
API_KEY = 'mrGAmTyy'
CLIENT_CODE = 'DIHV1008'
PASSWORD = '1982'
TOTP_TOKEN = '43X7CRFHVDVEGZX56PZVN4NE2I'

# Initialize SmartConnect
from SmartApi import SmartConnect
import pyotp

smart_api = SmartConnect(api_key=API_KEY)
totp = pyotp.TOTP(TOTP_TOKEN).now()

try:
    session_data = smart_api.generateSession(CLIENT_CODE, PASSWORD, totp)
    if not session_data['status']:
        logging.error(f"Login failed: {session_data['message']}")
    else:
        logging.info("Login successful.")
except Exception as e:
    logging.error(f"Error during login: {e}")

# Variable to control saving data
save_data = True

# Token Map Fetching
def fetch_token_map():
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            token_df = pd.DataFrame(response.json())
            token_df['expiry'] = token_df['expiry'].str.strip()
            token_df = token_df.astype({'strike': float})
            logging.info("Token map fetched successfully.")
            return token_df
    except Exception as e:
        logging.error(f"Error fetching token map: {e}")
    return pd.DataFrame()

token_df = fetch_token_map()

# Symbol List
SYMBOL_LIST = ["ACC", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "BAJAJHLDNG", "HDFCBANK", "TCS", "RELIANCE"]

# Fetch Historical Data
def get_historical_data(symbol_token, interval='FIVE_MINUTE', days=10):
    time.sleep(1)
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    params = {
        "exchange": "NSE",
        "symboltoken": symbol_token,
        "interval": interval,
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M")
    }
    return smart_api.getCandleData(params)['data']

# Custom KAMA Calculation (Matches Pine Script Logic)
def calculate_kama(df, length=14, fast_length=2, slow_length=30):
    """
    Calculate Kaufman Adaptive Moving Average (KAMA).
    Args:
        df: DataFrame containing the 'close' column.
        length: Period for ER calculation.
        fast_length: Fast EMA length.
        slow_length: Slow EMA length.
    Returns:
        A pandas Series containing KAMA values.
    """
    close = df['close']
    kama = [close.iloc[0]]  # Initialize KAMA with the first close price

    # Calculate momentum and volatility
    momentum = close.diff(length).abs()
    volatility = close.diff().abs().rolling(window=length).sum()

    # Efficiency Ratio (ER)
    er = np.where(volatility != 0, momentum / volatility, 0)

    # Smoothing constant (alpha)
    fast_alpha = 2 / (fast_length + 1)
    slow_alpha = 2 / (slow_length + 1)
    alpha = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2

    # Iteratively calculate KAMA
    for i in range(1, len(close)):
        current_alpha = alpha[i] if not np.isnan(alpha[i]) else slow_alpha
        new_kama = current_alpha * close.iloc[i] + (1 - current_alpha) * kama[-1]
        kama.append(new_kama)

    return pd.Series(kama, index=close.index)





# Calculate Indicators
def calculate_indicators(df, short_length=14, long_length=250):
    """
    Calculate KAMA Short, KAMA Long, ADX, ATR, and Choppiness Index.
    """
    # Calculate KAMA Short and KAMA Long
    df['KAMA_short'] = calculate_kama(df, length=short_length)
    df['KAMA_long'] = calculate_kama(df, length=long_length)

    # ADX Calculation
    adx = ta.adx(high=df['high'], low=df['low'], close=df['close'], length=14)
    df['ADX'] = adx['ADX_14']
    df['+DI'] = adx['DMP_14']
    df['-DI'] = adx['DMN_14']

    # ATR Calculation
    df['ATR'] = ta.atr(high=df['high'], low=df['low'], close=df['close'], length=14)

    # Choppiness Index
    df['Choppiness_Index'] = ta.chop(high=df['high'], low=df['low'], close=df['close'], length=14)

    # KAMA Color Signals
    df['KAMA_short_signal'] = df['KAMA_short'].diff().apply(lambda x: 'green' if x > 0 else 'red')
    df['KAMA_long_signal'] = df['KAMA_long'].diff().apply(lambda x: 'green' if x > 0 else 'red')

    return df



# Generate Signals
def generate_signals(symbol):
    token_info = token_df[(token_df['name'] == symbol) & (token_df['exch_seg'] == 'NSE')].iloc[0]
    token = token_info['token']
    candle_data = get_historical_data(token)

    df = pd.DataFrame(candle_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    df = calculate_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    signal = "NONE"
    stop_loss = None
    target = None

    if (latest['KAMA_short_signal'] == 'green' and prev['KAMA_short_signal'] == 'red'
        and latest['KAMA_long_signal'] == 'green'
        and latest['Choppiness_Index'] < 38.2
        and latest['ADX'] > 55):
        signal = "BUY"
        stop_loss = latest['low'] * 0.999
        target = latest['close'] + (2.5 * latest['ATR'])

    elif (latest['KAMA_short_signal'] == 'red' and prev['KAMA_short_signal'] == 'green'
          and latest['KAMA_long_signal'] == 'red'
          and latest['Choppiness_Index'] < 38.2
          and latest['ADX'] > 55):
        signal = "SELL"
        stop_loss = latest['high'] * 1.001
        target = latest['close'] - (2.5 * latest['ATR'])

    # Save DataFrame to CSV
    if save_data:
        output_file = f"{symbol}.csv"
        df.to_csv(output_file, index=True)
        logging.info(f"Data for {symbol} saved to {output_file}")

    return {
        "symbol": symbol,
        "signal": signal,
        "Close": latest['close'],
        "KAMA_short": latest['KAMA_short'],
        "KAMA_long": latest['KAMA_long'],
        "ADX": latest['ADX'],
        "Choppiness_Index": latest['Choppiness_Index'],
        "ATR": latest['ATR'],
        "Stop_Loss": round(stop_loss, 2) if stop_loss else None,
        "Target": round(target, 2) if target else None
    }

# Scheduled Scanning
@app.on_event("startup")
async def scheduled_scanner():
    while True:
        for symbol in SYMBOL_LIST:
            try:
                signal = generate_signals(symbol)
                logging.info(f"Scanned {symbol}: {signal}")
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
        await asyncio.sleep(300)  # Run every 5 minutes

# Run Server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
