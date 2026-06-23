from dotenv import load_dotenv
import os
import time
import math
from datetime import datetime
from binance.client import Client
from groq import Groq

load_dotenv()
API_KEY      = os.getenv("BINANCE_API_KEY")
API_SECRET   = os.getenv("BINANCE_API_SECRET")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ========== SETTINGS ==========
COINS = [
    {"symbol": "DOGEUSDT", "trade_usdt": 2},
]
STOP_LOSS_PERCENT = 2.0
CHECK_INTERVAL    = 60
# ==============================

client      = Client(API_KEY, API_SECRET)
groq_client = Groq(api_key=GROQ_API_KEY)

states = {
    c["symbol"]: {
        "holding":        False,
        "buy_price":      0,
        "buy_quantity":   0,
        "baseline_price": 0,
        "trade_usdt":     c["trade_usdt"],
        "prices":         []
    } for c in COINS
}

def now():
    return datetime.now().strftime("%H:%M:%S")

def get_price(symbol):
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])

def get_filters(symbol):
    info = client.get_symbol_info(symbol)
    step_size    = 1.0
    min_qty      = 0.0
    min_notional = 1.0
    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            step_size = float(f["stepSize"])
            min_qty   = float(f["minQty"])
        if f["filterType"] == "NOTIONAL":
            min_notional = float(f["minNotional"])
    return step_size, min_qty, min_notional

def round_qty(quantity, step_size):
    if step_size == 0:
        return quantity
    precision = max(0, round(-math.log10(step_size)))
    qty = quantity - (quantity % step_size)
    return round(qty, precision)

def get_usdt_balance():
    account = client.get_account()
    for asset in account["balances"]:
        if asset["asset"] == "USDT":
            return float(asset["free"])
    return 0.0

def get_asset_balance(asset):
    account = client.get_account()
    for a in account["balances"]:
        if a["asset"] == asset:
            return float(a["free"])
    return 0.0

def ask_groq(symbol, prices, holding, buy_price):
    price_str = ", ".join([f"{p:.6f}" for p in prices[-10:]])
    
    if holding:
        profit = ((prices[-1] - buy_price) / buy_price) * 100
        situation = f"Maine {symbol} @ {buy_price:.6f} pe buy kiya tha. Abhi profit/loss: {profit:.2f}%"
    else:
        situation = f"Maine abhi {symbol} hold nahi kiya hua."

    prompt = f"""Tu ek crypto trading expert hai. 
Symbol: {symbol}
Last 10 prices: {price_str}
Current price: {prices[-1]:.6f}
{situation}

Sirf ek word mein jawab do: BUY, SELL, ya HOLD
Koi explanation nahi chahiye."""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10
    )
    
    decision = response.choices[0].message.content.strip().upper()
    if "BUY" in decision:
        return "BUY"
    elif "SELL" in decision:
        return "SELL"
    else:
        return "HOLD"

def buy(symbol, usdt_amount):
    balance = get_usdt_balance()
    print(f"[{now()}] 💵 USDT Balance: {balance}")

    usdt_amount = min(usdt_amount, balance - 0.2)

    if usdt_amount <= 0:
        print(f"[{now()}] ⚠️  Balance kam hai — skipping!")
        return None, None

    price                            = get_price(symbol)
    step_size, min_qty, min_notional = get_filters(symbol)
    quantity                         = round_qty(usdt_amount / price, step_size)

    if quantity < min_qty:
        print(f"[{now()}] ⚠️  {symbol} quantity too small — skipping")
        return None, None
    if quantity * price < min_notional:
        print(f"[{now()}] ⚠️  {symbol} notional too small — skipping")
        return None, None

    client.order_market_buy(symbol=symbol, quantity=quantity)
    print(f"[{now()}] ✅ BUY! {quantity} {symbol} @ {price}")
    return price, quantity

def sell(symbol, quantity, reason="PROFIT"):
    price                            = get_price(symbol)
    step_size, min_qty, min_notional = get_filters(symbol)

    asset          = symbol.replace("USDT", "")
    actual_balance = get_asset_balance(asset)
    quantity       = min(quantity, actual_balance)
    quantity       = round_qty(quantity * 0.99, step_size)

    if quantity < min_qty:
        print(f"[{now()}] ⚠️  {symbol} sell qty too small — skipping")
        return
    if quantity * price < min_notional:
        print(f"[{now()}] ⚠️  {symbol} sell notional too small — skipping")
        return

    client.order_market_sell(symbol=symbol, quantity=quantity)
    print(f"[{now()}] 🔴 SELL ({reason})! {quantity} {symbol} @ {price}")

def run_bot():
    print(f"[{now()}] 🤖 AI Smart Bot Start Ho Gaya!")
    print(f"[{now()}] 🧠 Groq AI Connected!")
    print(f"[{now()}] 📊 Coins     : {[c['symbol'] for c in COINS]}")
    print(f"[{now()}] 🛑 Stop Loss : {STOP_LOSS_PERCENT}%")
    print("-" * 45)

    for c in COINS:
        sym = c["symbol"]
        states[sym]["baseline_price"] = get_price(sym)
        print(f"[{now()}] 📌 {sym} Baseline: {states[sym]['baseline_price']}")

    for c in COINS:
        sym   = c["symbol"]
        asset = sym.replace("USDT", "")
        bal   = get_asset_balance(asset)
        if bal > 0:
            price = get_price(sym)
            states[sym]["holding"]      = True
            states[sym]["buy_price"]    = price
            states[sym]["buy_quantity"] = bal
            print(f"[{now()}] 📦 {sym} already holding: {bal} @ {price}")

    print("-" * 45)

    while True:
        try:
            for c in COINS:
                sym   = c["symbol"]
                state = states[sym]

                current_price = get_price(sym)
                state["prices"].append(current_price)

                if len(state["prices"]) > 20:
                    state["prices"].pop(0)

                print(f"[{now()}] 💰 {sym}: {current_price:.6f}")

                if state["holding"]:
                    profit = ((current_price - state["buy_price"])
                              / state["buy_price"]) * 100
                    print(f"[{now()}] 📈 Profit: {profit:.2f}%")

                    if profit <= -STOP_LOSS_PERCENT:
                        sell(sym, state["buy_quantity"], "STOP LOSS")
                        state["holding"]        = False
                        state["baseline_price"] = current_price
                        continue

                if len(state["prices"]) >= 5:
                    decision = ask_groq(sym, state["prices"],
                                        state["holding"], state["buy_price"])
                    print(f"[{now()}] 🧠 Groq says: {decision}")

                    if decision == "BUY" and not state["holding"]:
                        price, qty = buy(sym, state["trade_usdt"])
                        if price and qty:
                            state["buy_price"]      = price
                            state["buy_quantity"]   = qty
                            state["holding"]        = True
                            state["baseline_price"] = current_price

                    elif decision == "SELL" and state["holding"]:
                        sell(sym, state["buy_quantity"], "AI SELL")
                        state["holding"]        = False
                        state["baseline_price"] = current_price

            print("-" * 45)
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[{now()}] ❌ Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()