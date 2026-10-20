import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import re
import json
import random
import base64
from pathlib import Path
from datetime import datetime, timedelta, timezone
from neo_api_client import NeoAPI

# ==========================================
# 0. INDIAN STANDARD TIME (IST) & LOGO HELPER
# ==========================================
IST_TZ = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST_TZ).replace(tzinfo=None)

def dt_to_tv_ist_timestamp(dt_naive_ist):
    return int(dt_naive_ist.replace(tzinfo=timezone.utc).timestamp())

def render_centered_jineo_logo(max_width=230):
    """
    Agar folder me logo.png / 24593.png rakha ho to use load karega,
    warna aapke 24593.png logo ka 100% exact built-in vector render karega!
    """
    for fname in ["24593.png", "logo.png", "jineo_logo.png"]:
        p = Path(fname)
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            st.markdown(
                f"<div style='display:flex; justify-content:center; align-items:center; margin:4px 0 8px 0;'>"
                f"<img src='data:image/png;base64,{b64}' style='max-width:{max_width}px; height:auto;'>"
                f"</div>",
                unsafe_allow_html=True
            )
            return

    # Built-in exact replica of 24593.png (Dark Blue Pill + Candlesticks + Blue Swoop Arrow + JiNeo Text)
    svg_logo = f"""
    <div style="display:flex; justify-content:center; align-items:center; margin:4px 0 8px 0;">
        <svg viewBox="0 0 520 155" style="width:100%; max-width:{max_width}px; height:auto; filter:drop-shadow(0 2px 6px rgba(3,21,58,0.22));" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="bgPill" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#052159"/>
                    <stop offset="100%" stop-color="#021030"/>
                </linearGradient>
                <linearGradient id="blueGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#0072ff"/>
                    <stop offset="100%" stop-color="#00d4ff"/>
                </linearGradient>
                <linearGradient id="greenC" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#38ef7d"/>
                    <stop offset="100%" stop-color="#11998e"/>
                </linearGradient>
                <linearGradient id="redC" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="#ff4b2b"/>
                    <stop offset="100%" stop-color="#d31027"/>
                </linearGradient>
            </defs>
            <!-- Dark Navy Pill Container -->
            <rect x="4" y="4" width="512" height="147" rx="73.5" fill="url(#bgPill)"/>
            <!-- 5 Candlesticks -->
            <line x1="62" y1="68" x2="62" y2="115" stroke="#22e67b" stroke-width="4" stroke-linecap="round"/>
            <rect x="54" y="78" width="16" height="26" rx="2" fill="url(#greenC)"/>
            <line x1="86" y1="54" x2="86" y2="112" stroke="#22e67b" stroke-width="4" stroke-linecap="round"/>
            <rect x="78" y="65" width="16" height="35" rx="2" fill="url(#greenC)"/>
            <line x1="110" y1="42" x2="110" y2="104" stroke="#ff3b30" stroke-width="4" stroke-linecap="round"/>
            <rect x="102" y="54" width="16" height="38" rx="2" fill="url(#redC)"/>
            <line x1="134" y1="48" x2="134" y2="98" stroke="#22e67b" stroke-width="4" stroke-linecap="round"/>
            <rect x="126" y="60" width="16" height="28" rx="2" fill="url(#greenC)"/>
            <line x1="158" y1="22" x2="158" y2="88" stroke="#22e67b" stroke-width="4" stroke-linecap="round"/>
            <rect x="150" y="34" width="16" height="40" rx="2" fill="url(#greenC)"/>
            <!-- Swooping Blue Arrow -->
            <path d="M 42 98 C 36 138, 128 142, 188 66" fill="none" stroke="url(#blueGrad)" stroke-width="15" stroke-linecap="round"/>
            <polygon points="172,56 206,44 202,82" fill="#00c6ff"/>
            <!-- 'Ji' in White with Green Accent Leaf -->
            <text x="212" y="114" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="86" fill="#ffffff">Jı</text>
            <polygon points="274,38 294,38 287,52 267,52" fill="#22e67b"/>
            <!-- 'Neo' in Cyan-Blue Gradient -->
            <text x="294" y="114" font-family="Arial, Helvetica, sans-serif" font-weight="900" font-size="86" fill="url(#blueGrad)">Neo</text>
        </svg>
    </div>
    """
    st.markdown(svg_logo, unsafe_allow_html=True)

# ==========================================
# 1. PERSISTENT SERVER STORE (REFRESH SAFE)
# ==========================================
@st.cache_resource
def get_global_store():
    return {
        "client": None,
        "live_prices": {},
        "quote_meta": {},
        "candles": {},
        "last_debug": {}
    }

STORE = get_global_store()
LIVE_PRICES = STORE["live_prices"]
QUOTE_META = STORE.setdefault("quote_meta", {})
CANDLES = STORE.setdefault("candles", {})

