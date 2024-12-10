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
API_KEY = ''
CLIENT_CODE = ''
PASSWORD = ''
TOTP_TOKEN = ''

# External endpoint to POST signal data
EXTERNAL_ENDPOINT = "http://example.com/signals"

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

# Token Map Fetching
def fetch_token_map():
    logging.info("Fetching token map...")
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    try:
        response = requests.get(url, timeout=10)
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
    time.sleep(1)  # Rate limiting
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)
    params = {
        "exchange": "NSE",
        "symboltoken": symbol_token,
        "interval": interval,
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M")
    }
    try:
        logging.info(f"Fetching historical data for token: {symbol_token}")
        response = smart_api.getCandleData(params)
        if response['status']:
            return response['data']
        else:
            logging.error(f"API Error for token {symbol_token}: {response}")
    except Exception as e:
        logging.error(f"Exception while fetching data for token {symbol_token}: {e}")
    return []

# Custom KAMA Calculation
def calculate_kama(df, length=14, fast_length=2, slow_length=30):
    close = df['close']
    kama = [close.iloc[0]]  # Initialize with first close
    momentum = close.diff(length).abs()
    volatility = close.diff().abs().rolling(window=length).sum()
    er = np.where(volatility != 0, momentum / volatility, 0)
    fast_alpha = 2 / (fast_length + 1)
    slow_alpha = 2 / (slow_length + 1)
    alpha = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2
    for i in range(1, len(close)):
        current_alpha = alpha[i] if not np.isnan(alpha[i]) else slow_alpha
        new_kama = current_alpha * close.iloc[i] + (1 - current_alpha) * kama[-1]
        kama.append(new_kama)
    return pd.Series(kama, index=close.index)

# Generate Signals

def generate_signals(symbol):
    """Generate trading signals for a given symbol."""
    try:
        # Fetch token for the given symbol
        token_info = token_df[(token_df['name'] == symbol) & (token_df['exch_seg'] == 'NSE')]
        if token_info.empty:
            logging.warning(f"Token not found for symbol {symbol}. Skipping...")
            return None
        token = token_info.iloc[0]['token']

        # Fetch historical data
        candle_data = get_historical_data(token)
        if not candle_data:
            logging.warning(f"No data returned for symbol {symbol}.")
            return None

        # Process historical data
        df = pd.DataFrame(candle_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # Calculate Indicators
        df['KAMA_short'] = calculate_kama(df, length=14)
        df['KAMA_long'] = calculate_kama(df, length=250)
        df['CHOP'] = ta.chop(df['high'], df['low'], df['close'], length=14)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        # Determine KAMA transitions
        df['KAMA_short_color'] = df['KAMA_short'].diff().apply(lambda x: 'green' if x > 0 else 'red')
        df['KAMA_long_color'] = df['KAMA_long'].diff().apply(lambda x: 'green' if x > 0 else 'red')

        latest = df.iloc[-1]
        previous = df.iloc[-2]

        signal = None
        stop_loss = None
        target = None

        # BUY Signal Logic
        if (previous['KAMA_short_color'] == 'red' and latest['KAMA_short_color'] == 'green' and
            previous['KAMA_long_color'] == 'red' and latest['KAMA_long_color'] == 'green' and
            latest['CHOP'] < 50):
            signal = "BUY"
            stop_loss = round(previous['low'] - (latest['ATR'] * 1.5), 2)
            target = round(latest['close'] + (latest['ATR'] * 2.5), 2)

        # SELL Signal Logic
        elif (previous['KAMA_short_color'] == 'green' and latest['KAMA_short_color'] == 'red' and
              previous['KAMA_long_color'] == 'green' and latest['KAMA_long_color'] == 'red' and
              latest['CHOP'] < 50):
            signal = "SELL"
            stop_loss = round(previous['high'] + (latest['ATR'] * 1.5), 2)
            target = round(latest['close'] - (latest['ATR'] * 2.5), 2)

        # Return Signal Result
        if signal:
            result = {
                "symbol": symbol,
                "signal": signal,
                "Close": latest['close'],
                "KAMA_short": latest['KAMA_short'],
                "KAMA_long": latest['KAMA_long'],
                "CHOP": latest['CHOP'],
                "ATR": latest['ATR'],
                "Stop_Loss": stop_loss,
                "Target": target
            }

            # Post to external endpoint
            try:
                response = requests.post(EXTERNAL_ENDPOINT, json=result, timeout=5)
                if response.status_code == 200:
                    logging.info(f"Signal for {symbol} sent successfully: {result}")
                else:
                    logging.error(f"Failed to post signal for {symbol}: {response.text}")
            except Exception as e:
                logging.error(f"Error posting signal for {symbol}: {e}")

            return result
        else:
            logging.info(f"No signal generated for {symbol}.")
            return None

    except Exception as e:
        logging.error(f"Error generating signal for {symbol}: {e}")
        return None



@app.get("/signals")
async def fetch_signals():
    results = []
    for symbol in SYMBOL_LIST:
        result = generate_signals(symbol)
        if result:
            results.append(result)
    return results

@app.on_event("startup")
async def scheduled_scanner():
    while True:
        for symbol in SYMBOL_LIST:
            generate_signals(symbol)
        await asyncio.sleep(300)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
