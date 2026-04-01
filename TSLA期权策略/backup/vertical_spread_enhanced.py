#!/usr/bin/env python3
"""
垂直价差推荐策略 (增强版)
结合 VIX/IV 数据 + 舆情分析，动态调整价差宽度

逻辑:
- VIX趋势 + IV条件 → 基础决策
- 舆情分析 → 调整价差宽度
- 看涨情绪 → 宽价差 (20-35点)
- 中性情绪 → 标准价差 (15-25点)
- 看跌情绪 → 窄价差 (10-15点)
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

# Finnhub
FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'

STOCKS = ['TSLA', 'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'AMD']
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_enhanced.db'

def get_vix():
    """获取VIX和MA"""
    try:
        vix = yf.download("^VIX", period="10d")["Close"]
        if len(vix) < 5:
            return np.nan, np.nan
        current = vix.iloc[-1]
        ma10 = vix.tail(5).mean()
        current = current.item() if isinstance(current, pd.Series) else current
        ma10 = ma10.item() if isinstance(ma10, pd.Series) else ma10
        return current, ma10
    except:
        return np.nan, np.nan

def get_sentiment(symbol):
    """获取舆情情绪"""
    try:
        import finnhub
        client = finnhub.Client(api_key=FINNHUB_KEY)
        news = client.company_news(symbol, _from='2026-02-25', to='2026-03-01')
        
        if not news:
            return "neutral", 0
        
        # 情绪关键词
        bull_kw = ['buy', 'upgrade', 'bull', 'growth', 'target', '上涨', '看好', '突破']
        bear_kw = ['sell', 'downgrade', 'bear', 'risk', 'warning', '下跌', '警告', '风险']
        
        bull = 0
        bear = 0
        
        for n in news[:20]:
            title = n.get('headline', '').lower()
            if any(k in title for k in bull_kw):
                bull += 1
            if any(k in title for k in bear_kw):
                bear += 1
        
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

def get_stock_data(symbol, vix, vix_ma):
    """获取个股数据+决策"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist.empty:
            return None
        
        price = hist['Close'].iloc[-1]
        price = price.item() if isinstance(price, pd.Series) else price
        
        # HV
        returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        hv = returns.tail(20).std() * np.sqrt(252) * 100
        hv = hv.item() if isinstance(hv, pd.Series) else hv
        
        # IV
        iv = np.nan
        if ticker.options:
            try:
                opt = ticker.option_chain(ticker.options[0])
                puts = opt.puts
                atm = min(puts['strike'], key=lambda x: abs(x - price))
                iv = puts[puts['strike'] == atm].iloc[0].get('impliedVolatility', np.nan)
                iv = (iv * 100) if pd.notna(iv) else np.nan
            except:
                pass
        
        iv_hv = (iv / hv * 100) if pd.notna(iv) and pd.notna(hv) else np.nan
        
        # 舆情
        sentiment, sent_ratio = get_sentiment(symbol)
        
        # VIX决策
        vix_ok = vix < vix_ma if pd.notna(vix) and pd.notna(vix_ma) else False
        iv_ok = 30 <= iv <= 50 if pd.notna(iv) else False
        iv_hv_ok = 100 <= iv_hv <= 140 if pd.notna(iv_hv) else False
        
        if not vix_ok:
            decision = "🔴禁止"
        elif iv_ok and iv_hv_ok:
            decision = "✅开仓"
        elif iv_ok or iv_hv_ok:
            decision = "🟡试探"
        else:
            decision = "🔴禁止"
        
        # 计算价差宽度
        spread_width = calculate_spread_width(sentiment, iv, decision)
        
        return {
            'symbol': symbol,
            'price': price,
            'iv': iv,
            'hv': hv,
            'iv_hv': iv_hv,
            'decision': decision,
            'sentiment': sentiment,
            'sent_ratio': sent_ratio,
            'spread_width': spread_width,
            'vix': vix
        }
    except Exception as e:
        return None

def calculate_spread_width(sentiment, iv, decision):
    """根据舆情动态调整价差宽度"""
    if decision.startswith("🔴"):
        return 0
    
    # 基础宽度
    base_width = 20
    
    # 根据情绪调整
    if sentiment == "bullish":
        # 看涨: 宽价差 (+10)
        width = min(35, base_width + 10)
    elif sentiment == "bearish":
        # 看跌: 窄价差 (-10)
        width = max(10, base_width - 10)
    else:
        # 中性: 标准宽度
        width = base_width
    
    # 根据IV进一步调整
    if pd.notna(iv):
        if iv > 50:
            width = min(35, width + 5)  # IV高则加宽
        elif iv < 30:
            width = max(10, width - 5)  # IV低则收窄
    
    return width

# 主程序
print("="*60)
print("🚀 垂直价差策略扫描 (增强版 - 含舆情)")
print("="*60)

# VIX
vix, vix_ma = get_vix()
print(f"\n📊 VIX: {vix:.2f} | MA: {vix_ma:.2f} | {'🟢' if vix < vix_ma else '🔴'}")

# 扫描
results = []
print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")

for sym in STOCKS:
    data = get_stock_data(sym, vix, vix_ma)
    if data:
        results.append(data)
        
        # 输出
        iv_str = f"{data['iv']:.1f}%" if pd.notna(data['iv']) else "N/A"
        sent_emoji = "🐂" if data['sentiment'] == "bullish" else "🐻" if data['sentiment'] == "bearish" else "😐"
        
        print(f"{data['decision']} {sym:5s} \${data['price']:7.2f}  IV:{iv_str:>6s}  情绪:{sent_emoji}{data['sentiment']:8s}  价差:{data['spread_width']:.0f}点")

# 排序
results.sort(key=lambda x: (
    x['decision'] == "✅开仓",
    x['decision'] == "🟡试探",
    x['decision'] == "🔴禁止"
), reverse=True)

# 保存
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS vertical_spreads_enhanced')
c.execute('''CREATE TABLE vertical_spreads_enhanced (
    id INTEGER PRIMARY KEY, RunDateTime TEXT, Symbol TEXT, Price REAL, IV REAL, HV REAL,
    IV_HV_Ratio REAL, VIX_Level REAL, Sentiment TEXT, Spread_Width REAL, Decision TEXT)''')

for r in results:
    c.execute('INSERT INTO vertical_spreads_enhanced VALUES (NULL,?,?,?,?,?,?,?,?,?,?)', 
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), r['symbol'], r['price'], r['iv'], r['hv'], 
         r['iv_hv'], r['vix'], r['sentiment'], r['spread_width'], r['decision']))
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
        print(f"   价差宽度: {r['spread_width']:.0f}点 (动态调整)")
        
        # 计算推荐执行价
        short_strike = r['price'] * 0.95
        long_strike = short_strike - r['spread_width']
        print(f"   Short Strike: ${short_strike:.2f}")
        print(f"   Long Strike:  ${long_strike:.2f}")

# 统计
print(f"\n📊 统计: ✅{sum(1 for r in results if r['decision']=='✅开仓')} | 🟡{sum(1 for r in results if r['decision']=='🟡试探')} | 🔴{sum(1 for r in results if r['decision']=='🔴禁止')}")
