import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import requests
from ta.trend import SMAIndicator
from ta.momentum import RSIIndicator
import pyotp
import time

# Initialize FastAPI app
app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up logging
logging.basicConfig(
    filename="activity.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("uvicorn").setLevel(logging.WARNING)  # Suppress uvicorn logs

# Log startup information
logging.info("Application started.")

# Replace with your actual credentials
API_KEY = ''
CLIENT_CODE = ''
PASSWORD = ''
TOTP_TOKEN = ''

# Initialize SmartConnect
from SmartApi import SmartConnect

smart_api = SmartConnect(api_key=API_KEY)

# Generate TOTP
totp = pyotp.TOTP(TOTP_TOKEN).now()

# Create a session
try:
    session_data = smart_api.generateSession(CLIENT_CODE, PASSWORD, totp)
    if not session_data['status']:
        logging.error(f"Login failed: {session_data['message']}")
    else:
        logging.info("Login successful.")
        auth_token = session_data['data']['jwtToken']
        refresh_token = session_data['data']['refreshToken']
except Exception as e:
    logging.error(f"Error during login: {e}")

# Fetch token map
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
        else:
            logging.error("Failed to fetch token map.")
            return pd.DataFrame()
    except Exception as e:
        logging.error(f"Error fetching token map: {e}")
        return pd.DataFrame()

token_df = fetch_token_map()

# List of symbols to monitor
SYMBOL_LIST =  [
"ADANIPOWER",
"RECLTD",
"LTIM",
"PERSISTENT",
"TORNTPOWER",
"SBICARD",
"JINDALSTEL",
"DIVISLAB",
"HDFCAMC",
"ADANIPORTS",
"GODREJCP",
"HDFCLIFE",
"ICICIPRULI",
"SBILIFE",
"ICICIGI",
"MAXHEALTH",
"GMRINFRA",
"IDEA",
"IRCTC",
"MUTHOOTFIN",
"ULTRACEMCO",
"COFORGE",
"YESBANK",
"POLYCAB",
"BAJAJ-AUTO",
"BAJAJFINSV",
"IRB",
"INDIGO",
"AUBANK",
"DIXON",
"MANKIND",
"PAYTM",
"INDUSTOWER",
"ABCAPITAL",
"ABFRL",
"TIINDIA",
"L&TFH",
"JSWINFRA",
"BANDHANBNK",
"KPITTECH",

]


def get_token_info(symbol, exch_seg='NSE'):
    df = token_df
    eq_df = df[(df['exch_seg'] == exch_seg) & (df['symbol'].str.contains('EQ'))]
    return eq_df[eq_df['name'] == symbol]

def get_historical_data(symbol_token, interval='FIVE_MINUTE', days=2):
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
    try:
        historical_data = smart_api.getCandleData(params)
        if historical_data['status']:
            logging.info(f"Historical data fetched for token {symbol_token}.")
            return historical_data['data']
        else:
            logging.error(f"Failed to fetch historical data: {historical_data['message']}")
    except Exception as e:
        logging.error(f"Error fetching historical data: {e}")
    return None

def calculate_indicators(candle_data, symbol_name):
    """
    Calculate indicators and log OHLC and indicator values with the symbol name.
    """
    df = pd.DataFrame(candle_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    # Calculate SMA
    df['SMA_20'] = SMAIndicator(close=df['close'], window=20).sma_indicator()
    df['SMA_200'] = SMAIndicator(close=df['close'], window=200).sma_indicator()

    # Log OHLC and indicators for the latest row
    latest = df.iloc[-1]
    logging.info(
        f"Symbol: {symbol_name} | OHLC: Open={latest['open']}, High={latest['high']}, Low={latest['low']}, "
        f"Close={latest['close']}, Volume={latest['volume']} | Indicators: SMA_20={latest['SMA_20']}, "
        f"SMA_200={latest['SMA_200']}"
    )

    return df


def generate_signal(df, symbol_name):
    """
    Generate buy or sell signals based on updated criteria and log the signal details.
    """
    latest_close = df['close'].iloc[-1]
    sma_20 = df['SMA_20'].iloc[-1]
    sma_200 = df['SMA_200'].iloc[-1]

    # Calculate differences as percentages
    diff_close_sma20 = abs((latest_close - sma_20) / sma_20) * 100
    diff_sma20_sma200 = abs((sma_20 - sma_200) / sma_200) * 100

    # Sell Signal
    if diff_close_sma20 > 1.8 and diff_sma20_sma200 > 1.8:
    #if latest_close > 4500:
        logging.info(
            f"Symbol: {symbol_name} | Signal: SELL | Close={latest_close}, SMA_20={sma_20}, SMA_200={sma_200}, "
            f"Diff_Close_SMA20={diff_close_sma20:.2f}%, Diff_SMA20_SMA200={diff_sma20_sma200:.2f}%"
        )
        return "SELL"

    # Buy Signal
    if diff_close_sma20 < 1.8 and diff_sma20_sma200 > 1.8:
        logging.info(
            f"Symbol: {symbol_name} | Signal: BUY | Close={latest_close}, SMA_20={sma_20}, SMA_200={sma_200}, "
            f"Diff_Close_SMA20={diff_close_sma20:.2f}%, Diff_SMA20_SMA200={diff_sma20_sma200:.2f}%"
        )
        return "BUY"

    # No Signal
    logging.info(
        f"Symbol: {symbol_name} | No Signal | Close={latest_close}, SMA_20={sma_20}, SMA_200={sma_200}, "
        f"Diff_Close_SMA20={diff_close_sma20:.2f}%, Diff_SMA20_SMA200={diff_sma20_sma200:.2f}%"
    )
    return None

async def wait_until_next_interval():
    """Wait until the next 5-minute interval."""
    now = datetime.now()
    next_minute = (now.minute // 5 + 1) * 5
    if next_minute == 60:
        next_time = now.replace(hour=now.hour + 1, minute=0, second=0, microsecond=0)
    else:
        next_time = now.replace(minute=next_minute, second=0, microsecond=0)
    wait_time = (next_time - now).total_seconds()
    logging.info(f"Waiting {wait_time} seconds for the next interval at {next_time}.")
    await asyncio.sleep(wait_time)

signals = []
async def scan_stocks():
    global signals
    await wait_until_next_interval()  # Wait for the first 5-minute interval
    while True:
        try:
            logging.info("Starting stock scan.")
            signals = []
            for symbol in SYMBOL_LIST:
                token_info = get_token_info(symbol).iloc[0]
                token = token_info['token']
                symbol_name = token_info['name']  # Ensure the symbol name is retrieved correctly

                candle_data = get_historical_data(token)
                if candle_data:
                    # Pass symbol_name to calculate_indicators and generate_signal
                    df = calculate_indicators(candle_data, symbol_name)
                    signal = generate_signal(df, symbol_name)
                    if signal:
                        current_price = df['close'].iloc[-1]
                        signals.append({
                            "symbol": symbol_name,
                            "token": token,
                            "price": current_price,
                            "signal": signal
                        })
                        logging.info(f"Signal generated: {signal} for {symbol_name} at {current_price}")
            logging.info("Stock scan completed.")
        except Exception as e:
            logging.error(f"Error during stock scan: {e}")
        await asyncio.sleep(300)  # Wait for 5 minutes


@app.on_event("startup")
async def startup_event():
    logging.info("Starting background task for stock scanning.")
    asyncio.create_task(scan_stocks())

@app.get("/signals")
async def get_filtered_signals():
    logging.info("Fetching latest signals.")
    return signals if signals else {"message": "No signals generated for the monitored stocks"}
