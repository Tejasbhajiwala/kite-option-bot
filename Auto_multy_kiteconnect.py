from kiteconnect import KiteConnect
import pandas as pd
import requests
import time
from config import *

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

df = None


def load_instruments():

    global df

    nfo = kite.instruments("NFO")
    mcx = kite.instruments("MCX")

    df = pd.DataFrame(nfo + mcx)


def get_spot(symbol):

    if symbol in INDEX_MAP:

        return kite.ltp(INDEX_MAP[symbol])[INDEX_MAP[symbol]]["last_price"]

    elif symbol in COMMODITY_LIST:

        fut = df[
            (df["name"] == symbol) &
            (df["segment"] == "MCX-FUT")
        ].sort_values("expiry").iloc[0]

        ts = f"MCX:{fut['tradingsymbol']}"

        return kite.ltp(ts)[ts]["last_price"]

    else:

        ts = f"NSE:{symbol}"

        return kite.ltp(ts)[ts]["last_price"]


def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = {

        "chat_id": CHAT_ID,
        "text": msg

    }

    requests.post(url, data=data)


def analyze(symbol):

    spot = get_spot(symbol)

    msg = f"{symbol} Spot: {spot}"

    return msg


def run():

    load_instruments()

    symbols = ["NIFTY", "BANKNIFTY", "GOLD"]

    for s in symbols:

        msg = analyze(s)

        send_telegram(msg)

        time.sleep(2)


if __name__ == "__main__":

    run()
