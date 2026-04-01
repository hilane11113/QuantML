#!/usr/bin/env python3
"""
垂直价差推荐策略 (增强版 V3)
完整策略层框架：
1. 风险调整参数表 (随VIX信号动态变化)
2. 综合评分 = 盈亏比(40%) + 流动性(30%) + 安全距离(30%) + 参数匹配(10%)
3. 价格区间预测 (Black-Scholes)
4. 希腊字母风控
"""

import sqlite3
import pandas as pd
from datetime import datetime
import yfinance as yf
import numpy as np
import os
import math
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

STOCKS = ['TSLA', 'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'AMD']
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_v3.db'

# ==================== 风险调整参数表 ====================
SIGNAL_PARAMS = {
    "GREEN": {
        "short_ratio": 0.96,      # 卖出行权价比
        "safety_margin": 0.04,    # 安全距离
        "spread_width": 25       # 价差宽度
    },
    "YELLOW": {
        "short_ratio": 0.92,
        "safety_margin": 0.08,
        "spread_width": 20
    },
    "RED": {
        "short_ratio": 0.88,
        "safety_margin": 0.12,
        "spread_width": 15
    }
}

def get_vix():
    """获取VIX和MA10"""
    try:
        vix = yf.download("^VIX", period="30d", timeout=10)["Close"]
        if len(vix) < 10:
            return np.nan, np.nan, np.nan, np.nan
        
        current = vix.iloc[-1].item()
        ma10 = vix.tail(10).mean().item()
        deviation = (current - ma10) / ma10 * 100
        
        return current, ma10, deviation, vix
    except:
        return np.nan, np.nan, np.nan, None

def get_stock_iv_from_hv(ticker, price):
    """用HV估算IV"""
    try:
        hist = ticker.history(period="30d")
        if hist.empty:
            return np.nan, np.nan
        
        returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        hv_20 = returns.tail(20).std() * np.sqrt(252) * 100
        hv_20 = hv_20.item() if hasattr(hv_20, 'item') else hv_20
        
        estimated_iv = hv_20 * 1.15
        return estimated_iv, hv_20
    except:
        return np.nan, np.nan

def get_sentiment(symbol):
    """获取舆情"""
    try:
        import finnhub
        client = finnhub.Client(api_key='d2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0')
        news = client.company_news(symbol, _from='2026-02-25', to='2026-03-03')
        
        if not news:
            return "neutral", 0
        
        bull_kw = ['buy', 'upgrade', 'bull', 'growth', 'target', '上涨', '看好', '突破']
        bear_kw = ['sell', 'downgrade', 'bear', 'risk', 'warning', '下跌', '警告', '风险']
        
        bull = sum(1 for n in news[:20] if any(k in n.get('headline', '').lower() for k in bull_kw))
        bear = sum(1 for n in news[:20] if any(k in n.get('headline', '').lower() for k in bear_kw))
        
        total = bull + bear
        if total == 0:
            return "neutral", 0
        
        ratio = bull / total
        if ratio > 0.6:
            return "bullish", ratio
        elif ratio < 0.4:
            return "bearish", ratio
        else:
            return "neutral", ratio
    except:
        return "neutral", 0

def calculate_vix_signal(vix, vix_ma, deviation):
    """VIX信号判断"""
    if pd.isna(vix) or pd.isna(vix_ma):
        return "UNKNOWN", 0
    
    if deviation > 5:
        signal = "GREEN"
    elif deviation < -5:
        signal = "RED"
    else:
        signal = "YELLOW"
    
    score = 50
    score += max(min(deviation * 2.5, 25), -25)
    
    if vix < 15:
        score += 20
    elif vix > 30:
        score -= 20
    elif vix > 20:
        score -= 10
    
    score = max(0, min(100, score))
    return signal, score

def calculate_composite_score(rr_ratio, liquidity_score, safety_distance, params_match, sentiment_score):
    """
    综合评分 = 盈亏比(30%) + 流动性(20%) + 安全距离(20%) + 参数匹配(10%) + 舆情(20%)
    """
    # 盈亏比因子 (0-30分)
    rr_clamped = min(rr_ratio, 2.0)
    rr_score = (rr_clamped / 2.0) * 30
    
    # 流动性因子 (0-20分)
    liq_score = min(liquidity_score * 2, 20)
    
    # 安全距离因子 (0-20分)
    safety_score = min(safety_distance * 2, 20)
    
    # 参数匹配奖励 (0-10分)
    param_score = params_match * 10
    
    # 舆情因子 (0-20分)
    # 积极=20分, 中性=10分, 负面=0分
    sentiment_scores = {"bullish": 20, "neutral": 10, "bearish": 0}
    sent_score = sentiment_scores.get(sentiment_score, 10)
    
    total = rr_score + liq_score + safety_score + param_score + sent_score
    return min(100, max(0, total))

def calculate_price_range_bs(S, T, sigma, confidence=1.96):
    """
    Black-Scholes价格区间预测
    S: 股价, T: 到期时间(年), sigma: 波动率, confidence: 置信度(1.96=95%)
    """
    try:
        r = 0.02  # 无风险利率
        sqrt_T = np.sqrt(T)
        
        lower = S * np.exp(-r*T) * norm.cdf(-confidence * sqrt_T + sigma*np.sqrt(T))
        upper = S * np.exp(-r*T) * norm.cdf(confidence * sqrt_T + sigma*np.sqrt(T))
        
        return lower, upper
    except:
        return S * 0.8, S * 1.2

def calculate_spread_greeks(price, short_strike, long_strike, days, iv):
    """希腊字母计算"""
    try:
        r = 0.02
        T = days / 365.0
        iv_decimal = iv / 100
        
        d1_short = (np.log(price / short_strike) + (r + iv_decimal**2/2) * T) / (iv_decimal * np.sqrt(T))
        d1_long = (np.log(price / long_strike) + (r + iv_decimal**2/2) * T) / (iv_decimal * np.sqrt(T))
        
        # Delta
        delta_short = norm.cdf(d1_short) - 1
        delta_long = norm.cdf(d1_long) - 1
        spread_delta = delta_short - delta_long
        
        # Theta
        theta_short = -(price * iv_decimal * norm.pdf(d1_short)) / (2 * np.sqrt(365))
        theta_long = -(price * iv_decimal * norm.pdf(d1_long)) / (2 * np.sqrt(365))
        spread_theta = theta_short - theta_long
        
        # Gamma
        gamma_short = norm.pdf(d1_short) / (price * iv_decimal * np.sqrt(T))
        gamma_long = norm.pdf(d1_long) / (price * iv_decimal * np.sqrt(T))
        spread_gamma = gamma_short - gamma_long
        
        return {
            'delta': round(spread_delta, 4),
            'theta': round(spread_theta, 2),
            'gamma': round(spread_gamma, 6)
        }
    except:
        return {'delta': 0, 'theta': 0, 'gamma': 0}

def get_stock_data(symbol, vix, vix_ma, deviation, vix_signal):
    """获取数据+完整策略评分"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist.empty:
            return None
        
        price = hist['Close'].iloc[-1]
        price = price.item() if hasattr(price, 'item') else price
        
        # IV估算
        estimated_iv, hv = get_stock_iv_from_hv(ticker, price)
        iv = estimated_iv if not pd.isna(estimated_iv) else hv
        iv = iv if not pd.isna(iv) else 35
        
        # 舆情
        sentiment, sent_ratio = get_sentiment(symbol)
        
        # 获取参数
        params = SIGNAL_PARAMS.get(vix_signal, SIGNAL_PARAMS["YELLOW"])
        
        # 计算目标行权价
        target_short = price * params["short_ratio"]
        
        # 获取期权链计算盈亏比等
        spread_data = calculate_spread_details(ticker, price, target_short, params["spread_width"], iv)
        
        if spread_data is None:
            # 无法获取期权数据，使用默认值
            spread_data = {
                'rr_ratio': 1.0,
                'liquidity': 10,
                'safety_distance': 10,
                'params_match': 0.5,
                'short_strike': target_short,
                'long_strike': target_short - params["spread_width"]
            }
        
        # 综合评分
        composite_score = calculate_composite_score(
            spread_data['rr_ratio'],
            spread_data['liquidity'],
            spread_data['safety_distance'],
            spread_data['params_match'],
            sentiment  # 加入舆情因子
        )
        
        # 决策 - 基于信号和评分
        if vix_signal == "GREEN" and composite_score >= 30:
            decision = "✅开仓"
        elif vix_signal == "GREEN" and composite_score >= 20:
            decision = "🟡试探"
        elif composite_score >= 40:
            decision = "🟡试探"
        else:
            decision = "🔴禁止"
        
        # 价格区间预测 (7天/14天/30天)
        price_ranges = {}
        for days in [7, 14, 30]:
            T = days / 365.0
            lower, upper = calculate_price_range_bs(price, T, iv/100)
            price_ranges[days] = (round(lower, 2), round(upper, 2))
        
        # 希腊字母
        greeks = calculate_spread_greeks(price, spread_data['short_strike'], spread_data['long_strike'], 30, iv)
        
        # 仓位
        position = int(100 * (composite_score / 100) * (1 if vix_signal == "GREEN" else 0.6))
        position = max(0, min(100, position))
        
        return {
            'symbol': symbol,
            'price': price,
            'iv': iv,
            'hv': hv,
            'vix': vix,
            'vix_signal': vix_signal,
            'decision': decision,
            'sentiment': sentiment,
            'composite_score': composite_score,
            'rr_ratio': spread_data['rr_ratio'],
            'liquidity': spread_data['liquidity'],
            'safety_distance': spread_data['safety_distance'],
            'params_match': spread_data['params_match'],
            'short_strike': spread_data['short_strike'],
            'long_strike': spread_data['long_strike'],
            'spread_width': params["spread_width"],
            'position_size': position,
            'price_range_7d': price_ranges[7],
            'price_range_14d': price_ranges[14],
            'price_range_30d': price_ranges[30],
            'greeks': greeks
        }
    except Exception as e:
        print(f"   ⚠️ {symbol}: {e}")
        return None

def calculate_spread_details(ticker, price, target_short, spread_width, iv):
    """计算价差详情"""
    try:
        if not ticker.options:
            return None
        
        opt = ticker.option_chain(ticker.options[0])
        puts = opt.puts
        
        # 找最近的行权价
        puts['dist'] = abs(puts['strike'] - target_short)
        puts = puts.sort_values('dist').head(10)
        
        if puts.empty:
            return None
        
        best = puts.iloc[0]
        short_strike = best['strike']
        
        # 找long strike
        long_candidates = puts[puts['strike'] < short_strike]
        if long_candidates.empty:
            long_strike = short_strike - spread_width
        else:
            long_strike = long_candidates.iloc[0]['strike']
        
        actual_width = short_strike - long_strike
        
        # 盈亏比 (简化) - 用lastPrice
        last = best['lastPrice'] if pd.notna(best['lastPrice']) else 0
        if last == 0:
            last = iv / 10  # 估算
        
        max_profit = last * 1  # 每手
        max_loss = actual_width * 100  # 价差
        
        rr_ratio = max_profit / max_loss if max_loss > 0 else 1.0
        
        # 流动性
        oi = best.get('openInterest', 0) if pd.notna(best.get('openInterest', 0)) else 0
        vol = best.get('volume', 0) if pd.notna(best.get('volume', 0)) else 0
        liquidity = min(30, (oi * 0.7 + vol * 0.3) / 1000)
        
        # 安全距离
        safety = min(30, (price - short_strike) / price * 100 * 10)
        
        # 参数匹配
        params_match = 1.0 - abs(actual_width - spread_width) / spread_width
        
        return {
            'rr_ratio': rr_ratio,
            'liquidity': liquidity,
            'safety_distance': safety,
            'params_match': max(0, params_match),
            'short_strike': short_strike,
            'long_strike': long_strike
        }
    except:
        return None

# ==================== 主程序 ====================
print("="*70)
print("🚀 垂直价差策略 V3 (完整策略层框架)")
print("="*70)

# VIX信号
vix, vix_ma, deviation, _ = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")

params = SIGNAL_PARAMS[vix_signal]
print(f"   参数: 卖价比={params['short_ratio']}, 安全距离={params['safety_margin']}, 价差=${params['spread_width']}")

# 扫描
results = []
print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")

for sym in STOCKS:
    data = get_stock_data(sym, vix, vix_ma, deviation, vix_signal)
    if data:
        results.append(data)
        
        print(f"{data['decision']} {sym:5s} \${data['price']:7.2f} IV:{data['iv']:5.1f}% "
              f"评分:{data['composite_score']:3.0f} 仓位:{data['position_size']:3d}%")

# 排序
results.sort(key=lambda x: (
    x['decision'] == "✅开仓",
    x['decision'] == "🟡试探",
    x['decision'] == "🔴禁止"
), reverse=True)

# 保存
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS vertical_spreads_v3')
c.execute('''CREATE TABLE vertical_spreads_v3 (
    id INTEGER PRIMARY KEY, RunDateTime TEXT, Symbol TEXT, Price REAL, IV REAL,
    VIX_Signal TEXT, Composite_Score REAL, RR_Ratio REAL, Liquidity REAL,
    Safety_Distance REAL, Short_Strike REAL, Long_Strike REAL, Spread_Width REAL,
    Position_Size REAL, Decision TEXT,
    Price_7d_Lower REAL, Price_7d_Upper REAL,
    Price_14d_Lower REAL, Price_14d_Upper REAL,
    Delta REAL, Theta REAL, Gamma REAL)''')

for r in results:
    c.execute('''INSERT INTO vertical_spreads_v3 VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', 
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), r['symbol'], r['price'], r['iv'],
         r['vix_signal'], r['composite_score'], r['rr_ratio'], r['liquidity'],
         r['safety_distance'], r['short_strike'], r['long_strike'], r['spread_width'],
         r['position_size'], r['decision'],
         r['price_range_7d'][0], r['price_range_7d'][1],
         r['price_range_14d'][0], r['price_range_14d'][1],
         r['greeks']['delta'], r['greeks']['theta'], r['greeks']['gamma']))
conn.commit()
conn.close()

print(f"\n✅ 已保存到 {DB_PATH}")

# 推荐
print("\n" + "="*70)
print("📋 策略推荐 (完整评分)")
print("="*70)

for r in results:
    if r['decision'].startswith("✅"):
        print(f"\n✅ {r['symbol']} Bull Put Spread")
        print(f"   价格: ${r['price']:.2f} | IV: {r['iv']:.1f}% | VIX信号: {r['vix_signal']}")
        print(f"   综合评分: {r['composite_score']:.0f}/100")
        print(f"   评分明细: 盈亏比={r['rr_ratio']:.2f} 流动性={r['liquidity']:.1f} 安全距离={r['safety_distance']:.1f} 参数匹配={r['params_match']:.1f}")
        print(f"   价差: ${r['short_strike']:.2f} / ${r['long_strike']:.2f} (宽${r['spread_width']})")
        print(f"   建议仓位: {r['position_size']}%")
        
        g = r['greeks']
        print(f"   希腊字母: Delta={g['delta']:.4f} Theta={g['theta']:.2f} Gamma={g['gamma']:.6f}")
        
        p7, p14, p30 = r['price_range_7d'], r['price_range_14d'], r['price_range_30d']
        print(f"   价格区间(68%): 7天 ${p7[0]}-${p7[1]} | 14天 ${p14[0]}-${p14[1]} | 30天 ${p30[0]}-${p30[1]}")

# 统计
print(f"\n📊 统计: ✅{sum(1 for r in results if r['decision']=='✅开仓')} | 🟡{sum(1 for r in results if r['decision']=='🟡试探')} | 🔴{sum(1 for r in results if r['decision']=='🔴禁止')}")