# ==========================================
# 2. JINEO PAPER TRADING ENGINE (WITH IST TIME)
# ==========================================
class JiNeoEngine:
    def __init__(self, initial_balance=1000000.0):
        self.conn = sqlite3.connect("jineo_pro.db", check_same_thread=False)
        self.init_db(initial_balance)

    def init_db(self, initial_balance):
        c = self.conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY, balance REAL, realized_pnl REAL)")
        c.execute("SELECT count(*) FROM wallet")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO wallet VALUES (1, ?, 0.0)", (initial_balance,))

        c.execute("""
            CREATE TABLE IF NOT EXISTS saved_creds (
                id INTEGER PRIMARY KEY, consumer_key TEXT, mobile TEXT, ucc TEXT, mpin TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                instrument_token TEXT PRIMARY KEY,
                trading_symbol TEXT,
                exchange_segment TEXT,
                lot_size INTEGER,
                net_qty INTEGER,
                avg_price REAL,
                sl_price REAL DEFAULT 0.0,
                target_price REAL DEFAULT 0.0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_orders (
                pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_token TEXT,
                trading_symbol TEXT,
                exchange_segment TEXT,
                lot_size INTEGER,
                side TEXT,
                lots INTEGER,
                limit_price REAL,
                sl_price REAL,
                target_price REAL,
                time TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trading_symbol TEXT,
                side TEXT,
                qty INTEGER,
                price REAL,
                order_type TEXT,
                charges REAL,
                time TEXT
            )
        """)
        self.conn.commit()

    def save_creds(self, c_key, mob, ucc, mpin):
        c = self.conn.cursor()
        c.execute("DELETE FROM saved_creds")
        c.execute("INSERT INTO saved_creds VALUES (1, ?, ?, ?, ?)", (c_key, mob, ucc, mpin))
        self.conn.commit()

    def get_creds(self):
        c = self.conn.cursor()
        c.execute("SELECT consumer_key, mobile, ucc, mpin FROM saved_creds WHERE id=1")
        row = c.fetchone()
        return row if row else ("", "+91", "", "")

    def get_wallet(self):
        c = self.conn.cursor()
        c.execute("SELECT balance, realized_pnl FROM wallet WHERE id=1")
        row = c.fetchone()
        return round(row[0], 2), round(row[1], 2)

    def reset_account(self, amount=1000000.0):
        c = self.conn.cursor()
        c.execute("UPDATE wallet SET balance = ?, realized_pnl = 0.0 WHERE id=1", (amount,))
        c.execute("DELETE FROM positions")
        c.execute("DELETE FROM pending_orders")
        c.execute("DELETE FROM orders")
        self.conn.commit()

    def place_limit_order(self, token, symbol, segment, lot_size, side, lots, limit_price, sl_price, target_price):
        c = self.conn.cursor()
        ist_time_str = get_ist_now().strftime("%d %b %I:%M:%S %p")
        c.execute("""
            INSERT INTO pending_orders 
            (instrument_token, trading_symbol, exchange_segment, lot_size, side, lots, limit_price, sl_price, target_price, time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(token), symbol, segment, lot_size, side, lots, round(limit_price, 2), round(sl_price, 2), round(target_price, 2), ist_time_str))
        self.conn.commit()
        return True, f"⏳ Limit {side} Placed: {symbol} @ ₹{limit_price:.2f} ({ist_time_str})"

    def execute_market_order(self, token, symbol, segment, lot_size, side, lots, ltp, sl_price=0.0, target_price=0.0, reason="MARKET"):
        qty = lots * lot_size
        turnover = qty * ltp
        charges = 20.0
        bal, realized = self.get_wallet()
        c = self.conn.cursor()

        c.execute("SELECT net_qty, avg_price, sl_price, target_price FROM positions WHERE instrument_token=?", (str(token),))
        pos = c.fetchone()

        if side == "BUY":
            req = turnover + charges
            if bal < req and (not pos or pos[0] >= 0):
                return False, f"Insufficient Funds! Needed ₹{req:,.2f}"
            new_bal = bal - req
            booked = 0.0
            if pos:
                old_q, old_a, old_sl, old_tg = pos
                if old_q < 0:
                    booked = (old_a - ltp) * min(abs(old_q), qty)
                new_q = old_q + qty
                new_a = ((old_q * old_a) + turnover) / new_q if new_q > 0 else ltp
                f_sl = round(sl_price, 2) if sl_price > 0 else old_sl
                f_tg = round(target_price, 2) if target_price > 0 else old_tg
                c.execute("UPDATE positions SET net_qty=?, avg_price=?, sl_price=?, target_price=? WHERE instrument_token=?", (new_q, new_a, f_sl, f_tg, str(token)))
            else:
                c.execute("INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(token), symbol, segment, lot_size, qty, ltp, round(sl_price, 2), round(target_price, 2)))
            c.execute("UPDATE wallet SET balance=?, realized_pnl=? WHERE id=1", (new_bal, realized + booked - charges))

        elif side == "SELL":
            new_bal = bal + turnover - charges
            booked = 0.0
            if pos:
                old_q, old_a, old_sl, old_tg = pos
                if old_q > 0:
                    booked = (ltp - old_a) * min(old_q, qty)
                new_q = old_q - qty
                new_a = old_a if new_q != 0 else 0.0
                f_sl = round(sl_price, 2) if sl_price > 0 else old_sl
                f_tg = round(target_price, 2) if target_price > 0 else old_tg
                c.execute("UPDATE positions SET net_qty=?, avg_price=?, sl_price=?, target_price=? WHERE instrument_token=?", (new_q, new_a, f_sl, f_tg, str(token)))
            else:
                c.execute("INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(token), symbol, segment, lot_size, -qty, ltp, round(sl_price, 2), round(target_price, 2)))
            c.execute("UPDATE wallet SET balance=?, realized_pnl=? WHERE id=1", (new_bal, realized + booked - charges))

        c.execute("DELETE FROM positions WHERE net_qty = 0")
        ist_time_str = get_ist_now().strftime("%d %b %I:%M:%S %p")
        c.execute("INSERT INTO orders (trading_symbol, side, qty, price, order_type, charges, time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (symbol, side, qty, round(ltp, 2), reason, charges, ist_time_str))
        self.conn.commit()
        return True, f"✅ [{reason}] {side} {qty} Qty of {symbol} @ ₹{ltp:.2f} ({ist_time_str})"

    def check_triggers(self, fetcher_fn):
        c = self.conn.cursor()
        alerts = []
        c.execute("SELECT pending_id, instrument_token, trading_symbol, exchange_segment, lot_size, side, lots, limit_price, sl_price, target_price FROM pending_orders")
        for p_id, tok, sym, seg, l_size, side, lots, lim_p, sl_p, tg_p in c.fetchall():
            ltp = fetcher_fn(tok, seg)
            if ltp <= 0:
                continue
            if (side == "BUY" and ltp <= lim_p) or (side == "SELL" and ltp >= lim_p):
                ok, msg = self.execute_market_order(tok, sym, seg, l_size, side, lots, ltp, sl_p, tg_p, reason="LIMIT-FILL")
                if ok:
                    c.execute("DELETE FROM pending_orders WHERE pending_id=?", (p_id,))
                    self.conn.commit()
                    alerts.append(msg)

        c.execute("SELECT instrument_token, trading_symbol, exchange_segment, lot_size, net_qty, avg_price, sl_price, target_price FROM positions WHERE net_qty != 0")
        for tok, sym, seg, l_size, qty, avg_p, sl_p, tg_p in c.fetchall():
            ltp = fetcher_fn(tok, seg)
            if ltp <= 0:
                continue
            lots_open = abs(qty) // l_size
            if qty > 0:
                if sl_p > 0 and ltp <= sl_p:
                    ok, msg = self.execute_market_order(tok, sym, seg, l_size, "SELL", lots_open, ltp, reason="SL-HIT 🛑")
                    if ok:
                        alerts.append(msg)
                elif tg_p > 0 and ltp >= tg_p:
                    ok, msg = self.execute_market_order(tok, sym, seg, l_size, "SELL", lots_open, ltp, reason="TARGET-HIT 🎯")
                    if ok:
                        alerts.append(msg)
            elif qty < 0:
                if sl_p > 0 and ltp >= sl_p:
                    ok, msg = self.execute_market_order(tok, sym, seg, l_size, "BUY", lots_open, ltp, reason="SL-HIT 🛑")
                    if ok:
                        alerts.append(msg)
                elif tg_p > 0 and ltp <= tg_p:
                    ok, msg = self.execute_market_order(tok, sym, seg, l_size, "BUY", lots_open, ltp, reason="TARGET-HIT 🎯")
                    if ok:
                        alerts.append(msg)
        return alerts

engine = JiNeoEngine()

# ==========================================
# 3. KOTAK NEO API & IST OHLC GENERATOR
# ==========================================
def seed_or_update_candles(tok_str, ltp, meta_dict=None):
    tok_str = str(tok_str).strip()
    ltp = float(ltp)
    if ltp <= 0:
        return
    LIVE_PRICES[tok_str] = ltp

    now_ist = get_ist_now()
    if now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 30) or now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
        anchor_time = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    else:
        anchor_time = now_ist.replace(second=0, microsecond=0)

    if meta_dict is None:
        meta_dict = QUOTE_META.get(tok_str, {})

    need_seed = (tok_str not in CANDLES) or (len(CANDLES[tok_str]) < 60) or ("v5_ist" not in CANDLES[tok_str][0])

    if need_seed:
        rng = random.Random(int(tok_str) if tok_str.isdigit() else hash(tok_str))
        raw_o = float(meta_dict.get("open") or 0.0)
        raw_h = float(meta_dict.get("high") or 0.0)
        raw_l = float(meta_dict.get("low") or 0.0)

        open_p = raw_o if raw_o > 0 else round(ltp * rng.uniform(0.85, 1.20), 2)
        high_p = max(raw_h, open_p, ltp, round(max(open_p, ltp) * 1.12, 2))
        low_p = min(raw_l if raw_l > 0 else ltp, open_p, ltp, round(min(open_p, ltp) * 0.88, 2))
        low_p = max(0.05, low_p)

        n_bars = 150
        price_range = max(0.5, high_p - low_p)
        volatility = max(0.05, price_range * 0.048)

        closes = [open_p]
        curr = open_p
        for i in range(1, n_bars):
            rem = n_bars - i
            pull = (ltp - curr) / rem
            shock = rng.gauss(0, volatility)
            if rng.random() < 0.18:
                shock *= 1.75
            elif rng.random() < 0.45:
                shock *= 0.35
            curr = max(low_p, min(high_p, curr + pull + shock))
            closes.append(round(curr, 2))
        closes[-1] = round(ltp, 2)

        bars = []
        for i in range(n_bars):
            t_bar = anchor_time - timedelta(minutes=(n_bars - 1 - i))
            unix_ist = dt_to_tv_ist_timestamp(t_bar)
            b_open = closes[i - 1] if i > 0 else round(open_p, 2)
            b_close = closes[i]
            if b_open == b_close and ltp > 0.10:
                b_open = round(max(0.05, b_close + (0.05 if i % 2 == 0 else -0.05)), 2)

            body = abs(b_close - b_open)
            w_up = round(abs(rng.gauss(0, max(body * 0.75, price_range * 0.016))), 2)
            w_dn = round(abs(rng.gauss(0, max(body * 0.75, price_range * 0.016))), 2)
            b_high = round(min(high_p * 1.02, max(b_open, b_close) + w_up), 2)
            b_low = round(max(0.05, min(b_open, b_close) - w_dn), 2)

            vol_spike = 2.5 if body > volatility * 1.1 else rng.uniform(0.35, 1.25)
            vol = int(max(1500, 35000 * vol_spike))

            bars.append({
                "dt": t_bar,
                "time": unix_ist,
                "open": b_open,
                "high": b_high,
                "low": b_low,
                "close": b_close,
                "vol": vol,
                "v5_ist": True
            })
        CANDLES[tok_str] = bars
    else:
        last = CANDLES[tok_str][-1]
        unix_now = dt_to_tv_ist_timestamp(anchor_time)
        if last["time"] == unix_now:
            last["close"] = round(ltp, 2)
            last["high"] = round(max(last["high"], ltp), 2)
            last["low"] = round(min(last["low"], ltp), 2)
            last["vol"] += 250
        elif unix_now > last["time"]:
            prev_c = last["close"]
            CANDLES[tok_str].append({
                "dt": anchor_time,
                "time": unix_now,
                "open": prev_c,
                "high": round(max(prev_c, ltp), 2),
                "low": round(min(prev_c, ltp), 2),
                "close": round(ltp, 2),
                "vol": 6200,
                "v5_ist": True
            })
            if len(CANDLES[tok_str]) > 240:
                CANDLES[tok_str] = CANDLES[tok_str][-240:]

def parse_quotes(obj):
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return
    if isinstance(obj, list):
        for item in obj:
            parse_quotes(item)
    elif isinstance(obj, dict):
        tok = obj.get('exchange_token') or obj.get('instrument_token') or obj.get('tk') or obj.get('pSymbol') or obj.get('token')
        ltp = obj.get('ltp') or obj.get('last_traded_price') or obj.get('lp') or obj.get('lastPrice')
        ohlc = obj.get('ohlc') if isinstance(obj.get('ohlc'), dict) else {}
        if ltp is None and ohlc:
            ltp = ohlc.get('close')

        if tok is not None and ltp is not None:
            try:
                f = float(ltp)
                if f > 0:
                    t_str = str(tok).strip()
                    prev_close = float(ohlc.get('close') or obj.get('c') or obj.get('prev_close') or 0.0)
                    open_p = float(ohlc.get('open') or obj.get('o') or obj.get('open_price') or f)
                    high_p = float(ohlc.get('high') or obj.get('h') or obj.get('high_price') or f)
                    low_p = float(ohlc.get('low') or obj.get('l') or obj.get('low_price') or f)
                    per_chg = obj.get('per_change') or obj.get('pc') or obj.get('pChange')
                    net_chg = obj.get('change') or obj.get('chg')

                    if per_chg is not None:
                        pct = float(per_chg)
                    elif prev_close > 0:
                        pct = ((f - prev_close) / prev_close) * 100.0
                    else:
                        pct = 0.0

                    chg_val = float(net_chg) if net_chg is not None else (f - prev_close if prev_close > 0 else 0.0)
                    meta = {
                        "pct": round(pct, 2), "chg": round(chg_val, 2),
                        "open": open_p, "high": high_p, "low": low_p, "close": prev_close
                    }
                    QUOTE_META[t_str] = meta
                    seed_or_update_candles(t_str, f, meta)
            except Exception:
                pass
        for k, v in obj.items():
            if isinstance(v, (list, dict)):
                parse_quotes(v)

def setup_ws(client):
    client.on_message = lambda m: parse_quotes(m)
    client.on_error = lambda e: None
    client.on_close = lambda m: None
    client.on_open = lambda m: None

def fetch_batch(client, tokens, seg):
    clean = [str(t).strip() for t in tokens if str(t).strip()]
    if not clean:
        return
    for i in range(0, len(clean), 25):
        chunk = clean[i:i+25]
        payload = [{"instrument_token": t, "exchange_segment": seg} for t in chunk]
        try:
            res = client.quotes(instrument_tokens=payload)
            parse_quotes(res)
        except Exception:
            pass
        try:
            client.subscribe(instrument_tokens=payload, isIndex=False, isDepth=False)
        except Exception:
            pass

def get_realtime_ltp(client, token, segment):
    tok = str(token).strip()
    fetch_batch(client, [tok], segment)
    return LIVE_PRICES.get(tok, 0.0)

@st.cache_data(ttl=3600)
def load_master(_client, segment):
    try:
        url = _client.scrip_master(exchange_segment=segment)
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return pd.DataFrame()

def parse_options(df, idx_name):
    df = df.copy()
    trd = 'pTrdSymbol' if 'pTrdSymbol' in df.columns else df.columns[2]
    opt = 'pOptionType' if 'pOptionType' in df.columns else None
    df['Opt'] = df[opt].astype(str).str.strip() if opt else df[trd].astype(str).str[-2:]
    df = df[df['Opt'].isin(['CE', 'PE'])].copy()

    s_col = next((c for c in df.columns if 'Strike' in c or 'strike' in c), None)
    strikes = []
    if s_col:
        s_vals = pd.to_numeric(df[s_col], errors='coerce').fillna(0)
        if s_vals.median() > 200000:
            s_vals = s_vals / 100.0
        strikes = s_vals.astype(int).tolist()
    else:
        for sym in df[trd].astype(str):
            m = re.search(r'(\d{5})(CE|PE)$', sym)
            strikes.append(int(m.group(1)) if m else 0)
    df['Strike'] = strikes

    exp_col = next((c for c in df.columns if 'Expiry' in c or 'expiry' in c), None)
    dates, ten_yr = [], 315532800
    for _, r in df.iterrows():
        dt = None
        if exp_col and pd.notna(r[exp_col]):
            try:
                v = float(r[exp_col])
                dt = datetime.fromtimestamp(v + ten_yr if v < 1600000000 else v)
            except Exception:
                pass
        if not dt:
            sym = str(r[trd])
            body = sym[len(idx_name):-2]
            m_w = re.match(r'^(\d{2})([1-9OND])(\d{2})(\d+)$', body)
            try:
                if m_w:
                    yy, mc, dd, _ = m_w.groups()
                    mm = {'1':1,'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'O':10,'N':11,'D':12}[mc]
                    dt = datetime(2000 + int(yy), mm, int(dd))
            except Exception:
                dt = datetime(2099, 12, 31)
        dates.append(dt.date() if hasattr(dt, 'date') else datetime(2099, 12, 31).date())

    df['ExpiryDate'] = dates
    today = get_ist_now().date()
    df = df[df['ExpiryDate'] >= today].copy()
    df['ExpiryLabel'] = df['ExpiryDate'].apply(lambda d: d.strftime("%d %b %Y (%a)") if d.year < 2090 else "Upcoming")
    return df

def estimate_live_spot(df_exp, all_strikes, tok_col, seg_code, client):
    if not all_strikes:
        return 0.0, 0
    step = max(1, len(all_strikes) // 12)
    sample_strikes = all_strikes[::step]
    sub_df = df_exp[df_exp['Strike'].isin(sample_strikes)]
    fetch_batch(client, sub_df[tok_col].tolist(), seg_code)
    best_strike = all_strikes[len(all_strikes) // 2]
    min_diff, calc_spot = 999999.0, float(best_strike)
    for s in all_strikes:
        ce_r = df_exp[(df_exp['Strike'] == s) & (df_exp['Opt'] == 'CE')]
        pe_r = df_exp[(df_exp['Strike'] == s) & (df_exp['Opt'] == 'PE')]
        if not ce_r.empty and not pe_r.empty:
            cp = LIVE_PRICES.get(str(ce_r.iloc[0][tok_col]).strip(), 0.0)
            pp = LIVE_PRICES.get(str(pe_r.iloc[0][tok_col]).strip(), 0.0)
            if cp > 0 and pp > 0:
                diff = abs(cp - pp)
                if diff < min_diff:
                    min_diff, best_strike, calc_spot = diff, s, round(s + (cp - pp), 2)
    return calc_spot, best_strike

# ==========================================
# 4. FULL-PAGE BROKER CHART ENGINE (EXACT UPSTOX/TBT CLONE)
# ==========================================
def build_raw_tf_bars(df_1m, step):
    if step > 1:
        grouped = []
        for i in range(0, len(df_1m), step):
            chunk = df_1m.iloc[i:i+step]
            grouped.append({
                "time": int(chunk.iloc[-1]["time"]),
                "open": float(chunk.iloc[0]["open"]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk.iloc[-1]["close"]),
                "vol": float(chunk["vol"].sum())
            })
        return grouped
    else:
        return [
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "vol": float(r["vol"])
            }
            for _, r in df_1m.iterrows()
        ]

def render_broker_pro_chart(df_1m, sym_title, short_label, exch_name, live_p, chg, pct, lot_size):
    tf_raw_map = {
        "1m": build_raw_tf_bars(df_1m, 1),
        "3m": build_raw_tf_bars(df_1m, 3),
        "5m": build_raw_tf_bars(df_1m, 5),
        "15m": build_raw_tf_bars(df_1m, 15),
    }

    clr_hex = "#159e6b" if pct >= 0 else "#e53935"
    sign = "+" if pct >= 0 else ""

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
        <style>
            * {{
                box-sizing: border-box;
                user-select: none;
                -webkit-user-select: none;
                -webkit-touch-callout: none;
                -webkit-tap-highlight-color: transparent;
            }}
            html, body {{
                margin: 0; padding: 0; width: 100%; height: 100%;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #ffffff; overflow: hidden;
                overscroll-behavior: none;
            }}
            #app-shell {{
                position: relative; width: 100%; height: 505px;
                display: flex; flex-direction: column;
                border: 1px solid #e2e8f0; background: #ffffff;
            }}
            #top-bar {{
                height: 44px; width: 100%; display: flex; align-items: center;
                justify-content: space-between; padding: 0 8px;
                border-bottom: 1px solid #e2e8f0; background: #ffffff;
                position: relative; z-index: 100; pointer-events: auto;
            }}
            .tb-left, .tb-right {{ display: flex; align-items: center; gap: 5px; }}
            .tb-btn {{
                height: 34px; min-width: 38px; padding: 0 10px; border-radius: 6px;
                border: 1px solid #e2e8f0; background: #f8fafc; color: #1e293b;
                font-size: 13px; font-weight: 700; display: flex; align-items: center;
                justify-content: center; cursor: pointer; touch-action: manipulation;
            }}
            .tb-btn.active {{ background: #4f46e5; color: #ffffff; border-color: #4f46e5; }}
            .tb-sep {{ width: 1px; height: 22px; background: #cbd5e1; margin: 0 2px; }}
            .fx-btn {{
                font-family: Georgia, serif; font-style: italic; font-size: 16px; font-weight: bold;
                padding: 0 12px; color: #0f172a; background: #eef2ff; border: 1px solid #c7d2fe;
            }}

            #workspace {{
                position: relative; flex: 1; width: 100%;
                display: flex; flex-direction: row; overflow: hidden;
            }}
            #draw-bar {{
                width: 42px; height: 100%; background: #ffffff; border-right: 1px solid #e2e8f0;
                display: flex; flex-direction: column; align-items: center; padding-top: 6px; gap: 6px;
                z-index: 90; pointer-events: auto;
            }}
            .d-btn {{
                width: 34px; height: 34px; border-radius: 6px; border: none; background: transparent;
                color: #334155; font-size: 16px; display: flex; align-items: center; justify-content: center;
                cursor: pointer; touch-action: manipulation;
            }}
            .d-btn.active {{ background: #eef2ff; color: #4f46e5; border: 1px solid #c7d2fe; font-weight: bold; }}

            #chart-area {{
                position: relative; flex: 1; height: 100%; overflow: hidden;
                touch-action: none;
            }}
            #tv-chart {{ width: 100%; height: 100%; }}
            #draw-canvas {{
                position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                pointer-events: none; z-index: 25; touch-action: none;
            }}

            #ohlc-overlay {{
                position: absolute; top: 6px; left: 10px; z-index: 20;
                pointer-events: none; max-width: 82%;
            }}
            .sym-title {{ font-size: 13px; font-weight: 700; color: #0f172a; background: rgba(255,255,255,0.85); padding: 1px 4px; border-radius: 3px; }}
            .prc-sub {{ font-size: 12px; font-weight: 700; color: {clr_hex}; margin-top: 2px; background: rgba(255,255,255,0.85); padding: 1px 4px; border-radius: 3px; }}

            #ind-legend {{
                margin-top: 5px; display: flex; flex-direction: column; gap: 4px;
                pointer-events: auto;
            }}
            .ind-item {{
                display: inline-flex; align-items: center; gap: 6px;
                background: rgba(255,255,255,0.94); border: 1px solid #cbd5e1;
                padding: 3px 8px; border-radius: 5px; font-size: 11px; font-weight: 600; color: #1e293b;
                width: fit-content; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            }}
            .ind-act {{
                cursor: pointer; padding: 2px 5px; border-radius: 4px; font-size: 12px; color: #475569;
                touch-action: manipulation;
            }}
            .ind-act:hover {{ background: #e2e8f0; color: #0f172a; }}

            #floating-draw-menu {{
                position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
                background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.12); padding: 4px 8px;
                display: none; align-items: center; gap: 8px; z-index: 85;
            }}
            .fd-btn {{
                border: none; background: #f8fafc; padding: 4px 8px; border-radius: 5px;
                font-size: 12px; font-weight: 700; color: #1e293b; cursor: pointer;
            }}
            .clr-dot {{
                width: 18px; height: 18px; border-radius: 50%; cursor: pointer; border: 2px solid #fff;
                box-shadow: 0 0 0 1px #cbd5e1;
            }}

            #anchor-toast {{
                position: absolute; bottom: 42px; left: 50%; transform: translateX(-50%);
                background: #5b21b6; color: #ffffff; padding: 8px 14px; border-radius: 8px;
                font-size: 12px; font-weight: 600; display: none; align-items: center; gap: 10px;
                box-shadow: 0 4px 12px rgba(91,33,182,0.35); z-index: 80; white-space: nowrap;
            }}

            #bottom-bar {{
                height: 30px; width: 100%; border-top: 1px solid #e2e8f0; background: #ffffff;
                display: flex; align-items: center; justify-content: space-between;
                padding: 0 10px; font-size: 11px; color: #475569; font-weight: 600; z-index: 80;
            }}
            .b-pill {{
                padding: 2px 7px; border: 1px solid #cbd5e1; border-radius: 4px; cursor: pointer; font-weight: 700;
            }}

            #fx-modal {{
                position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                background: #ffffff; z-index: 200; display: none; flex-direction: column;
            }}
            .fx-head {{
                display: flex; align-items: center; justify-content: space-between;
                padding: 12px 16px; border-bottom: 1px solid #e2e8f0; font-size: 17px; font-weight: 800; color: #0f172a;
            }}
            .fx-search-wrap {{ padding: 10px 16px; border-bottom: 1px solid #f1f5f9; }}
            #fx-search {{
                width: 100%; padding: 9px 12px; border: 1px solid #cbd5e1; border-radius: 8px;
                font-size: 14px; outline: none; user-select: text; -webkit-user-select: text;
            }}
            .fx-list {{ flex: 1; overflow-y: auto; padding: 6px 0; }}
            .fx-row {{
                display: flex; align-items: center; justify-content: space-between;
                padding: 12px 18px; border-bottom: 1px solid #f8fafc; cursor: pointer;
                font-size: 14px; font-weight: 500; color: #1e293b;
            }}
            .fx-row:hover {{ background: #f1f5f9; }}
            .fx-badge {{ background: #2563eb; color: #fff; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; }}

            #cfg-modal {{
                position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(15,23,42,0.45); z-index: 210; display: none;
                align-items: center; justify-content: center; padding: 16px;
            }}
            .cfg-box {{
                width: 100%; max-width: 350px; background: #ffffff; border-radius: 12px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.2); overflow: hidden;
            }}
            .cfg-head {{
                display: flex; justify-content: space-between; align-items: center;
                padding: 14px 16px; border-bottom: 1px solid #e2e8f0; font-size: 16px; font-weight: 800;
            }}
            .cfg-body {{ padding: 16px; display: flex; flex-direction: column; gap: 14px; }}
            .cfg-field {{ display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 600; color: #334155; }}
            .cfg-input {{
                width: 110px; padding: 6px 10px; border: 1px solid #94a3b8; border-radius: 6px;
                font-size: 14px; font-weight: 600; text-align: left; user-select: text; -webkit-user-select: text;
            }}
            .cfg-foot {{
                display: flex; justify-content: flex-end; gap: 10px; padding: 12px 16px;
                border-top: 1px solid #e2e8f0; background: #f8fafc;
            }}
            .btn-cancel {{ padding: 7px 16px; border-radius: 6px; border: 1px solid #cbd5e1; background: #fff; font-weight: 700; cursor: pointer; }}
            .btn-ok {{ padding: 7px 20px; border-radius: 6px; border: none; background: #4c1d95; color: #fff; font-weight: 700; cursor: pointer; }}

            #green-toast {{
                position: absolute; bottom: 48px; left: 50%; transform: translateX(-50%);
                background: #334155; color: #ffffff; padding: 8px 16px; border-radius: 8px;
                font-size: 13px; font-weight: 600; display: none; z-index: 220;
                box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            }}
        </style>
    </head>
    <body>
        <div id="app-shell">
            <div id="top-bar">
                <div class="tb-left">
                    <button type="button" class="tb-btn active" id="tf-1m" onpointerdown="switchTF('1m')">1m</button>
                    <button type="button" class="tb-btn" id="tf-3m" onpointerdown="switchTF('3m')">3m</button>
                    <button type="button" class="tb-btn" id="tf-5m" onpointerdown="switchTF('5m')">5m</button>
                    <button type="button" class="tb-btn" id="tf-15m" onpointerdown="switchTF('15m')">15m</button>
                    <div class="tb-sep"></div>
                    <button type="button" class="tb-btn fx-btn" onpointerdown="openFxModal()">𝑓𝑥</button>
                </div>
                <div class="tb-right">
                    <button type="button" class="tb-btn" onpointerdown="zoomIn()">＋</button>
                    <button type="button" class="tb-btn" onpointerdown="zoomOut()">－</button>
                    <button type="button" class="tb-btn" onpointerdown="resetZoom()">⟲</button>
                </div>
            </div>

            <div id="workspace">
                <div id="draw-bar">
                    <button type="button" class="d-btn active" id="tool-none" onpointerdown="setTool('none')" title="Cursor / Drag">╋</button>
                    <button type="button" class="d-btn" id="tool-hline" onpointerdown="setTool('hline')" title="Horizontal Line">─</button>
                    <button type="button" class="d-btn" id="tool-trend" onpointerdown="setTool('trend')" title="Trend Line">╱</button>
                    <button type="button" class="d-btn" id="tool-ray" onpointerdown="setTool('ray')" title="Horizontal Ray">⇢</button>
                    <button type="button" class="d-btn" id="tool-rect" onpointerdown="setTool('rect')" title="Rectangle Zone">▭</button>
                    <button type="button" class="d-btn" id="tool-vline" onpointerdown="setTool('vline')" title="Vertical Line">│</button>
                    <button type="button" class="d-btn" onpointerdown="deleteSelectedOrUndo()" title="Undo" style="color:#f59e0b;">↶</button>
                    <button type="button" class="d-btn" onpointerdown="clearDrawings()" title="Clear All" style="color:#ef4444;">🗑</button>
                </div>

                <div id="chart-area">
                    <div id="floating-draw-menu">
                        <button type="button" class="fd-btn" onpointerdown="cycleLineWidth()" id="lw-label">2px</button>
                        <div class="clr-dot" style="background:#2563eb;" onpointerdown="setLineColor('#2563eb')"></div>
                        <div class="clr-dot" style="background:#16a34a;" onpointerdown="setLineColor('#16a34a')"></div>
                        <div class="clr-dot" style="background:#dc2626;" onpointerdown="setLineColor('#dc2626')"></div>
                        <div class="clr-dot" style="background:#9333ea;" onpointerdown="setLineColor('#9333ea')"></div>
                        <button type="button" class="fd-btn" style="color:#dc2626;" onpointerdown="deleteSelectedOrUndo()">🗑</button>
                    </div>

                    <div id="ohlc-overlay">
                        <div class="sym-title" id="sym-header">{short_label} · 1 · {exch_name}</div>
                        <div class="prc-sub" id="live-ohlc">{live_p:.2f} &nbsp;{sign}{chg:.2f} ({sign}{pct:.2f}%)</div>
                        <div id="ind-legend"></div>
                    </div>

                    <div id="anchor-toast">
                        <span id="anchor-msg">Move the point to position the anchor then tap to place</span>
                        <span style="cursor:pointer;font-weight:bold;" onpointerdown="setTool('none')">✕</span>
                    </div>

                    <div id="tv-chart"></div>
                    <canvas id="draw-canvas"></canvas>
                </div>
            </div>

            <div id="bottom-bar">
                <div>Date Range ▾ &nbsp;|&nbsp; <span id="ist-clock">--:--:--</span> IST</div>
                <div style="display:flex; gap:6px; align-items:center;">
                    <span style="color:#64748b;font-weight:700;">Powered by JiNeo</span>
                    <span class="b-pill" onpointerdown="resetZoom()">A</span>
                    <span class="b-pill" onpointerdown="toggleLogScale()">L</span>
                </div>
            </div>

            <div id="fx-modal">
                <div class="fx-head">
                    <span>Indicators</span>
                    <span style="cursor:pointer;font-size:20px;padding:4px 8px;" onpointerdown="closeFxModal()">✕</span>
                </div>
                <div class="fx-search-wrap">
                    <input type="text" id="fx-search" placeholder="🔍 Search (SuperTrend, EMA, VWAP, Bollinger)..." oninput="filterFxList()">
                </div>
                <div class="fx-list" id="fx-list-container"></div>
            </div>

            <div id="cfg-modal">
                <div class="cfg-box">
                    <div class="cfg-head">
                        <span id="cfg-title">SuperTrend</span>
                        <span style="cursor:pointer;padding:4px 8px;" onpointerdown="closeCfgModal()">✕</span>
                    </div>
                    <div class="cfg-body" id="cfg-fields"></div>
                    <div class="cfg-foot">
                        <button type="button" class="btn-cancel" onpointerdown="closeCfgModal()">Cancel</button>
                        <button type="button" class="btn-ok" onpointerdown="saveCfgModal()">Ok</button>
                    </div>
                </div>
            </div>

            <div id="green-toast">✅ Indicator added to chart</div>
        </div>

        <script>
            const rawTFMap = {json.dumps(tf_raw_map)};
            const shortLabel = "{short_label}";
            const exchName = "{exch_name}";
            let currentTF = "1m";
            let isLogScale = false;

            function updateClock() {{
                const now = new Date();
                const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
                const ist = new Date(utc + (3600000 * 5.5));
                const hh = String(ist.getHours()).padStart(2, '0');
                const mm = String(ist.getMinutes()).padStart(2, '0');
                const ss = String(ist.getSeconds()).padStart(2, '0');
                const el = document.getElementById('ist-clock');
                if (el) el.innerText = `${{hh}}:${{mm}}:${{ss}}`;
            }}
            setInterval(updateClock, 1000);
            updateClock();

            const chartArea = document.getElementById('chart-area');
            const chartEl = document.getElementById('tv-chart');
            const canvas = document.getElementById('draw-canvas');
            const ctx = canvas.getContext('2d');

            const chart = LightweightCharts.createChart(chartEl, {{
                layout: {{
                    background: {{ type: 'solid', color: '#ffffff' }},
                    textColor: '#334155',
                    fontSize: 11,
                }},
                grid: {{
                    vertLines: {{ color: 'rgba(226, 232, 240, 0.7)' }},
                    horzLines: {{ color: 'rgba(226, 232, 240, 0.7)' }},
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                }},
                rightPriceScale: {{
                    borderColor: '#e2e8f0',
                    scaleMargins: {{ top: 0.14, bottom: 0.22 }},
                    autoScale: true,
                }},
                timeScale: {{
                    borderColor: '#e2e8f0',
                    timeVisible: true,
                    secondsVisible: false,
                    rightOffset: 6,
                    barSpacing: 9,
                }},
            }});

            const candleSeries = chart.addCandlestickSeries({{
                upColor: '#159e6b', downColor: '#e53935',
                borderUpColor: '#159e6b', borderDownColor: '#e53935',
                wickUpColor: '#159e6b', wickDownColor: '#e53935',
            }});

            const volSeries = chart.addHistogramSeries({{
                priceFormat: {{ type: 'volume' }},
                priceScaleId: '',
            }});
            volSeries.priceScale().applyOptions({{
                scaleMargins: {{ top: 0.80, bottom: 0 }},
            }});

            const IND_CATALOG = [
                {{ type: 'SuperTrend', name: 'SuperTrend', badge: 'POPULAR', defaults: {{ period: 10, factor: 3, color: '#159e6b' }} }},
                {{ type: 'EMA', name: 'Moving Average Exponential (EMA)', badge: '', defaults: {{ period: 20, color: '#2563eb' }} }},
                {{ type: 'EMA_Cross', name: 'EMA Cross (Short / Long)', badge: '', defaults: {{ short: 9, long: 26, color: '#9333ea' }} }},
                {{ type: 'SMA', name: 'Moving Average Simple (SMA)', badge: '', defaults: {{ period: 50, color: '#ea580c' }} }},
                {{ type: 'VWAP', name: 'VWAP (Volume Weighted Avg Price)', badge: 'INTRADAY', defaults: {{ color: '#eab308' }} }},
                {{ type: 'BB', name: 'Bollinger Bands (BB)', badge: '', defaults: {{ period: 20, mult: 2, color: '#0891b2' }} }},
                {{ type: 'HighLow', name: 'Day High / Low Levels', badge: 'NEW', defaults: {{ color: '#64748b' }} }}
            ];

            const IND_STORAGE_KEY = "jineo_active_inds_v7";
            let activeInds = [
                {{ id: 'ind_1', type: 'SuperTrend', params: {{ period: 10, factor: 3, color: '#159e6b' }} }}
            ];
            try {{
                const savedI = localStorage.getItem(IND_STORAGE_KEY);
                if (savedI) activeInds = JSON.parse(savedI);
            }} catch(e) {{}}

            let renderedIndSeries = [];

            function saveInds() {{
                try {{ localStorage.setItem(IND_STORAGE_KEY, JSON.stringify(activeInds)); }} catch(e) {{}}
            }}

            function calcEMA(bars, period) {{
                const k = 2 / (period + 1);
                let ema = bars[0].close;
                return bars.map((b, i) => {{
                    ema = (i === 0) ? b.close : (b.close * k + ema * (1 - k));
                    return {{ time: b.time, value: Number(ema.toFixed(2)) }};
                }});
            }}

            function calcSMA(bars, period) {{
                return bars.map((b, i) => {{
                    const start = Math.max(0, i - period + 1);
                    let sum = 0;
                    for (let j = start; j <= i; j++) sum += bars[j].close;
                    return {{ time: b.time, value: Number((sum / (i - start + 1)).toFixed(2)) }};
                }});
            }}

            function calcVWAP(bars) {{
                let cumPV = 0, cumV = 0;
                return bars.map(b => {{
                    const typ = (b.high + b.low + b.close) / 3;
                    cumPV += typ * (b.vol || 1);
                    cumV += (b.vol || 1);
                    return {{ time: b.time, value: Number((cumPV / cumV).toFixed(2)) }};
                }});
            }}

            function calcBB(bars, period, mult) {{
                const upper = [], lower = [];
                bars.forEach((b, i) => {{
                    const start = Math.max(0, i - period + 1);
                    const slice = bars.slice(start, i + 1).map(x => x.close);
                    const mean = slice.reduce((a, c) => a + c, 0) / slice.length;
                    const variance = slice.reduce((a, c) => a + Math.pow(c - mean, 2), 0) / slice.length;
                    const std = Math.sqrt(variance);
                    upper.push({{ time: b.time, value: Number((mean + mult * std).toFixed(2)) }});
                    lower.push({{ time: b.time, value: Number((mean - mult * std).toFixed(2)) }});
                }});
                return {{ upper, lower }};
            }}

            function calcSuperTrend(bars, period, factor) {{
                if (bars.length === 0) return [];
                const tr = bars.map((b, i) => {{
                    if (i === 0) return b.high - b.low;
                    const pc = bars[i - 1].close;
                    return Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
                }});
                const atr = [];
                let sum = 0;
                for (let i = 0; i < bars.length; i++) {{
                    if (i < period) {{
                        sum += tr[i];
                        atr.push(sum / (i + 1));
                    }} else {{
                        atr.push(((atr[i - 1] * (period - 1)) + tr[i]) / period);
                    }}
                }}
                const finalUpper = [], finalLower = [], st = [], dir = [];
                for (let i = 0; i < bars.length; i++) {{
                    const hl2 = (bars[i].high + bars[i].low) / 2;
                    const bu = hl2 + factor * atr[i];
                    const bl = hl2 - factor * atr[i];
                    if (i === 0) {{
                        finalUpper.push(bu);
                        finalLower.push(bl);
                        st.push(bl);
                        dir.push(1);
                    }} else {{
                        const fu = (bu < finalUpper[i - 1] || bars[i - 1].close > finalUpper[i - 1]) ? bu : finalUpper[i - 1];
                        const fl = (bl > finalLower[i - 1] || bars[i - 1].close < finalLower[i - 1]) ? bl : finalLower[i - 1];
                        finalUpper.push(fu);
                        finalLower.push(fl);
                        let d = dir[i - 1];
                        if (d === -1 && bars[i].close > finalUpper[i - 1]) d = 1;
                        else if (d === 1 && bars[i].close < finalLower[i - 1]) d = -1;
                        dir.push(d);
                        st.push(d === 1 ? fl : fu);
                    }}
                }}
                return bars.map((b, i) => ({{
                    time: b.time,
                    value: Number(st[i].toFixed(2)),
                    color: dir[i] === 1 ? '#159e6b' : '#dc2626'
                }}));
            }}

            function rebuildIndicators() {{
                renderedIndSeries.forEach(s => chart.removeSeries(s));
                renderedIndSeries = [];

                const bars = rawTFMap[currentTF] || [];
                if (bars.length === 0) return;

                const legendEl = document.getElementById('ind-legend');
                legendEl.innerHTML = '';

                activeInds.forEach(ind => {{
                    let lastValText = '';
                    let labelText = '';
                    let badgeClr = ind.params.color || '#2563eb';

                    if (ind.type === 'SuperTrend') {{
                        const p = Number(ind.params.period || 10);
                        const f = Number(ind.params.factor || 3);
                        const stData = calcSuperTrend(bars, p, f);
                        const s = chart.addLineSeries({{ lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        s.setData(stData);
                        renderedIndSeries.push(s);
                        const lastPt = stData[stData.length - 1];
                        lastValText = lastPt ? lastPt.value.toFixed(2) : '';
                        badgeClr = lastPt ? lastPt.color : '#159e6b';
                        labelText = `SuperTrend ${{p}} ${{f}}`;
                    }} else if (ind.type === 'EMA') {{
                        const p = Number(ind.params.period || 20);
                        const d = calcEMA(bars, p);
                        const s = chart.addLineSeries({{ color: badgeClr, lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        s.setData(d);
                        renderedIndSeries.push(s);
                        lastValText = d[d.length - 1].value.toFixed(2);
                        labelText = `EMA ${{p}}`;
                    }} else if (ind.type === 'EMA_Cross') {{
                        const sh = Number(ind.params.short || 9);
                        const lg = Number(ind.params.long || 26);
                        const d1 = calcEMA(bars, sh);
                        const d2 = calcEMA(bars, lg);
                        const s1 = chart.addLineSeries({{ color: '#16a34a', lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        const s2 = chart.addLineSeries({{ color: '#dc2626', lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        s1.setData(d1); s2.setData(d2);
                        renderedIndSeries.push(s1, s2);
                        lastValText = `${{d1[d1.length - 1].value.toFixed(1)}} / ${{d2[d2.length - 1].value.toFixed(1)}}`;
                        labelText = `EMA Cross ${{sh}} ${{lg}}`;
                    }} else if (ind.type === 'SMA') {{
                        const p = Number(ind.params.period || 50);
                        const d = calcSMA(bars, p);
                        const s = chart.addLineSeries({{ color: badgeClr, lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        s.setData(d);
                        renderedIndSeries.push(s);
                        lastValText = d[d.length - 1].value.toFixed(2);
                        labelText = `SMA ${{p}}`;
                    }} else if (ind.type === 'VWAP') {{
                        const d = calcVWAP(bars);
                        const s = chart.addLineSeries({{ color: badgeClr, lineWidth: 2, priceLineVisible: false, lastValueVisible: true }});
                        s.setData(d);
                        renderedIndSeries.push(s);
                        lastValText = d[d.length - 1].value.toFixed(2);
                        labelText = `VWAP`;
                    }} else if (ind.type === 'BB') {{
                        const p = Number(ind.params.period || 20);
                        const m = Number(ind.params.mult || 2);
                        const bb = calcBB(bars, p, m);
                        const su = chart.addLineSeries({{ color: badgeClr, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
                        const sl = chart.addLineSeries({{ color: badgeClr, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
                        su.setData(bb.upper); sl.setData(bb.lower);
                        renderedIndSeries.push(su, sl);
                        lastValText = `${{bb.upper[bb.upper.length - 1].value.toFixed(1)}}`;
                        labelText = `BB ${{p}} ${{m}}`;
                    }} else if (ind.type === 'HighLow') {{
                        const hi = Math.max(...bars.map(b => b.high));
                        const lo = Math.min(...bars.map(b => b.low));
                        const sh = chart.addLineSeries({{ color: '#16a34a', lineWidth: 1, lineStyle: 2, priceLineVisible: false }});
                        const sl = chart.addLineSeries({{ color: '#dc2626', lineWidth: 1, lineStyle: 2, priceLineVisible: false }});
                        sh.setData(bars.map(b => ({{ time: b.time, value: hi }})));
                        sl.setData(bars.map(b => ({{ time: b.time, value: lo }})));
                        renderedIndSeries.push(sh, sl);
                        lastValText = `H:${{hi.toFixed(1)}} L:${{lo.toFixed(1)}}`;
                        labelText = `Day High/Low`;
                    }}

                    const item = document.createElement('div');
                    item.className = 'ind-item';
                    item.innerHTML = `
                        <span>${{labelText}}</span>
                        <span style="color:${{badgeClr}};font-weight:800;">${{lastValText}}</span>
                        <span class="ind-act" onpointerdown="openCfgModal('${{ind.id}}')" title="Settings">⚙️</span>
                        <span class="ind-act" onpointerdown="removeInd('${{ind.id}}')" title="Remove">✕</span>
                    `;
                    legendEl.appendChild(item);
                }});
            }}

            function switchTF(tfKey) {{
                if (!rawTFMap[tfKey]) return;
                currentTF = tfKey;
                document.querySelectorAll('#top-bar .tb-btn').forEach(b => b.classList.remove('active'));
                const btn = document.getElementById('tf-' + tfKey);
                if (btn) btn.classList.add('active');

                const tfNum = tfKey.replace('m', '');
                document.getElementById('sym-header').innerText = `${{shortLabel}} · ${{tfNum}} · ${{exchName}}`;

                const bars = rawTFMap[tfKey];
                candleSeries.setData(bars.map(b => ({{ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }})));
                volSeries.setData(bars.map(b => ({{
                    time: b.time,
                    value: b.vol,
                    color: b.close >= b.open ? 'rgba(21, 158, 107, 0.35)' : 'rgba(229, 57, 53, 0.35)'
                }})));

                rebuildIndicators();
                chart.timeScale().fitContent();
                setTimeout(redrawShapes, 30);
            }}

            function openFxModal() {{
                document.getElementById('fx-modal').style.display = 'flex';
                document.getElementById('fx-search').value = '';
                renderFxCatalog('');
            }}
            function closeFxModal() {{
                document.getElementById('fx-modal').style.display = 'none';
            }}
            function filterFxList() {{
                const q = document.getElementById('fx-search').value.toLowerCase();
                renderFxCatalog(q);
            }}
            function renderFxCatalog(query) {{
                const container = document.getElementById('fx-list-container');
                container.innerHTML = '';
                IND_CATALOG.filter(item => item.name.toLowerCase().includes(query) || item.type.toLowerCase().includes(query)).forEach(item => {{
                    const row = document.createElement('div');
                    row.className = 'fx-row';
                    row.innerHTML = `
                        <span>☆ &nbsp; ${{item.name}}</span>
                        ${{item.badge ? `<span class="fx-badge">${{item.badge}}</span>` : ''}}
                    `;
                    row.onpointerdown = () => {{
                        const newId = 'ind_' + Date.now();
                        activeInds.push({{ id: newId, type: item.type, params: JSON.parse(JSON.stringify(item.defaults)) }});
                        saveInds();
                        rebuildIndicators();
                        closeFxModal();
                        showToast(`✅ ${{item.type}} added to chart`);
                    }};
                    container.appendChild(row);
                }});
            }}

            function removeInd(id) {{
                activeInds = activeInds.filter(x => x.id !== id);
                saveInds();
                rebuildIndicators();
            }}

            let editingIndId = null;
            function openCfgModal(id) {{
                const ind = activeInds.find(x => x.id === id);
                if (!ind) return;
                editingIndId = id;
                document.getElementById('cfg-title').innerText = ind.type;
                const fieldsEl = document.getElementById('cfg-fields');
                fieldsEl.innerHTML = '';

                Object.keys(ind.params).forEach(k => {{
                    const labelMap = {{ period: 'Length', factor: 'Factor', short: 'Short Length', long: 'Long Length', mult: 'StdDev Multiplier', color: 'Line Color' }};
                    const row = document.createElement('div');
                    row.className = 'cfg-field';
                    const inputType = (k === 'color') ? 'color' : 'number';
                    row.innerHTML = `
                        <span>${{labelMap[k] || k}}</span>
                        <input class="cfg-input" type="${{inputType}}" id="cfg-in-${{k}}" value="${{ind.params[k]}}" step="any">
                    `;
                    fieldsEl.appendChild(row);
                }});
                document.getElementById('cfg-modal').style.display = 'flex';
            }}

            function closeCfgModal() {{
                document.getElementById('cfg-modal').style.display = 'none';
                editingIndId = null;
            }}

            function saveCfgModal() {{
                const ind = activeInds.find(x => x.id === editingIndId);
                if (ind) {{
                    Object.keys(ind.params).forEach(k => {{
                        const el = document.getElementById('cfg-in-' + k);
                        if (el) {{
                            ind.params[k] = (k === 'color') ? el.value : Number(el.value);
                        }}
                    }});
                    saveInds();
                    rebuildIndicators();
                }}
                closeCfgModal();
            }}

            function showToast(msg) {{
                const t = document.getElementById('green-toast');
                t.innerText = msg;
                t.style.display = 'block';
                setTimeout(() => {{ t.style.display = 'none'; }}, 2000);
            }}

            function zoomIn() {{
                const ts = chart.timeScale();
                chart.applyOptions({{ timeScale: {{ barSpacing: Math.min(40, ts.options().barSpacing * 1.3) }} }});
                redrawShapes();
            }}
            function zoomOut() {{
                const ts = chart.timeScale();
                chart.applyOptions({{ timeScale: {{ barSpacing: Math.max(3, ts.options().barSpacing * 0.75) }} }});
                redrawShapes();
            }}
            function resetZoom() {{
                chart.timeScale().fitContent();
                chart.priceScale('right').applyOptions({{ autoScale: true }});
                setTimeout(redrawShapes, 30);
            }}
            function toggleLogScale() {{
                isLogScale = !isLogScale;
                chart.priceScale('right').applyOptions({{
                    mode: isLogScale ? LightweightCharts.PriceScaleMode.Logarithmic : LightweightCharts.PriceScaleMode.Normal
                }});
            }}

            const DRAW_KEY = "jineo_draw_v8_" + shortLabel;
            let currentTool = 'none';
            let shapes = [];
            try {{
                const savedD = localStorage.getItem(DRAW_KEY);
                if (savedD) shapes = JSON.parse(savedD);
            }} catch(e) {{}}

            let selectedIdx = -1;
            let dragMode = null;
            let dragStartAnchor = null;
            let dragOrigShape = null;
            let previewShape = null;

            function saveShapes() {{
                try {{ localStorage.setItem(DRAW_KEY, JSON.stringify(shapes)); }} catch(e) {{}}
            }}

            function updateFloatingMenu() {{
                const menu = document.getElementById('floating-draw-menu');
                if (selectedIdx >= 0 && selectedIdx < shapes.length) {{
                    menu.style.display = 'flex';
                    document.getElementById('lw-label').innerText = (shapes[selectedIdx].width || 2) + 'px';
                }} else {{
                    menu.style.display = 'none';
                }}
            }}

            function cycleLineWidth() {{
                if (selectedIdx >= 0 && selectedIdx < shapes.length) {{
                    const cur = shapes[selectedIdx].width || 2;
                    shapes[selectedIdx].width = cur === 2 ? 3 : (cur === 3 ? 4 : 2);
                    saveShapes();
                    updateFloatingMenu();
                    redrawShapes();
                }}
            }}

            function setLineColor(clr) {{
                if (selectedIdx >= 0 && selectedIdx < shapes.length) {{
                    shapes[selectedIdx].color = clr;
                    saveShapes();
                    redrawShapes();
                }}
            }}

            function setChartInteraction(enabled) {{
                chart.applyOptions({{
                    handleScroll: {{ mouseWheel: enabled, pressedMouseMove: enabled, horzTouchDrag: enabled, vertTouchDrag: enabled }},
                    handleScale: {{ axisPressedMouseMove: {{ time: enabled, price: enabled }}, mouseWheel: enabled, pinch: enabled }}
                }});
            }}

            function screenToAnchor(x, y) {{
                const logical = chart.timeScale().coordinateToLogical(x);
                const price = candleSeries.coordinateToPrice(y);
                return {{ logical: logical, price: price }};
            }}

            function anchorToScreen(a) {{
                if (!a || a.logical === null || a.price === null) return null;
                const x = chart.timeScale().logicalToCoordinate(a.logical);
                const y = candleSeries.priceToCoordinate(a.price);
                if (x === null || y === null) return null;
                return {{ x: x, y: y }};
            }}

            function distToSegment(px, py, x1, y1, x2, y2) {{
                const A = px - x1, B = py - y1, C = x2 - x1, D = y2 - y1;
                const dot = A * C + B * D;
                const lenSq = C * C + D * D;
                let param = -1;
                if (lenSq !== 0) param = dot / lenSq;
                let xx, yy;
                if (param < 0) {{ xx = x1; yy = y1; }}
                else if (param > 1) {{ xx = x2; yy = y2; }}
                else {{ xx = x1 + param * C; yy = y1 + param * D; }}
                return Math.hypot(px - xx, py - yy);
            }}

            function findHitShape(x, y) {{
                const TOL = 24;
                for (let i = shapes.length - 1; i >= 0; i--) {{
                    const s = shapes[i];
                    if (s.type === 'hline') {{
                        const sy = candleSeries.priceToCoordinate(s.price);
                        if (sy !== null && Math.abs(y - sy) <= TOL) return {{ index: i, mode: 'move_hline' }};
                    }} else if (s.type === 'vline') {{
                        const sx = chart.timeScale().logicalToCoordinate(s.logical);
                        if (sx !== null && Math.abs(x - sx) <= TOL) return {{ index: i, mode: 'move_vline' }};
                    }} else if (s.type === 'ray') {{
                        const pt = anchorToScreen(s.p1);
                        if (pt) {{
                            if (Math.hypot(x - pt.x, y - pt.y) <= TOL) return {{ index: i, mode: 'move_p1' }};
                            if (x >= pt.x && Math.abs(y - pt.y) <= TOL) return {{ index: i, mode: 'move_p1' }};
                        }}
                    }} else if (s.type === 'trend') {{
                        const pt1 = anchorToScreen(s.p1);
                        const pt2 = anchorToScreen(s.p2);
                        if (pt1 && pt2) {{
                            if (Math.hypot(x - pt1.x, y - pt1.y) <= TOL) return {{ index: i, mode: 'move_p1' }};
                            if (Math.hypot(x - pt2.x, y - pt2.y) <= TOL) return {{ index: i, mode: 'move_p2' }};
                            if (distToSegment(x, y, pt1.x, pt1.y, pt2.x, pt2.y) <= TOL) return {{ index: i, mode: 'move_both' }};
                        }}
                    }} else if (s.type === 'rect') {{
                        const pt1 = anchorToScreen(s.p1);
                        const pt2 = anchorToScreen(s.p2);
                        if (pt1 && pt2) {{
                            if (Math.hypot(x - pt1.x, y - pt1.y) <= TOL) return {{ index: i, mode: 'move_p1' }};
                            if (Math.hypot(x - pt2.x, y - pt2.y) <= TOL) return {{ index: i, mode: 'move_p2' }};
                            const minX = Math.min(pt1.x, pt2.x), maxX = Math.max(pt1.x, pt2.x);
                            const minY = Math.min(pt1.y, pt2.y), maxY = Math.max(pt1.y, pt2.y);
                            if (x >= minX - TOL && x <= maxX + TOL && y >= minY - TOL && y <= maxY + TOL) {{
                                return {{ index: i, mode: 'move_both' }};
                            }}
                        }}
                    }}
                }}
                return null;
            }}

            function setTool(t) {{
                currentTool = t;
                dragMode = null;
                previewShape = null;
                document.querySelectorAll('#draw-bar .d-btn').forEach(b => b.classList.remove('active'));
                const btn = document.getElementById('tool-' + t);
                if (btn) btn.classList.add('active');

                const toastEl = document.getElementById('anchor-toast');
                if (t === 'none') {{
                    toastEl.style.display = 'none';
                    canvas.style.pointerEvents = 'none';
                    setChartInteraction(true);
                }} else {{
                    toastEl.style.display = 'flex';
                    canvas.style.pointerEvents = 'auto';
                    setChartInteraction(false);
                }}
                redrawShapes();
            }}

            function deleteSelectedOrUndo() {{
                if (selectedIdx >= 0 && selectedIdx < shapes.length) {{
                    shapes.splice(selectedIdx, 1);
                    selectedIdx = -1;
                }} else {{
                    shapes.pop();
                }}
                saveShapes();
                updateFloatingMenu();
                redrawShapes();
            }}

            function clearDrawings() {{
                shapes = [];
                selectedIdx = -1;
                saveShapes();
                updateFloatingMenu();
                redrawShapes();
                setTool('none');
            }}

            function getTouchOrMouseXY(e) {{
                const r = chartArea.getBoundingClientRect();
                const pt = (e.touches && e.touches[0]) ? e.touches[0] : ((e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0] : e);
                return {{ x: pt.clientX - r.left, y: pt.clientY - r.top }};
            }}

            function handleStart(e) {{
                if (e.target.closest('#floating-draw-menu') || e.target.closest('#ind-legend')) return;
                const xy = getTouchOrMouseXY(e);
                const anchor = screenToAnchor(xy.x, xy.y);
                if (anchor.logical === null || anchor.price === null) return;

                if (currentTool === 'none') {{
                    const hit = findHitShape(xy.x, xy.y);
                    if (hit) {{
                        selectedIdx = hit.index;
                        dragMode = hit.mode;
                        dragStartAnchor = anchor;
                        dragOrigShape = JSON.parse(JSON.stringify(shapes[selectedIdx]));
                        setChartInteraction(false);
                        updateFloatingMenu();
                        if (e.cancelable) e.preventDefault();
                        e.stopPropagation();
                        redrawShapes();
                        return;
                    }} else {{
                        if (selectedIdx !== -1) {{
                            selectedIdx = -1;
                            updateFloatingMenu();
                            redrawShapes();
                        }}
                        return;
                    }}
                }}

                if (e.cancelable) e.preventDefault();
                e.stopPropagation();

                if (currentTool === 'hline') {{
                    shapes.push({{ type: 'hline', price: anchor.price, color: '#2563eb', width: 2 }});
                    selectedIdx = shapes.length - 1;
                    saveShapes();
                    setTool('none');
                    updateFloatingMenu();
                    return;
                }}
                if (currentTool === 'vline') {{
                    shapes.push({{ type: 'vline', logical: anchor.logical, color: '#2563eb', width: 2 }});
                    selectedIdx = shapes.length - 1;
                    saveShapes();
                    setTool('none');
                    updateFloatingMenu();
                    return;
                }}
                if (currentTool === 'ray') {{
                    shapes.push({{ type: 'ray', p1: anchor, color: '#2563eb', width: 2 }});
                    selectedIdx = shapes.length - 1;
                    saveShapes();
                    setTool('none');
                    updateFloatingMenu();
                    return;
                }}

                dragMode = 'create';
                dragStartAnchor = anchor;
                previewShape = {{
                    type: currentTool,
                    p1: anchor,
                    p2: {{ logical: anchor.logical + 6, price: anchor.price }},
                    color: '#2563eb',
                    width: 2
                }};
                redrawShapes();
            }}

            function handleMove(e) {{
                if (!dragMode) return;
                if (e.cancelable) e.preventDefault();
                e.stopPropagation();

                const xy = getTouchOrMouseXY(e);
                const anchor = screenToAnchor(xy.x, xy.y);
                if (anchor.logical === null || anchor.price === null) return;

                if (dragMode === 'create' && previewShape) {{
                    previewShape.p2 = anchor;
                    redrawShapes();
                    return;
                }}

                if (selectedIdx >= 0 && selectedIdx < shapes.length) {{
                    const s = shapes[selectedIdx];
                    const dLog = anchor.logical - dragStartAnchor.logical;
                    const dPrc = anchor.price - dragStartAnchor.price;

                    if (dragMode === 'move_hline') {{
                        s.price = anchor.price;
                    }} else if (dragMode === 'move_vline') {{
                        s.logical = anchor.logical;
                    }} else if (dragMode === 'move_p1') {{
                        s.p1 = anchor;
                    }} else if (dragMode === 'move_p2') {{
                        s.p2 = anchor;
                    }} else if (dragMode === 'move_both') {{
                        s.p1 = {{ logical: dragOrigShape.p1.logical + dLog, price: dragOrigShape.p1.price + dPrc }};
                        s.p2 = {{ logical: dragOrigShape.p2.logical + dLog, price: dragOrigShape.p2.price + dPrc }};
                    }}
                    redrawShapes();
                }}
            }}

            function handleEnd(e) {{
                if (!dragMode) return;
                if (e.cancelable) e.preventDefault();
                e.stopPropagation();

                if (dragMode === 'create' && previewShape) {{
                    if (Math.abs(previewShape.p1.logical - previewShape.p2.logical) < 0.3) {{
                        previewShape.p2 = {{ logical: previewShape.p1.logical + 10, price: previewShape.p1.price }};
                    }}
                    shapes.push(previewShape);
                    selectedIdx = shapes.length - 1;
                    previewShape = null;
                    saveShapes();
                    setTool('none');
                    updateFloatingMenu();
                }} else {{
                    saveShapes();
                    setChartInteraction(true);
                    updateFloatingMenu();
                }}
                dragMode = null;
                redrawShapes();
            }}

            chartArea.addEventListener('touchstart', handleStart, {{ passive: false, capture: true }});
            window.addEventListener('touchmove', handleMove, {{ passive: false, capture: true }});
            window.addEventListener('touchend', handleEnd, {{ passive: false, capture: true }});

            chartArea.addEventListener('mousedown', handleStart, true);
            window.addEventListener('mousemove', handleMove, true);
            window.addEventListener('mouseup', handleEnd, true);

            function drawBrokerHandle(x, y, color, isSelected) {{
                ctx.save();
                ctx.fillStyle = '#ffffff';
                ctx.strokeStyle = color;
                ctx.lineWidth = 2.5;
                if (isSelected) {{
                    const sz = 14;
                    ctx.beginPath();
                    ctx.roundRect(x - sz/2, y - sz/2, sz, sz, 4);
                    ctx.fill();
                    ctx.stroke();
                }} else {{
                    ctx.beginPath();
                    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();
                }}
                ctx.restore();
            }}

            function drawShape(s, isSelected) {{
                ctx.save();
                const clr = s.color || '#2563eb';
                ctx.strokeStyle = clr;
                ctx.lineWidth = s.width || 2;

                if (s.type === 'hline') {{
                    const y = candleSeries.priceToCoordinate(s.price);
                    if (y !== null) {{
                        ctx.beginPath();
                        ctx.moveTo(0, y);
                        ctx.lineTo(canvas.width, y);
                        ctx.stroke();
                        drawBrokerHandle(canvas.width * 0.52, y, clr, isSelected);
                        ctx.fillStyle = clr;
                        ctx.fillRect(canvas.width - 58, y - 10, 56, 20);
                        ctx.fillStyle = '#ffffff';
                        ctx.font = 'bold 11px sans-serif';
                        ctx.fillText(s.price.toFixed(2), canvas.width - 52, y + 4);
                    }}
                }} else if (s.type === 'vline') {{
                    const x = chart.timeScale().logicalToCoordinate(s.logical);
                    if (x !== null) {{
                        ctx.beginPath();
                        ctx.moveTo(x, 0);
                        ctx.lineTo(x, canvas.height);
                        ctx.stroke();
                        drawBrokerHandle(x, canvas.height * 0.5, clr, isSelected);
                    }}
                }} else if (s.type === 'ray') {{
                    const pt = anchorToScreen(s.p1);
                    if (pt) {{
                        ctx.beginPath();
                        ctx.moveTo(pt.x, pt.y);
                        ctx.lineTo(canvas.width, pt.y);
                        ctx.stroke();
                        drawBrokerHandle(pt.x, pt.y, clr, isSelected);
                    }}
                }} else if (s.type === 'trend') {{
                    const pt1 = anchorToScreen(s.p1);
                    const pt2 = anchorToScreen(s.p2);
                    if (pt1 && pt2) {{
                        ctx.beginPath();
                        ctx.moveTo(pt1.x, pt1.y);
                        ctx.lineTo(pt2.x, pt2.y);
                        ctx.stroke();
                        drawBrokerHandle(pt1.x, pt1.y, clr, isSelected);
                        drawBrokerHandle(pt2.x, pt2.y, clr, isSelected);
                    }}
                }} else if (s.type === 'rect') {{
                    const pt1 = anchorToScreen(s.p1);
                    const pt2 = anchorToScreen(s.p2);
                    if (pt1 && pt2) {{
                        const rx = Math.min(pt1.x, pt2.x), ry = Math.min(pt1.y, pt2.y);
                        const rw = Math.abs(pt2.x - pt1.x), rh = Math.abs(pt2.y - pt1.y);
                        ctx.fillStyle = clr + '22';
                        ctx.fillRect(rx, ry, rw, rh);
                        ctx.strokeRect(rx, ry, rw, rh);
                        drawBrokerHandle(pt1.x, pt1.y, clr, isSelected);
                        drawBrokerHandle(pt2.x, pt2.y, clr, isSelected);
                    }}
                }}
                ctx.restore();
            }}

            function redrawShapes() {{
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                shapes.forEach((s, idx) => drawShape(s, idx === selectedIdx));
                if (previewShape) drawShape(previewShape, true);
            }}

            function resizeCanvas() {{
                const rect = chartArea.getBoundingClientRect();
                canvas.width = rect.width;
                canvas.height = rect.height;
                chart.resize(rect.width, rect.height);
                redrawShapes();
            }}

            window.addEventListener('resize', resizeCanvas);
            chart.timeScale().subscribeVisibleLogicalRangeChange(redrawShapes);

            function syncLoop() {{
                redrawShapes();
                requestAnimationFrame(syncLoop);
            }}
            requestAnimationFrame(syncLoop);

            switchTF('1m');
            setTimeout(resizeCanvas, 50);
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=512, scrolling=False)

# ==========================================
# 5. MAIN UI & ZERO-HEADER BROKER STYLING
# ==========================================
st.set_page_config(page_title="JiNeo", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    header[data-testid="stHeader"],
    div[data-testid="stToolbar"],
    div[data-testid="stDecoration"],
    div[data-testid="collapsedControl"],
    button[kind="header"] {
        display: none !important;
        height: 0px !important;
        width: 0px !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    .block-container {
        padding-top: 0.15rem !important;
        padding-bottom: 1.0rem !important;
        padding-left: 0.25rem !important;
        padding-right: 0.25rem !important;
        max-width: 100% !important;
    }
    .st-key-option_chain [data-testid="stHorizontalBlock"],
    .st-key-broker_top_nav [data-testid="stHorizontalBlock"],
    .st-key-broker_sub_tabs [data-testid="stHorizontalBlock"],
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"],
    .st-key-bottom_pills [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 5px !important;
        width: 100% !important;
    }
    .st-key-option_chain [data-testid="stHorizontalBlock"] > div,
    .st-key-broker_top_nav [data-testid="stHorizontalBlock"] > div,
    .st-key-broker_sub_tabs [data-testid="stHorizontalBlock"] > div,
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"] > div,
    .st-key-bottom_pills [data-testid="stHorizontalBlock"] > div {
        min-width: 0 !important;
        flex: 1 1 auto !important;
    }
    .st-key-broker_top_nav div[data-testid="stButton"] button {
        height: 38px !important;
        min-height: 38px !important;
        padding: 0 10px !important;
        font-size: 18px !important;
        font-weight: 900 !important;
        border-radius: 8px !important;
        border: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        color: #0f172a !important;
    }
    .st-key-broker_sub_tabs div[data-testid="stButton"] button {
        height: 32px !important;
        min-height: 32px !important;
        border-radius: 0px !important;
        border: none !important;
        border-bottom: 2px solid #4f46e5 !important;
        background: transparent !important;
        color: #0f172a !important;
        font-size: 13px !important;
        font-weight: 800 !important;
    }
    .st-key-option_chain div[data-testid="stButton"] button {
        width: 100% !important;
        min-height: 2.3rem !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        padding: 2px 4px !important;
        border-radius: 6px !important;
    }
    .st-key-option_chain [data-testid="stHorizontalBlock"] > :nth-child(1) button {
        background: #f0fdf4 !important; color: #15803d !important; border: 1px solid #bbf7d0 !important;
    }
    .st-key-option_chain [data-testid="stHorizontalBlock"] > :nth-child(3) button {
        background: #fef2f2 !important; color: #b91c1c !important; border: 1px solid #fecaca !important;
    }
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"] > :nth-child(1) button,
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"] > :nth-child(2) button {
        background: #f8fafc !important;
        color: #1e293b !important;
        border: 1px solid #cbd5e1 !important;
        height: 40px !important;
        border-radius: 8px !important;
        font-size: 12px !important;
        font-weight: 700 !important;
    }
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"] > :nth-child(3) button {
        background-color: #15803d !important;
        color: white !important;
        border: none !important;
        height: 40px !important;
        border-radius: 8px !important;
        font-size: 15px !important;
        font-weight: 800 !important;
    }
    .st-key-broker_bottom_bar [data-testid="stHorizontalBlock"] > :nth-child(4) button {
        background-color: #dc2626 !important;
        color: white !important;
        border: none !important;
        height: 40px !important;
        border-radius: 8px !important;
        font-size: 15px !important;
        font-weight: 800 !important;
    }
    .st-key-bottom_pills div[data-testid="stButton"] button {
        border-radius: 20px !important;
        border: 1px solid #64748b !important;
        background: white !important;
        color: #1e293b !important;
        height: 35px !important;
        font-size: 12px !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)

saved_ck, saved_mob, saved_ucc, saved_mpin = engine.get_creds()
client = STORE["client"]

# =========================================================================
# LOGIN SCREEN (CENTERED LOGO, NO JINEO PLAIN TEXT)
# =========================================================================
if not client:
    render_centered_jineo_logo(max_width=240)
    with st.container(border=True):
        st.subheader("🔐 Kotak Neo API Login")
        ck = st.text_input("Consumer Key", value=saved_ck, type="password")
        mob = st.text_input("Mobile (+91...)", value=saved_mob)
        ucc = st.text_input("Client Code (UCC)", value=saved_ucc)
        totp = st.text_input("6-Digit Live TOTP")
        mpin = st.text_input("6-Digit MPIN", value=saved_mpin, type="password")
        if st.button("🚀 Connect Terminal", type="primary", use_container_width=True):
            try:
                c_obj = NeoAPI(consumer_key=ck.strip(), environment='prod')
                c_obj.totp_login(mobile_number=mob.strip(), ucc=ucc.strip(), totp=totp.strip())
                c_obj.totp_validate(mpin=mpin.strip())
                setup_ws(c_obj)
                STORE["client"] = c_obj
                engine.save_creds(ck.strip(), mob.strip(), ucc.strip(), mpin.strip())
                st.rerun()
            except Exception as e:
                st.error(f"Login Error: {e}")
else:
    if "active_screen" not in st.session_state:
        st.session_state["active_screen"] = "CHAIN"

    # =========================================================================
    # SCREEN 1: BROKER CHART VIEW
    # =========================================================================
    if st.session_state["active_screen"] == "CHART" and "trade_token" in st.session_state:
        trd = st.session_state["trade_token"]
        tok = str(trd["token"]).strip()
        sym = trd["symbol"]
        seg = trd["segment"]
        lot_size = trd["lot"]
        short_label = trd.get("label", sym)
        exp_sub = trd.get("expiry_sub", "NFO")

        curr_ltp = get_realtime_ltp(client, tok, seg)
        if curr_ltp <= 0:
            curr_ltp = max(float(trd.get("ltp", 39.0)), 0.05)

        seed_or_update_candles(tok, curr_ltp)

        meta = QUOTE_META.get(tok, {})
        pct = meta.get("pct", -46.12 if curr_ltp < 100 else 18.5)
        chg = meta.get("chg", round(curr_ltp * (pct / 100.0), 2))
        clr_txt = "#16a34a" if pct >= 0 else "#dc2626"
        sign_txt = "+" if pct >= 0 else ""

        with st.container(key="broker_top_nav"):
            n_back, n_title, n_price = st.columns([0.75, 2.75, 1.8])
            with n_back:
                if st.button("←", key="btn_back_to_chain", use_container_width=True):
                    st.session_state["active_screen"] = "CHAIN"
                    st.rerun()
            with n_title:
                st.markdown(
                    f"<div style='line-height:1.15; padding-left:2px;'>"
                    f"<div style='font-size:14px; font-weight:800; color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{short_label} ⌄</div>"
                    f"<div style='font-size:10px; font-weight:600; color:#64748b;'>{exp_sub}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with n_price:
                st.markdown(
                    f"<div style='text-align:right; line-height:1.15; padding-right:4px;'>"
                    f"<div style='font-size:15px; font-weight:800; color:{clr_txt};'>{curr_ltp:.2f}</div>"
                    f"<div style='font-size:10px; font-weight:600; color:#64748b;'>{sign_txt}{chg:.2f} ({sign_txt}{pct:.2f}%)</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )

        with st.container(key="broker_sub_tabs"):
            st1, st2 = st.columns(2)
            with st1:
                st.button("📈 Charts", key="sub_tab_chart", use_container_width=True)
            with st2:
                if st.button("⛓️ Option chain", key="sub_tab_chain", use_container_width=True):
                    st.session_state["active_screen"] = "CHAIN"
                    st.rerun()

        raw_bars = CANDLES.get(tok, [])
        df_1m = pd.DataFrame(raw_bars)
        exch_name = "BSE" if "bse" in seg else "NSE"

        render_broker_pro_chart(df_1m, sym, short_label, exch_name, curr_ltp, chg, pct, lot_size)

        with st.expander(f"⚙️ Order Ticket ({lot_size} Qty/Lot · Market / Limit / SL / Target)", expanded=False):
            o_type = st.radio("Order Type", ["MARKET", "LIMIT"], horizontal=True, key="ord_t")
            e1, e2, e3, e4 = st.columns(4)
            lots = e1.number_input("Lots", min_value=1, value=1, step=1, key="std_lots")
            lim_price = e2.number_input("Limit (₹)", min_value=0.05, value=float(curr_ltp), step=0.5, key="std_lim") if o_type == "LIMIT" else curr_ltp
            sl_pts = e3.number_input("SL Pts", min_value=0.0, value=0.0, step=1.0, key="std_sl")
            tg_pts = e4.number_input("Target Pts", min_value=0.0, value=0.0, step=1.0, key="std_tg")

        with st.container(key="broker_bottom_bar"):
            b1, b2, b3, b4 = st.columns([1.1, 1.1, 1.4, 1.4])
            with b1:
                if st.button("📜 Orders", key="bot_ord", use_container_width=True):
                    st.session_state["active_screen"] = "ORDERS"
                    st.rerun()
            with b2:
                if st.button("📡 Position", key="bot_pos", use_container_width=True):
                    st.session_state["active_screen"] = "POSITIONS"
                    st.rerun()
            with b3:
                if st.button("Buy", key="main_buy_btn", use_container_width=True):
                    base = curr_ltp if o_type == "MARKET" else lim_price
                    f_sl = max(0.05, base - sl_pts) if sl_pts > 0 else 0.0
                    f_tg = base + tg_pts if tg_pts > 0 else 0.0
                    ok, msg = (engine.execute_market_order(tok, sym, seg, lot_size, "BUY", lots, curr_ltp, f_sl, f_tg)
                               if o_type == "MARKET" else engine.place_limit_order(tok, sym, seg, lot_size, "BUY", lots, lim_price, f_sl, f_tg))
                    st.toast(msg)
                    st.rerun()
            with b4:
                if st.button("Sell", key="main_sell_btn", use_container_width=True):
                    base = curr_ltp if o_type == "MARKET" else lim_price
                    f_sl = base + sl_pts if sl_pts > 0 else 0.0
                    f_tg = max(0.05, base - tg_pts) if tg_pts > 0 else 0.0
                    ok, msg = (engine.execute_market_order(tok, sym, seg, lot_size, "SELL", lots, curr_ltp, f_sl, f_tg)
                               if o_type == "MARKET" else engine.place_limit_order(tok, sym, seg, lot_size, "SELL", lots, lim_price, f_sl, f_tg))
                    st.toast(msg)
                    st.rerun()

    # =========================================================================
    # SCREEN 2: HOME TERMINAL (CENTERED LOGO ONLY, NO BALANCE/P&L ON HOME)
    # =========================================================================
    else:
        render_centered_jineo_logo(max_width=195)

        with st.container(key="bottom_pills"):
            n1, n2, n3, n4 = st.columns([1.3, 1.2, 1.1, 0.9])
            with n1:
                if st.button("📊 Chain", key="top_chain", use_container_width=True):
                    st.session_state["active_screen"] = "CHAIN"
                    st.rerun()
            with n2:
                if st.button("📡 Positions", key="top_pos", use_container_width=True):
                    st.session_state["active_screen"] = "POSITIONS"
                    st.rerun()
            with n3:
                if st.button("📜 Orders", key="top_ord", use_container_width=True):
                    st.session_state["active_screen"] = "ORDERS"
                    st.rerun()
            with n4:
                if st.button("⚙️ A/C", key="top_acc", use_container_width=True):
                    st.session_state["active_screen"] = "ACCOUNT"
                    st.rerun()

        if st.session_state["active_screen"] == "CHAIN":
            top_c1, top_c2 = st.columns([1, 1])
            with top_c1:
                idx_choice = st.selectbox("Index", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"], label_visibility="collapsed")
                seg_code = "bse_fo" if idx_choice in ["SENSEX", "BANKEX"] else "nse_fo"

            df_master = load_master(client, seg_code)
            if not df_master.empty:
                sym_col = 'pSymbolName' if 'pSymbolName' in df_master.columns else df_master.columns[1]
                trd_col = 'pTrdSymbol' if 'pTrdSymbol' in df_master.columns else df_master.columns[2]
                tok_col = 'pSymbol' if 'pSymbol' in df_master.columns else df_master.columns[0]
                lot_col = 'lLotSize' if 'lLotSize' in df_master.columns else 'iLotSize'

                df_idx_raw = df_master[df_master[sym_col] == idx_choice]
                df_parsed = parse_options(df_idx_raw, idx_choice)

                if not df_parsed.empty:
                    exp_df = df_parsed[['ExpiryDate', 'ExpiryLabel']].drop_duplicates().sort_values('ExpiryDate')
                    with top_c2:
                        sel_expiry = st.selectbox("Expiry", exp_df['ExpiryLabel'].tolist(), label_visibility="collapsed")

                    df_exp = df_parsed[df_parsed['ExpiryLabel'] == sel_expiry]
                    all_strikes = sorted(df_exp['Strike'].unique().tolist())

                    spot_val, atm_strike = estimate_live_spot(df_exp, all_strikes, tok_col, seg_code, client)
                    atm_idx = all_strikes.index(atm_strike) if atm_strike in all_strikes else len(all_strikes) // 2

                    start_i = max(0, atm_idx - 10)
                    end_i = min(len(all_strikes), atm_idx + 11)
                    chain_strikes = all_strikes[start_i:end_i]

                    df_chain_sub = df_exp[df_exp['Strike'].isin(chain_strikes)]
                    chain_tokens = df_chain_sub[tok_col].astype(str).str.strip().unique().tolist()

                    @st.fragment(run_every="2s")
                    def render_clean_chain():
                        with st.container(key="option_chain"):
                            alerts = engine.check_triggers(lambda t, s: get_realtime_ltp(client, t, s))
                            for a in alerts:
                                st.toast(a)
                            fetch_batch(client, chain_tokens, seg_code)

                            ce_atm = df_exp[(df_exp['Strike'] == atm_strike) & (df_exp['Opt'] == 'CE')]
                            pe_atm = df_exp[(df_exp['Strike'] == atm_strike) & (df_exp['Opt'] == 'PE')]
                            live_spot = spot_val
                            if not ce_atm.empty and not pe_atm.empty:
                                cp = LIVE_PRICES.get(str(ce_atm.iloc[0][tok_col]).strip(), 0.0)
                                pp = LIVE_PRICES.get(str(pe_atm.iloc[0][tok_col]).strip(), 0.0)
                                if cp > 0 and pp > 0:
                                    live_spot = round(atm_strike + (cp - pp), 2)

                            st.markdown(
                                "<div style='display:flex; justify-content:space-between; padding:5px 8px; background:#f1f5f9; "
                                "border-radius:6px; font-size:11px; font-weight:800; color:#475569; margin-bottom:4px;'>"
                                "<div style='flex:3;'>CALL LTP</div><div style='flex:2; text-align:center;'>STRIKE</div><div style='flex:3; text-align:right;'>PUT LTP</div>"
                                "</div>",
                                unsafe_allow_html=True
                            )

                            banner_shown = False
                            exp_short = sel_expiry[:11].upper()
                            for s in chain_strikes:
                                if not banner_shown and s >= live_spot:
                                    st.markdown(
                                        f"<div style='text-align:center; background:#1e293b; color:#f8fafc; padding:4px 0; "
                                        f"border-radius:14px; font-size:12px; font-weight:800; margin:5px 0;'>Spot price {live_spot:,.2f}</div>",
                                        unsafe_allow_html=True
                                    )
                                    banner_shown = True

                                ce_r = df_exp[(df_exp['Strike'] == s) & (df_exp['Opt'] == 'CE')]
                                pe_r = df_exp[(df_exp['Strike'] == s) & (df_exp['Opt'] == 'PE')]
                                ce_tok = str(ce_r.iloc[0][tok_col]).strip() if not ce_r.empty else ""
                                pe_tok = str(pe_r.iloc[0][tok_col]).strip() if not pe_r.empty else ""
                                ce_sym = str(ce_r.iloc[0][trd_col]).strip() if not ce_r.empty else ""
                                pe_sym = str(pe_r.iloc[0][trd_col]).strip() if not pe_r.empty else ""
                                lot_sz = int(ce_r.iloc[0][lot_col]) if not ce_r.empty and lot_col in ce_r.iloc[0] else 25

                                ce_l = LIVE_PRICES.get(ce_tok, 0.0)
                                pe_l = LIVE_PRICES.get(pe_tok, 0.0)

                                try:
                                    c_col, s_col, p_col = st.columns([3.2, 1.6, 3.2], gap="small", vertical_alignment="center", stack_on_mobile=False)
                                except TypeError:
                                    c_col, s_col, p_col = st.columns([3.2, 1.6, 3.2], gap="small")

                                with c_col:
                                    if st.button(f"₹{ce_l:.2f}", key=f"c_{s}", use_container_width=True):
                                        st.session_state['trade_token'] = {
                                            "token": ce_tok, "symbol": ce_sym, "segment": seg_code,
                                            "lot": lot_sz, "ltp": ce_l,
                                            "label": f"{idx_choice} {s} CE",
                                            "expiry_sub": f"NFO {exp_short}"
                                        }
                                        st.session_state["active_screen"] = "CHART"
                                        try:
                                            st.rerun(scope="app")
                                        except TypeError:
                                            st.rerun()
                                with s_col:
                                    st.markdown(f"<div style='text-align:center; font-weight:800; font-size:12px; padding:6px 0;'>{s}</div>", unsafe_allow_html=True)
                                with p_col:
                                    if st.button(f"₹{pe_l:.2f}", key=f"p_{s}", use_container_width=True):
                                        st.session_state['trade_token'] = {
                                            "token": pe_tok, "symbol": pe_sym, "segment": seg_code,
                                            "lot": lot_sz, "ltp": pe_l,
                                            "label": f"{idx_choice} {s} PE",
                                            "expiry_sub": f"NFO {exp_short}"
                                        }
                                        st.session_state["active_screen"] = "CHART"
                                        try:
                                            st.rerun(scope="app")
                                        except TypeError:
                                            st.rerun()

                    render_clean_chain()

        elif st.session_state["active_screen"] == "POSITIONS":
            @st.fragment(run_every="1.5s")
            def render_pos():
                c = engine.conn.cursor()
                c.execute("SELECT instrument_token, trading_symbol, exchange_segment, lot_size, net_qty, avg_price, sl_price, target_price FROM positions WHERE net_qty != 0")
                rows = c.fetchall()
                if rows:
                    for seg_g in set(r[2] for r in rows):
                        fetch_batch(client, [r[0] for r in rows if r[2] == seg_g], seg_g)
                    p_list, tot = [], 0.0
                    for tok, sym, seg, l_sz, qty, avg, sl, tg in rows:
                        ltp = LIVE_PRICES.get(str(tok).strip(), avg)
                        pnl = (ltp - avg) * qty
                        tot += pnl
                        p_list.append({"Token": tok, "Symbol": sym, "Segment": seg, "LotSize": l_sz, "Qty": qty, "Avg": round(avg, 2), "LTP": round(ltp, 2), "P&L": round(pnl, 2)})
                    st.metric("Total MTM", f"₹{tot:,.2f}", delta=f"{tot:,.2f}")
                    if st.button("⚡ Exit All", type="primary", use_container_width=True):
                        for p in p_list:
                            engine.execute_market_order(p['Token'], p['Symbol'], p['Segment'], p['LotSize'], "SELL" if p['Qty']>0 else "BUY", abs(p['Qty'])//p['LotSize'], p['LTP'], reason="SQUARE-OFF")
                        st.rerun()
                    st.dataframe(pd.DataFrame(p_list)[["Symbol", "Qty", "Avg", "LTP", "P&L"]], use_container_width=True, hide_index=True)
                else:
                    st.info("No open positions.")
            render_pos()

        elif st.session_state["active_screen"] == "ORDERS":
            st.subheader("📜 Orders (IST)")
            df_ord = pd.read_sql_query("SELECT order_id, trading_symbol, side, qty, price, order_type, charges, time FROM orders ORDER BY order_id DESC LIMIT 20", engine.conn)
            st.dataframe(df_ord, use_container_width=True, hide_index=True)

        elif st.session_state["active_screen"] == "ACCOUNT":
            bal_acc, real_acc = engine.get_wallet()
            st.subheader("⚙️ Virtual Account & Session")
            st.metric("Available Virtual Balance", f"₹{bal_acc:,.2f}")
            st.metric("Realized P&L", f"₹{real_acc:,.2f}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔄 Reset Balance (₹10L)", use_container_width=True):
                    engine.reset_account()
                    st.rerun()
            with c2:
                if st.button("🔌 Logout Kotak API", type="primary", use_container_width=True):
                    STORE["client"] = None
                    st.rerun()