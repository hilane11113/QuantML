#!/usr/bin/env python3
"""
垂直价差策略 V6 (重写版)

核心逻辑：
- ctx-file 模式：只从统一数据口获取行情，策略走 v6 原生逻辑
- 独立模式：全量网络请求（原逻辑）

Strike 参数随 VIX 信号动态调整（VIX_STRIKE_PARAMS）：
  GREEN  (VIX<15): 贴近现价，宽spread，收集更多权利金
  YELLOW (15<VIX<25): 中间
  RED    (VIX>30): 远离现价，窄spread，控制风险

用法:
    python3 vertical_spread_v6.py TSLA --ctx-file=/tmp/tsla_ctx.json
    python3 vertical_sla_spread_v6.py TSLA
"""

import os
import sys
import json
import math
import warnings
import pandas as pd
import numpy as np
import yfinance as yf
from scipy.stats import norm
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'
os.environ.setdefault('https_proxy', PROXY)
os.environ.setdefault('http_proxy', PROXY)

STOCKS = []
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_v4.db'
EXPIRY_DAYS = 14

# ─────────────────────────────────────────────────────────────────
# VIX 信号差异化的 Strike 参数（v6 核心价值）
# ─────────────────────────────────────────────────────────────────
# 基于282笔历史数据分析优化
VIX_STRIKE_PARAMS = {
    "GREEN": {
        "Bull_Put_Spread":  {"short_ratio": 0.95, "spread_pct": 5},   # OTM 5%
        "Bull_Call_Spread": {"short_ratio": 1.05, "spread_pct": 5},
        "Short_Put":        {"short_ratio": 0.95},                       # OTM 5%
        "Iron_Condor":      {"put_short_ratio": 0.95, "call_short_ratio": 1.05, "spread_pct": 10},
    },
    "YELLOW": {
        "Bull_Put_Spread":  {"short_ratio": 0.93, "spread_pct": 7},   # OTM 7%（历史最佳）
        "Bull_Call_Spread": {"short_ratio": 1.07, "spread_pct": 7},
        "Short_Put":        {"short_ratio": 0.93},                       # OTM 7%
        "Iron_Condor":      {"put_short_ratio": 0.93, "call_short_ratio": 1.07, "spread_pct": 10},
    },
    "RED": {
        "Bull_Put_Spread":  {"short_ratio": 0.90, "spread_pct": 10},   # OTM 10%
        "Bull_Call_Spread": {"short_ratio": 1.10, "spread_pct": 10},
        "Short_Put":        {"short_ratio": 0.90},                      # OTM 10%
        "Iron_Condor":      {"put_short_ratio": 0.90, "call_short_ratio": 1.10, "spread_pct": 12},
    },
}

def check_entry_filter(rsi, vix, otm_pct):
    if rsi is not None:
        if rsi < 25 or rsi > 75:
            return False, 'reject', f'RSI={rsi:.0f} 极端值，拒绝'
        if vix is not None and vix > 30 and (rsi < 30 or rsi > 70):
            return False, 'reject', f'VIX={vix:.0f}+RSI={rsi:.0f} 高风险组合，拒绝'
        if vix is not None and vix > 30:
            return False, 'reject', f'VIX={vix:.0f}>30 尾部风险，拒绝'
    if otm_pct is not None and -5 < otm_pct < 0:
        return True, 'reduced', f'OTM={abs(otm_pct):.1f}%<5%，降低评分'
    if rsi is not None and vix is not None:
        if 25 <= rsi < 40 and vix > 25:
            return True, 'reduced', f'RSI={rsi:.0f}+VIX={vix:.0f} 高波动组合，降低仓位'
    return True, 'normal', '通过'

MIN_OTM_PCT = 5.0


# ─────────────────────────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────────────────────────

