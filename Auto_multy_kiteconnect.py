from kiteconnect import KiteConnect
from telegram.ext import ApplicationBuilder, MessageHandler, filters
import pandas as pd
import os
import math
import time


# ========= CONFIG =========
TELEGRAM_TOKEN = "8537196036:AAFOfjj_LKp4IcC9bq7A9n3Udr36uxou7bE"
# ========= CONFIG =========
API_KEY = "jvilhhoyu7a2n9qv"
API_SECRET = "bbh5lr2557ktsqe0y9wxh69g16t7jw0a"
ACCESS_TOKEN_FILE = "access_token.txt"
token="lCuTEWdRG6duwLZWliXJyEMIFMt8wgd2"

CAPITAL = 50000
MAX_RISK_PERCENT = 3
MAX_LOSS_ALLOWED = CAPITAL * MAX_RISK_PERCENT / 100
# ================= INDEX SYMBOL MAP =================

INDEX_MAP = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE"
}

# ================= COMMODITY SYMBOL LIST =================

COMMODITY_LIST = [
    "CRUDEOIL",
    "GOLD",
    "SILVER",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM"
]

CAPITAL = 50000
MAX_RISK = 0.10

INDEX_MAP = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE"
}

MCX_LIST = ["CRUDEOIL","GOLD","SILVER"]

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(token)
kite.profile()
print("Kite login success")
# ================= LOGIN =================

def login():

    #with open(ACCESS_TOKEN_FILE,"r") as f:

        #token="lCuTEWdRG6duwLZWliXJyEMIFMt8wgd2"
    #f.read().strip()

    #kite.set_access_token(token)

    #kite.profile()

    #print("Kite login success")


# ================= LOAD INSTRUMENTS =================

def load_instruments():

    global df
    nfo = kite.instruments("NFO")
    mcx = kite.instruments("MCX")
    df = pd.DataFrame(nfo + mcx)
    print("Instruments loaded:",len(df))


# ================= GET SPOT =================

def get_spot(symbol):

    if symbol in INDEX_MAP:

        kite_symbol = INDEX_MAP[symbol]

    elif symbol in MCX_LIST:

        fut = df[
            (df["name"]==symbol)&
            (df["segment"]=="MCX-FUT")
        ].iloc[0]

        kite_symbol=f"MCX:{fut['tradingsymbol']}"

    else:

        kite_symbol=f"NSE:{symbol}"

    return kite.ltp(kite_symbol)[kite_symbol]["last_price"]


# ================= OPTION CHAIN =================
def get_option_chain(symbol):

    global df

    # detect segment
    if symbol in COMMODITY_LIST:

        options = df[
            (df["name"] == symbol) &
            (df["segment"] == "MCX-OPT")
        ]

    else:

        options = df[
            (df["name"] == symbol) &
            (df["segment"] == "NFO-OPT")
        ]

    if len(options) == 0:
        raise Exception("No options found")

    expiry = sorted(options["expiry"].unique())[0]

    options = options[options["expiry"] == expiry]

    # ===== IMPORTANT FIX: LIMIT STRIKES AROUND ATM =====

    spot = get_spot(symbol)

    strikes = sorted(options["strike"].unique())

    # find ATM strike
    atm = min(strikes, key=lambda x: abs(x - spot))

    # select only nearby strikes
    lower = atm - (10 * (strikes[1] - strikes[0]))
    upper = atm + (10 * (strikes[1] - strikes[0]))

    options = options[
        (options["strike"] >= lower) &
        (options["strike"] <= upper)
    ]

    # prepare quote list
    symbol_map = {}
    quote_list = []

    for i, row in options.iterrows():

        ts = f"{row['exchange']}:{row['tradingsymbol']}"

        symbol_map[ts] = {

            "strike": row["strike"],
            "type": row["instrument_type"],
            "symbol": row["tradingsymbol"],
            "lot": row["lot_size"]

        }

        quote_list.append(ts)

    # batch request safely
    quotes = {}

    batch_size = 25

    for i in range(0, len(quote_list), batch_size):

        batch = quote_list[i:i+batch_size]

        batch_quotes = kite.quote(batch)

        quotes.update(batch_quotes)

        time.sleep(0.3)

    # build dataframe
    data = []

    for ts in quotes:

        q = quotes[ts]

        data.append({

            "strike": symbol_map[ts]["strike"],
            "type": symbol_map[ts]["type"],
            "symbol": symbol_map[ts]["symbol"],
            "lot": symbol_map[ts]["lot"],
            "oi": q["oi"],
            "price": q["last_price"]

        })

    return pd.DataFrame(data), expiry
