#!/usr/bin/env python3
"""
垂直价差推荐策略 (增强版 V2)
改进点:
1. 用HV估算IV (解决yfinance IV数据异常问题)
2. VIX信号引入偏离度 (不再只看是否大于MA)
3. 加入希腊字母风控
4. 动态仓位公式
"""

import sqlite3
import pandas as pd
from datetime import datetime
import yfinance as yf
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

STOCKS = ['TSLA', 'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'AMD']
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_v2.db'

def get_vix():
    """获取VIX和MA10"""
    try:
        vix = yf.download("^VIX", period="30d", timeout=10)["Close"]
        if len(vix) < 10:
            return np.nan, np.nan, np.nan, np.nan
        
        current = vix.iloc[-1].item()
        ma10 = vix.tail(10).mean().item()
        
        # 计算偏离度
        deviation = (current - ma10) / ma10 * 100
        
        return current, ma10, deviation, vix
    except:
        return np.nan, np.nan, np.nan, None

def get_stock_iv_from_hv(ticker, price):
    """用HV估算IV (解决yfinance IV数据异常问题)"""
    try:
        hist = ticker.history(period="30d")
        if hist.empty:
            return np.nan
        
        returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        
        # HV计算 (20日)
        hv_20 = returns.tail(20).std() * np.sqrt(252) * 100
        hv_20 = hv_20.item() if hasattr(hv_20, 'item') else hv_20
        
        # IV通常比HV高10-20%
        estimated_iv = hv_20 * 1.15
        
        # 尝试获取真实IV作为参考
        real_iv = np.nan
        if ticker.options:
            try:
                opt = ticker.option_chain(ticker.options[0])
                puts = opt.puts
                atm_put = puts[abs(puts['strike'] - price) == min(abs(puts['strike'] - price))]
                if not atm_put.empty:
                    raw_iv = atm_put['impliedVolatility'].iloc[0]
                    if not pd.isna(raw_iv) and raw_iv > 0.1:  # 过滤异常值
                        real_iv = raw_iv * 100
            except:
                pass
        
        return estimated_iv, hv_20, real_iv
    except:
        return np.nan, np.nan, np.nan

def get_sentiment(symbol):
    """获取舆情情绪 (简化版)"""
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
    """改进的VIX信号判断"""
    if pd.isna(vix) or pd.isna(vix_ma):
        return "UNKNOWN", 0
    
    # 信号级别基于偏离度
    if deviation > 5:
        signal = "GREEN"  # VIX远高于MA10，市场恐慌
    elif deviation < -5:
        signal = "RED"    # VIX远低于MA10，可能V型反转
    else:
        signal = "YELLOW" # 正常范围
    
    # 综合评分 (0-100)
    score = 50  # 基础分
    
    # 偏离度贡献 (-25到+25)
    score += max(min(deviation * 2.5, 25), -25)
    
    # VIX绝对值贡献
    if vix < 15:
        score += 20  # 低VIX利于开仓
    elif vix > 30:
        score -= 20 # 高VIX风险大
    elif vix > 20:
        score -= 10
    
    score = max(0, min(100, score))
    
    return signal, score

def calculate_spread_greeks_simple(price, short_strike, long_strike, days, iv):
    """简化希腊字母计算"""
    try:
        import math
        from scipy.stats import norm
        
        r = 0.02  # 无风险利率
        T = days / 365.0
        iv_decimal = iv / 100
        
        # 计算d1
        d1_short = (math.log(price / short_strike) + (r + iv_decimal**2/2) * T) / (iv_decimal * math.sqrt(T))
        d1_long = (math.log(price / long_strike) + (r + iv_decimal**2/2) * T) / (iv_decimal * math.sqrt(T))
        
        # Put Delta
        delta_short = norm.cdf(d1_short) - 1
        delta_long = norm.cdf(d1_long) - 1
        spread_delta = delta_short - delta_long
        
        # Theta (每日)
        theta_short = -(price * iv_decimal * norm.pdf(d1_short)) / (2 * math.sqrt(365))
        theta_long = -(price * iv_decimal * norm.pdf(d1_long)) / (2 * math.sqrt(365))
        spread_theta = theta_short - theta_long
        
        return {
            'delta': round(spread_delta, 4),
            'theta': round(spread_theta, 2),
            'delta_direction': '看跌' if spread_delta < 0 else '中性'
        }
    except:
        return {'delta': 0, 'theta': 0, 'delta_direction': '未知'}

def get_stock_data(symbol, vix, vix_ma, deviation, vix_score):
    """获取个股数据+决策"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist.empty:
            return None
        
        price = hist['Close'].iloc[-1]
        price = price.item() if hasattr(price, 'item') else price
        
        # 用HV估算IV
        estimated_iv, hv_20, real_iv = get_stock_iv_from_hv(ticker, price)
        
        # 使用估算IV (更可靠)
        iv = estimated_iv if not pd.isna(estimated_iv) else hv_20
        iv_source = "估算" if pd.isna(real_iv) or real_iv < 5 else "真实"
        
        # IV/HV比
        iv_hv_ratio = (iv / hv_20 * 100) if hv_20 > 0 else np.nan
        
        # 舆情
        sentiment, sent_ratio = get_sentiment(symbol)
        
        # VIX信号判断
        vix_signal, _ = calculate_vix_signal(vix, vix_ma, deviation)
        
        # 开仓决策 (改进逻辑)
        # 条件1: VIX信号
        # 条件2: IV在合理范围 (25%-60%)
        # 条件3: IV/HV比在100%-150% (正常市场)
        
        iv_ok = 25 <= iv <= 60 if not pd.isna(iv) else False
        iv_hv_ok = 100 <= iv_hv_ratio <= 150 if not pd.isna(iv_hv_ratio) else True
        
        if vix_signal == "GREEN" and iv_ok and iv_hv_ok:
            decision = "✅开仓"
        elif vix_signal == "YELLOW" and iv_ok:
            decision = "🟡试探"
        else:
            decision = "🔴禁止"
        
        # 计算价差宽度
        spread_width = calculate_spread_width(sentiment, iv, decision)
        
        # 动态仓位
        position_size = calculate_position_size(vix_score, iv, decision)
        
        # 希腊字母 (简化)
        if decision.startswith("✅") or decision.startswith("🟡"):
            days = 30  # 假设30天到期
            short_strike = price * 0.95
            long_strike = short_strike - spread_width
            greeks = calculate_spread_greeks_simple(price, short_strike, long_strike, days, iv)
        else:
            greeks = {'delta': 0, 'theta': 0, 'delta_direction': 'N/A'}
        
        return {
            'symbol': symbol,
            'price': price,
            'iv': iv,
            'hv': hv_20,
            'iv_source': iv_source,
            'iv_hv_ratio': iv_hv_ratio,
            'vix': vix,
            'vix_signal': vix_signal,
            'decision': decision,
            'sentiment': sentiment,
            'sent_ratio': sent_ratio,
            'spread_width': spread_width,
            'position_size': position_size,
            'greeks': greeks
        }
    except Exception as e:
        print(f"   ⚠️ {symbol}: {e}")
        return None

def calculate_spread_width(sentiment, iv, decision):
    """根据舆情动态调整价差宽度"""
    if decision.startswith("🔴"):
        return 0
    
    base_width = 20
    
    if sentiment == "bullish":
        width = min(35, base_width + 10)
    elif sentiment == "bearish":
        width = max(10, base_width - 10)
    else:
        width = base_width
    
    if not pd.isna(iv):
        if iv > 50:
            width = min(35, width + 5)
        elif iv < 30:
            width = max(10, width - 5)
    
    return width

def calculate_position_size(vix_score, iv, decision):
    """动态仓位计算"""
    if decision.startswith("🔴"):
        return 0
    
    # 基础仓位
    base = 100
    
    # VIX评分调整
    vix_factor = vix_score / 100
    
    # IV调整
    if pd.isna(iv):
        iv_factor = 0.5
    elif iv < 25:
        iv_factor = 0.6  # IV太低，仓位降低
    elif iv > 50:
        iv_factor = 0.7  # IV太高，仓位降低
    else:
        iv_factor = 1.0
    
    position = base * vix_factor * iv_factor
    
    # 限制范围
    position = max(0, min(100, position))
    
    return int(position)

# 主程序
print("="*60)
print("🚀 垂直价差策略扫描 (增强版 V2)")
print("="*60)

# VIX信号
vix, vix_ma, deviation, _ = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")

# 扫描
results = []
print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")

for sym in STOCKS:
    data = get_stock_data(sym, vix, vix_ma, deviation, vix_score)
    if data:
        results.append(data)
        
        iv_str = f"{data['iv']:.1f}%" if not pd.isna(data['iv']) else "N/A"
        sent_emoji = "🐂" if data['sentiment'] == "bullish" else "🐻" if data['sentiment'] == "bearish" else "😐"
        
        print(f"{data['decision']} {sym:5s} \${data['price']:7.2f}  IV:{iv_str:>6s}({data['iv_source']})  仓位:{data['position_size']:3d}%")

# 排序
results.sort(key=lambda x: (
    x['decision'] == "✅开仓",
    x['decision'] == "🟡试探",
    x['decision'] == "🔴禁止"
), reverse=True)

# 保存
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS vertical_spreads_v2')
c.execute('''CREATE TABLE vertical_spreads_v2 (
    id INTEGER PRIMARY KEY, RunDateTime TEXT, Symbol TEXT, Price REAL, IV REAL, HV REAL,
    IV_HV_Ratio REAL, VIX_Level REAL, VIX_Signal TEXT, Sentiment TEXT, 
    Spread_Width REAL, Position_Size REAL, Decision TEXT)''')

for r in results:
    c.execute('INSERT INTO vertical_spreads_v2 VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)', 
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), r['symbol'], r['price'], r['iv'], r['hv'], 
         r['iv_hv_ratio'], r['vix'], r['vix_signal'], r['sentiment'], 
         r['spread_width'], r['position_size'], r['decision']))
conn.commit()
conn.close()

print(f"\n✅ 已保存到 {DB_PATH}")

# 推荐
print("\n" + "="*60)
print("📋 策略推荐")
print("="*60)

for r in results:
    if r['decision'].startswith("✅"):
        print(f"\n✅ {r['symbol']} Bull Put Spread")
        print(f"   价格: ${r['price']:.2f}")
        print(f"   情绪: {r['sentiment']} ({r['sent_ratio']:.0%})")
        print(f"   价差宽度: {r['spread_width']:.0f}点")
        print(f"   建议仓位: {r['position_size']}%")
        
        short_strike = r['price'] * 0.95
        long_strike = short_strike - r['spread_width']
        print(f"   Short Strike: ${short_strike:.2f}")
        print(f"   Long Strike:  ${long_strike:.2f}")
        
        g = r['greeks']
        print(f"   Delta: {g['delta']:.4f} ({g['delta_direction']})")
        print(f"   Theta: {g['theta']:.2f}/天")

# 统计
print(f"\n📊 统计: ✅{sum(1 for r in results if r['decision']=='✅开仓')} | 🟡{sum(1 for r in results if r['decision']=='🟡试探')} | 🔴{sum(1 for r in results if r['decision']=='🔴禁止')}")