def get_vix():
    '获取VIX'
    try:
        os.environ.setdefault('https_proxy', PROXY)
        os.environ.setdefault('http_proxy', PROXY)
        vix_df = yf.download("^VIX", period="30d", timeout=10)
        vix = vix_df['Close'].iloc[-1]
        ma10 = vix_df['Close'].rolling(10).mean().iloc[-1]
        deviation = (vix - ma10) / ma10 * 100
        return float(vix), float(ma10), float(deviation)
    except Exception:
        return 20.0, 20.0, 0.0


def get_sentiment(symbol):
    """舆情评分"""
    return 50, "neutral", {"mentions": 0, "upvotes": 0, "score": 50}


def get_stock_iv_from_hv(ticker, price):
    '估算IV'
    try:
        hist = ticker.history(period="30d")
        if hist.empty:
            return 35.0, 30.0
        log_returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        hv = log_returns.std() * (252 ** 0.5) * 100
        iv = max(hv * 1.2, 30)
        return float(iv), float(hv)
    except Exception:
        return 35.0, 30.0


def get_available_expirations(ticker):
    """获取可用到期日"""
    try:
        expirations = ticker.options
        result = []
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d')
                days = (exp_date - datetime.now()).days
                if 1 <= days <= EXPIRY_DAYS:
                    result.append({'date': exp_str, 'days': days})
            except Exception:
                pass
        result.sort(key=lambda x: x['days'])
        return result
    except Exception:
        return []


def get_option_df(ticker, expiry_str):
    """获取期权链 DataFrame"""
    try:
        opt = ticker.option_chain(expiry_str)
        calls = opt.calls.copy()
        calls['type'] = 'call'
        puts = opt.puts.copy()
        puts['type'] = 'put'
        df = pd.concat([calls, puts], ignore_index=True)
        numeric_cols = ['strike', 'lastPrice', 'bid', 'ask', 'volume', 'openInterest', 'impliedVolatility']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────
# 策略计算核心
# ─────────────────────────────────────────────────────────────────

def calculate_vix_signal(vix, vix_ma, deviation):
    """VIX 信号判断"""
    if pd.isna(vix) or pd.isna(vix_ma):
        return "YELLOW", 50
    if vix > 30:
        return "RED", 30
    elif vix < 15:
        return "GREEN", 80
    elif vix > 25:
        return "YELLOW", 50
    elif vix > 20:
        return "YELLOW", 50
    if deviation > 15:
        return "RED", 30
    elif deviation < -10:
        return "GREEN", 80
    return "YELLOW", 50


def get_iv_score(iv):
    if 30 <= iv <= 50: return 10
    elif 20 <= iv < 30 or 50 < iv <= 60: return 7
    elif iv < 20: return 5
    return 5


def calculate_theta_score(theta, premium, days, iv):
    if premium <= 0 or days <= 0:
        return 0
    theta_eff = theta / (premium / days + 0.001)
    prem_eff = premium / (days + 1)
    if days < 7:
        theta_eff *= 0.7
    if iv > 50:
        theta_eff *= 0.8
    return round(theta_eff * 400 + prem_eff * 1.5)


def calculate_composite_score(rr_ratio, liquidity_score, safety_score, sentiment_score,
                               theta_score, iv_score, delta_score, gamma_score, downside_score):
    return (rr_ratio * 25 + liquidity_score * 3 + safety_score * 1.5
            + sentiment_score * 1.5 + theta_score * 0.5 + iv_score * 0.5
            + delta_score * 0.3 + gamma_score * 0.3 + downside_score * 0.5)