# ================= ANALYSIS ENGINE =================
def analyze(symbol):

    global MAX_LOSS_ALLOWED
    global COMMODITY_LIST
    global INDEX_MAP

    try:

        # ===== GET SPOT =====

        spot = get_spot(symbol)

        # ===== GET OPTION CHAIN =====

        chain, expiry = get_option_chain(symbol)

        puts = chain[chain["type"] == "PE"].copy()
        calls = chain[chain["type"] == "CE"].copy()

        if len(puts) < 2 or len(calls) < 2:

            return "Not enough option data"

        # ===== PCR =====

        total_put_oi = puts["oi"].sum()
        total_call_oi = calls["oi"].sum()

        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0

        # ===== SUPPORT RESISTANCE =====

        support = puts.loc[puts["oi"].idxmax()]
        resistance = calls.loc[calls["oi"].idxmax()]

        support_strike = support["strike"]
        resistance_strike = resistance["strike"]

        # ===== SPREAD SELECTION =====

        put_strikes = sorted(puts["strike"].unique())

        best_trade = None

        is_commodity = symbol in COMMODITY_LIST

        for i in range(1, len(put_strikes)):

            sell_strike = put_strikes[i]
            buy_strike = put_strikes[i-1]

            sell_option = puts[puts["strike"] == sell_strike].iloc[0]
            buy_option = puts[puts["strike"] == buy_strike].iloc[0]

            sell_price = sell_option["price"]
            buy_price = buy_option["price"]

            lot = sell_option["lot"]

            credit = sell_price - buy_price

            strike_diff = sell_strike - buy_strike

            max_loss = (strike_diff - credit) * lot
            max_profit = credit * lot

            # skip invalid
            if max_loss <= 0 or max_profit <= 0:
                continue

            # ===== COMMODITY RULE =====

            if is_commodity:

                # Profit must NOT be less than loss
                if max_profit < max_loss:
                    continue

            # ===== STOCK / INDEX RULE =====

            else:

                # risk control
                if max_loss > MAX_LOSS_ALLOWED:
                    continue

                # profit must not be less than loss
                if max_profit < max_loss:
                    continue

            # ===== SCORE =====

            probability = round(
                100 - abs(spot - sell_strike) / spot * 100, 1
            )

            liquidity_score = sell_option["oi"]

            score = probability + (max_profit / max_loss) * 10 + liquidity_score / 10000

            if best_trade is None or score > best_trade["score"]:

                best_trade = {

                    "sell_symbol": sell_option["symbol"],
                    "buy_symbol": buy_option["symbol"],

                    "sell_strike": sell_strike,
                    "buy_strike": buy_strike,

                    "sell_price": sell_price,
                    "buy_price": buy_price,

                    "lot": lot,

                    "max_profit": max_profit,
                    "max_loss": max_loss,

                    "probability": probability,

                    "score": score
                }

        # ===== NO TRADE FOUND =====

        if best_trade is None:

            return f"""
NO SAFE TRADE FOUND

Symbol: {symbol}
Spot: ₹{round(spot,2)}

Try different strike or wait.
"""

        # ===== OUTPUT =====

        trade = best_trade

        intraday = symbol in INDEX_MAP

        exit_rule = "Exit same day" if intraday else "Exit before expiry"

        msg = f"""
PRO OPTION STRATEGY REPORT

Symbol: {symbol}
Spot: ₹{round(spot,2)}

Expiry: {expiry}

PCR: {pcr}

Support: {support_strike}
Resistance: {resistance_strike}

Strategy: Bull Put Spread

Sell: {trade['sell_symbol']} @ ₹{trade['sell_price']}
Buy: {trade['buy_symbol']} @ ₹{trade['buy_price']}

Lot Size: {trade['lot']}

Max Profit: ₹{round(trade['max_profit'])}
Max Loss: ₹{round(trade['max_loss'])}

Risk Reward: 1:{round(trade['max_profit']/trade['max_loss'],2)}

Probability: {trade['probability']}%

Exit Rules:
• {exit_rule}
• Exit below {trade['sell_strike']}
• Exit at 50% loss
• Exit at 80% profit
"""

        return msg

    except Exception as e:

        return f"Error in analysis: {str(e)}"

def handle(update, context):

    symbol = update.message.text.upper()

    update.message.reply_text("Analyzing " + symbol)

    time.sleep(1)

    msg = analyze(symbol)

    update.message.reply_text(msg)


# ================= START BOT =================

def start():

    load_instruments()

    updater=Updater(TELEGRAM_TOKEN,use_context=True)

    dp=updater.dispatcher

    dp.add_handler(MessageHandler(Filters.text,handle))

    updater.start_polling()

    print("PRO BOT RUNNING")

    updater.idle()


start()