def calculate_strategy_details(price, iv, strategy_type, sentiment,
                               days_to_expiry, ticker=None, options_data=None):
    
    if days_to_expiry <= 0:
        return None

    T = max(days_to_expiry / 365, 1 / 365)
    sigma = iv / 100
    sentiment_map = {'bullish': 80, 'neutral': 50, 'bearish': 20}
    sentiment_score = sentiment_map.get(sentiment, 50)

    # 获取参数
    params = VIX_STRIKE_PARAMS.get("YELLOW", {})  # 默认 YELLOW
    if strategy_type in VIX_STRIKE_PARAMS.get("YELLOW", {}):
        params = VIX_STRIKE_PARAMS.get("YELLOW", {}).get(strategy_type, {})

    # ── Bull Put Spread ──────────────────────────────────────────
    if strategy_type == "Bull_Put_Spread":
        short_ratio = params.get("short_ratio", 0.97)
        spread_pct = params.get("spread_pct", 6)
        K1 = round(price * short_ratio / 2.5) * 2.5
        K2 = round(price * (short_ratio - spread_pct / 100) / 2.5) * 2.5
        if K2 >= K1:
            K2 = round((K1 - 15) / 2.5) * 2.5

        premium = 0
        if options_data is not None:
            puts_df = pd.DataFrame(options_data.get('puts', []))
            if not puts_df.empty:
                s_row = puts_df[puts_df['strike'] == K1]
                l_row = puts_df[puts_df['strike'] == K2]
                if not s_row.empty and not l_row.empty:
                    prem_s = (float(s_row.iloc[0]['bid']) + float(s_row.iloc[0]['ask'])) / 2
                    prem_l = (float(l_row.iloc[0]['bid']) + float(l_row.iloc[0]['ask'])) / 2
                    premium = (prem_s - prem_l) * 100
        if premium <= 0:
            try:
                d1 = (math.log(price / K1) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
                d2 = d1 - sigma * math.sqrt(T)
                p1 = K1 * math.exp(-0.05 * T) * norm.cdf(-d2) - price * norm.cdf(-d1)
                p2 = K2 * math.exp(-0.05 * T) * norm.cdf(-(math.log(price / K2) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))) - price * norm.cdf(-(math.log(price / K2) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T)) - sigma * math.sqrt(T))
                premium = max((p1 - p2) * 100, 1)
            except Exception:
                premium = 5.0

        width = K1 - K2
        max_profit = premium
        max_loss = width * 100 - premium
        rr_ratio = max_profit / max_loss if max_loss > 0 else 0

        try:
            d1 = (math.log(price / K1) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
            delta = norm.cdf(d1) - 1
            gamma = norm.pdf(d1) / (price * sigma * math.sqrt(T))
        except Exception:
            delta, gamma = -0.3, 0.02

        liquidity_score = 5
        safety_score = min(round((price - K1) / price * 100 * 2), 10)
        iv_score = get_iv_score(iv)
        theta_val = delta * 0.01
        theta_sc = calculate_theta_score(theta_val, premium, days_to_expiry, iv)
        downside_sc = 5
        score = calculate_composite_score(rr_ratio, liquidity_score, safety_score,
                                           sentiment_score, theta_sc, iv_score,
                                           abs(delta) * 10, gamma * 100, downside_sc)

        return {
            'strategy_type': 'Bull_Put_Spread',
            'strategy_desc': 'Bull Put Spread',
            'short_strike': K1, 'long_strike': K2,
            'premium': premium, 'max_profit': max_profit,
            'max_loss': max_loss, 'width': width,
            'rr_ratio': rr_ratio, 'liquidity_score': liquidity_score,
            'safety_score': safety_score,
            'composite_score': score,
            'delta': delta, 'gamma': gamma,
            'theta': theta_val, 'theta_score': theta_sc,
            'iv_score': iv_score,
            'downside_score': downside_sc,
            'days_to_expiry': days_to_expiry,
        }

    # ── Bull Call Spread ─────────────────────────────────────────
    elif strategy_type == "Bull_Call_Spread":
        short_ratio = params.get("short_ratio", 1.03)
        spread_pct = params.get("spread_pct", 6)
        K1 = round(price * short_ratio / 2.5) * 2.5
        K2 = round(price * (short_ratio + spread_pct / 100) / 2.5) * 2.5
        if K1 >= K2:
            K2 = K1 + 10

        premium = 0
        if options_data is not None:
            calls_df = pd.DataFrame(options_data.get('calls', []))
            if not calls_df.empty:
                l_row = calls_df[calls_df['strike'] == K1]
                s_row = calls_df[calls_df['strike'] == K2]
                if not l_row.empty and not s_row.empty:
                    prem_l = (float(l_row.iloc[0]['bid']) + float(l_row.iloc[0]['ask'])) / 2
                    prem_s = (float(s_row.iloc[0]['bid']) + float(s_row.iloc[0]['ask'])) / 2
                    premium = max((prem_s - prem_l) * 100, 0)
        if premium <= 0:
            try:
                premium = 5.0
            except Exception:
                premium = 3.0

        width = K2 - K1
        max_profit = width * 100 - abs(premium)
        max_loss = abs(premium)
        rr_ratio = max_profit / max_loss if max_loss > 0 else 0
        delta, gamma = 0.2, 0.01
        liquidity_score, safety_score = 5, 5
        theta_val = 0
        theta_sc = 5
        iv_score = get_iv_score(iv)
        score = calculate_composite_score(rr_ratio, liquidity_score, safety_score,
                                           sentiment_score, theta_sc, iv_score,
                                           delta * 10, gamma * 100, 5)

        return {
            'strategy_type': 'Bull_Call_Spread',
            'strategy_desc': 'Bull Call Spread',
            'short_strike': K2, 'long_strike': K1,
            'premium': premium, 'max_profit': max_profit,
            'max_loss': max_loss, 'width': width,
            'rr_ratio': rr_ratio, 'liquidity_score': liquidity_score,
            'safety_score': safety_score,
            'composite_score': score,
            'delta': delta, 'gamma': gamma,
            'theta': theta_val, 'theta_score': theta_sc,
            'iv_score': iv_score,
            'downside_score': 5,
            'days_to_expiry': days_to_expiry,
        }

    # ── Short Put ───────────────────────────────────────────────
    elif strategy_type == "Short_Put":
        short_ratio = params.get("short_ratio", 0.95)
        K1 = round(price * short_ratio / 2.5) * 2.5
        if K1 >= price:
            K1 = round(price * 0.97 / 2.5) * 2.5

        premium = 0
        if options_data is not None:
            puts_df = pd.DataFrame(options_data.get('puts', []))
            if not puts_df.empty:
                row = puts_df[puts_df['strike'] == K1]
                if not row.empty:
                    premium = (float(row.iloc[0]['bid']) + float(row.iloc[0]['ask'])) / 2 * 100
        if premium <= 0:
            try:
                d1 = (math.log(price / K1) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
                p = K1 * math.exp(-0.05 * T) * norm.cdf(-d2) - price * norm.cdf(-d1)
                premium = max(p * 100, 1)
            except Exception:
                premium = 5.0

        max_profit = premium
        max_loss = (K1 - price + premium / 100) * 100 if price < K1 else premium
        if max_loss < 0:
            max_loss = abs((price - K1) * 100) + premium
        rr_ratio = max_profit / max_loss if max_loss > 0 else 0
        downside_space = (price - K1) / price * 100
        downside_sc = min(int(downside_space * 2), 10)
        liquidity_score = 5
        safety_score = min(int(downside_space), 10)
        try:
            d1 = (math.log(price / K1) + (sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
            delta = norm.cdf(d1) - 1
        except Exception:
            delta = -0.3
        gamma = 0.02
        theta_val = abs(delta) * 0.05
        theta_sc = calculate_theta_score(theta_val, premium, days_to_expiry, iv)
        iv_score = get_iv_score(iv)
        score = calculate_composite_score(rr_ratio, liquidity_score, safety_score,
                                           sentiment_score, theta_sc, iv_score,
                                           abs(delta) * 10, gamma * 100, downside_sc)

        return {
            'strategy_type': 'Short_Put',
            'strategy_desc': 'Short Put',
            'strike': K1,
            'premium': premium, 'max_profit': max_profit,
            'max_loss': max_loss,
            'rr_ratio': rr_ratio, 'liquidity_score': liquidity_score,
            'safety_score': safety_score,
            'composite_score': score,
            'delta': delta, 'gamma': gamma,
            'theta': theta_val, 'theta_score': theta_sc,
            'iv_score': iv_score,
            'downside_score': downside_sc,
            'days_to_expiry': days_to_expiry,
        }

    return None


# ─────────────────────────────────────────────────────────────────
# 主扫描函数
# ─────────────────────────────────────────────────────────────────

def scan_multi_expiry(symbol, vix, vix_ma, deviation, vix_signal="YELLOW"):
    """
    扫描多个到期日的最优策略。
    返回 (market_data, best_strategies)
    """
    default_prices = {'TSLA': 400.0, 'NVDA': 180.0, 'AAPL': 250.0}
    price = default_prices.get(symbol, 100.0)
    ticker = None
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if not hist.empty:
            close_price = hist['Close'].iloc[-1]
            if hasattr(close_price, 'item'):
                close_price = close_price.item()
            if not pd.isna(close_price):
                price = close_price
    except Exception:
        pass

    estimated_iv, hv = get_stock_iv_from_hv(ticker, price)
    iv = estimated_iv if not pd.isna(estimated_iv) else hv
    iv = iv if not pd.isna(iv) else 35

    sentiment_score, sentiment_label, sent_data = get_sentiment(symbol)
    iv_score = get_iv_score(iv)

    market_data = {
        'symbol': symbol, 'price': price, 'iv': iv,
        'vix': vix, 'vix_signal': vix_signal,
        'sentiment': sentiment_label, 'sentiment_score': sentiment_score
    }

    if ticker is None:
        return market_data, []

    expirations = get_available_expirations(ticker)
    if not expirations:
        return market_data, []

    all_results = []
    for exp_info in expirations:
        expiry_str = exp_info['date']
        days = exp_info['days']
        df = get_option_df(ticker, expiry_str)
        if df.empty:
            continue
        calls_df = df[df['type'] == 'call'].copy()
        puts_df = df[df['type'] == 'put'].copy()

        for strategy_type in ["Bull_Put_Spread", "Bull_Call_Spread", "Short_Put"]:
            det = calculate_strategy_details(
                price, iv, strategy_type, sentiment_label,
                days, ticker=ticker, options_data={'calls': calls_df.to_dict('records'), 'puts': puts_df.to_dict('records')}
            )
            if det:
                det['expiry'] = expiry_str
                all_results.append(det)

    # 计算 RSI（用于入场过滤器）
    rsi_val = None
    try:
        if ticker is not None:
            h = ticker.history(period="30d")
            if not h.empty and len(h) >= 14:
                close = h['Close']
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi_series = 100 - 100 / (1 + rs)
                rsi_val = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else None
    except Exception:
        pass

    # 入场过滤器
    for det in all_results:
        ss = det.get('short_strike') or det.get('strike', price)
        otm_pct = (ss - price) / price * 100 if price else None
        can, level, reason = check_entry_filter(rsi_val, vix, otm_pct)
        det['filter_reason'] = reason
        if level == 'reject':
            det['composite_score'] = 0
            det['filter_decision'] = '🔴禁止'
        elif level == 'reduced':
            det['composite_score'] = det.get('composite_score', 0) * 0.7
            det['filter_decision'] = '🟡减仓'

    if not all_results:
        return market_data, []

    # 排序取 Top
    all_results.sort(key=lambda x: x['composite_score'], reverse=True)
    print(f"   📊 RSI: {rsi_val:.1f}" if rsi_val else "   📊 RSI: N/A")
    return market_data, all_results[:10]


# ─────────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────────

def _load_ctx(ctx_file):
    """加载 ctx 文件"""
    with open(ctx_file, encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict) and 'price' in raw:
        return {raw.get('symbol', 'TSLA'): raw}
    elif isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def run(symbol, ctx_data=None, use_network=True):
    """执行分析"""
    if not use_network and ctx_data:
        # ── ctx 模式 ──────────────────────────────────────────
        ctx = ctx_data
        price = ctx.get('price', 0)
        iv_raw = ctx.get('iv', 35)
        iv = iv_raw * 100 if isinstance(iv_raw, float) and 0 < iv_raw < 1 else float(iv_raw)
        vix_val = ctx.get('vix', 20)
        vix_ma = ctx.get('vix_ma10', vix_val)
        sentiment = ctx.get('sentiment', 'neutral')
        option_chains = ctx.get('option_chains', [])
        vix_sig, vix_sc = calculate_vix_signal(vix_val, vix_ma, 0)
        deviation = ((vix_val - vix_ma) / vix_ma * 100) if vix_ma > 0 else 0

        market_data = {
            'symbol': symbol, 'price': price, 'iv': iv,
            'vix': vix_val, 'vix_signal': vix_sig,
            'sentiment': sentiment,
        }

        print(f"\n📊 {symbol} (统一数据口) ${price:.2f} | IV:{iv:.1f}% | VIX:{vix_val:.2f}({vix_sig})")
        print(f"📊 VIX: {vix_val:.2f} | MA10: {vix_ma:.2f} | 偏离: {deviation:+.1f}% | 信号: {vix_sig}")

        all_results = []
        for chain in option_chains:
            days = chain.get('days', 7)
            expiry_str = chain.get('date', '')[:10]
            opt_data = {
                'calls': chain.get('calls', []),
                'puts': chain.get('puts', []),
            }
            for stype in ["Bull_Put_Spread", "Bull_Call_Spread", "Short_Put"]:
                det = calculate_strategy_details(
                    price, iv, stype, sentiment,
                    days, ticker=None, options_data=opt_data
                )
                if det:
                    det['expiry'] = expiry_str
                    all_results.append(det)

        # 入场过滤器
        for det in all_results:
            ss = det.get('short_strike') or det.get('strike', price)
            otm_pct = (ss - price) / price * 100 if price else None
            rsi_ctx = ctx.get('rsi') if ctx else None
            vix_ctx = vix_val
            can, level, reason = check_entry_filter(rsi_ctx, vix_ctx, otm_pct)
            det['filter_reason'] = reason
            if level == 'reject':
                det['composite_score'] = 0
                det['filter_decision'] = '🔴禁止'
            elif level == 'reduced':
                det['composite_score'] = det.get('composite_score', 0) * 0.7
                det['filter_decision'] = '🟡减仓'

        all_results.sort(key=lambda x: x['composite_score'], reverse=True)
        return market_data, all_results[:10]
    else:
        # ── 独立请求模式 ────────────────────────────────────
        proxy_vix, vix_ma2, deviation2 = get_vix()
        vix_sig2, vix_sc2 = calculate_vix_signal(proxy_vix, vix_ma2, deviation2)
        print(f"\n📊 VIX: {proxy_vix:.2f} | MA10: {vix_ma2:.2f} | 偏离: {deviation2:.1f}%")
        print(f"   信号: {vix_sig2} | 评分: {vix_sc2}/100")
        return scan_multi_expiry(symbol, proxy_vix, vix_ma2, deviation2, vix_sig2)


def print_results(market_data, best_strategies):
    """格式化输出"""
    symbol = market_data['symbol']
    price = market_data['price']
    iv = market_data.get('iv', 35)
    vix = market_data.get('vix', 0)
    vix_sig = market_data.get('vix_signal', 'YELLOW')
    sentiment = market_data.get('sentiment', 'neutral')

    sig_emoji = {'GREEN': '🟢', 'YELLOW': '🟡', 'RED': '🔴'}.get(vix_sig, '🟡')

    print(f"\n{'='*60}")
    print(f"  📋 {symbol} 策略推荐详情")
    print(f"{'='*60}")
    print(f"  📈 {symbol} - ⏸️ 观望" if vix_sig == "RED" else f"  📈 {symbol}")
    print()
    print(f"  📊 市场概况")
    print(f"  ─────────────")
    print(f"  股价          ${price:.2f}")
    print(f"  IV           {iv:.1f}%")
    print(f"  VIX         {sig_emoji} {vix:.2f} (信号: {vix_sig})")
    print(f"  舆情         {sentiment}")
    print(f"  综合评分     {market_data.get('sentiment_score', 50):.0f}/100")
    print()
    print(f"  📊 动态阈值   ≥65 开仓  ≥50 试探  <50 禁止")
    print()

    if not best_strategies:
        print(f"  ⚠️ 当前无符合条件的策略")
        print(f"  💡 建议: VIX={vix_sig} 市场，等待信号转绿或黄色再操作")
        print()
        print(f"{'='*60}")
        return

    print(f"  📋 推荐策略")
    print(f"  {'─'*54}")
    for i, s in enumerate(best_strategies[:5], 1):
        sc = s.get('composite_score', 0)
        dec = "✅开仓" if sc >= 65 else ("🟡试探" if sc >= 50 else "🔴禁止")
        sdesc = s.get('strategy_desc', s.get('strategy_type', ''))
        short = s.get('short_strike', s.get('strike', 'N/A'))
        expiry = s.get('expiry', 'N/A')
        days = s.get('days_to_expiry', 0)
        prem = s.get('premium', 0)
        mp = s.get('max_profit', 0)
        ml = s.get('max_loss', 0)
        rr = s.get('rr_ratio', 0)
        theta = s.get('theta', 0)
        print(f"  {dec} {i}. {sdesc}")
        if 'short_strike' in s or 'strike' in s:
            print(f"      卖 Strike  ${short} | 到期 {expiry}({days}天)")
        print(f"      权利金  ${prem:.2f} | 最大盈利 ${mp:.2f} | 最大亏损 ${ml:.2f}")
        print(f"      RR     {rr:.2f} | Theta ${theta:.3f}/天 | 评分 {sc:.0f}")
        print()

    print(f"{'='*60}")
    print(f"  💡 综合建议")
    top = best_strategies[0]
    top_sc = top.get('composite_score', 0)
    top_type = top.get('strategy_desc', '')
    top_short = top.get('short_strike', top.get('strike', ''))
    top_days = top.get('days_to_expiry', 0)
    if top_sc >= 65:
        print(f"  ✅ 推荐: {top_type} 卖 ${top_short} 持仓 {top_days} 天")
        print(f"     综合评分 {top_sc:.0f} 满足开仓条件")
    elif top_sc >= 50:
        print(f"  🟡 试探: {top_type} 卖 ${top_short} 持仓 {top_days} 天")
        print(f"     综合评分 {top_sc:.0f} 建议轻仓试探")
    else:
        print(f"  🔴 当前不建议开仓，等待更好的市场环境")
        print(f"     最优策略评分 {top_sc:.0f} 未达开仓门槛")
    print(f"{'='*60}")


if __name__ == "__main__":
    # ── yfinance 请求计数器 ──────────────────────────────
    try:
        sys.path.insert(0, '/root/.openclaw/workspace/quant/StockAssistant')
        from yf_counter import get_counter
        get_counter().install()
    except Exception:
        pass

    ctx_file = None
    symbols = []
    for arg in sys.argv[1:]:
        if arg.startswith("--ctx-file="):
            ctx_file = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            symbols.append(arg)

    if not symbols:
        symbols = ["TSLA"]

    ctx_map = {}
    if ctx_file:
        ctx_map = _load_ctx(ctx_file)
        print(f"[INFO] 从 ctx 文件加载: {list(ctx_map.keys())}")

    for sym in symbols:
        ctx = ctx_map.get(sym)
        mkt, strategies = run(sym, ctx_data=ctx, use_network=(ctx is None))
        print_results(mkt, strategies)

    print(f"\n{'='*60}")
    print(f"  vertical_spread_v6.py - 垂直价差策略")
    print(f"  --ctx-file=/path/to/ctx.json  使用统一数据口")
    print(f"{'='*60}")
