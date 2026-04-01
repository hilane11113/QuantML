#!/usr/bin/env python3
"""
垂直价差推荐策略 (增强版 V4)
根据评分和信号推荐不同类型的期权策略
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
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_v4.db'

# ==================== 风险参数表 ====================
SIGNAL_PARAMS = {
    "GREEN": {"short_ratio": 0.96, "safety_margin": 0.04, "spread_width": 25},
    "YELLOW": {"short_ratio": 0.92, "safety_margin": 0.08, "spread_width": 20},
    "RED": {"short_ratio": 0.88, "safety_margin": 0.12, "spread_width": 15}
}

# ==================== 策略类型定义 ====================
STRATEGY_TYPES = {
    "Bull_Put_Spread": {
        "name": "Bull Put Spread",
        "中文": "牛市看跌价差",
        "适合": "温和看涨/震荡上行",
        "收益": "有限",
        "风险": "有限"
    },
    "Bull_Call_Spread": {
        "name": "Bull Call Spread", 
        "中文": "牛市看涨价差",
        "适合": "强烈看涨/突破上涨",
        "收益": "有限",
        "风险": "有限"
    },
    "Iron_Condor": {
        "name": "Iron Condor",
        "中文": "铁鹰价差",
        "适合": "中性/低波动",
        "收益": "有限",
        "风险": "有限"
    },
    "Straddle": {
        "name": "Long Straddle",
        "中文": "跨式期权",
        "适合": "大幅波动/突破",
        "收益": "无限",
        "风险": "有限"
    }
}

def get_vix():
    try:
        vix = yf.download("^VIX", period="30d", timeout=10)["Close"]
        if len(vix) < 10:
            return np.nan, np.nan, np.nan
        current = vix.iloc[-1].item()
        ma10 = vix.tail(10).mean().item()
        deviation = (current - ma10) / ma10 * 100
        return current, ma10, deviation
    except:
        return np.nan, np.nan, np.nan

def get_stock_iv_from_hv(ticker, price):
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
    if pd.isna(vix) or pd.isna(vix_ma):
        return "UNKNOWN", 0
    if deviation > 5:
        signal = "GREEN"
    elif deviation < -5:
        signal = "RED"
    else:
        signal = "YELLOW"
    score = 50 + max(min(deviation * 2.5, 25), -25)
    if vix < 15:
        score += 20
    elif vix > 30:
        score -= 20
    elif vix > 20:
        score -= 10
    score = max(0, min(100, score))
    return signal, score

def calculate_composite_score(rr_ratio, liquidity_score, safety_distance, params_match, sentiment_score):
    rr_score = min(rr_ratio / 2.0, 1.0) * 30
    liq_score = min(liquidity_score * 2, 20)
    safety_score = min(safety_distance * 2, 20)
    param_score = params_match * 10
    sentiment_scores = {"bullish": 20, "neutral": 10, "bearish": 0}
    sent_score = sentiment_scores.get(sentiment_score, 10)
    total = rr_score + liq_score + safety_score + param_score + sent_score
    return min(100, max(0, total))

def recommend_strategy_type(signal, sentiment, iv, composite_score):
    """根据信号、情绪、IV推荐策略类型"""
    if signal == "GREEN" and sentiment == "bullish" and composite_score >= 50:
        # 强烈看涨
        return "Bull_Call_Spread", "🐂 强烈看涨"
    elif signal == "GREEN" and composite_score >= 30:
        # 温和看涨
        return "Bull_Put_Spread", "🐂 温和看涨"
    elif signal == "YELLOW" and composite_score >= 40:
        # 中性策略
        return "Iron_Condor", "⚖️ 中性震荡"
    elif iv > 60:
        # 高IV，适合做空波动率
        return "Iron_Condor", "📉 高IV做空波动"
    elif signal == "RED" or composite_score < 20:
        # 观望
        return "None", "⏸️ 观望"
    else:
        return "Bull_Put_Spread", "🐂 温和看涨"

def calculate_strategy_details(price, iv, strategy_type, sentiment):
    """根据策略类型计算详细参数"""
    params = {}
    
    if strategy_type == "Bull_Put_Spread":
        # 卖高买低
        short_ratio = 0.95
        long_ratio = 0.90
        params = {
            "short_strike": round(price * short_ratio / 2.5) * 2.5,
            "long_strike": round(price * long_ratio / 2.5) * 2.5,
            "width": price * (short_ratio - long_ratio),
            "max_profit_estimate": price * 0.02,
            "max_loss_estimate": price * 0.05
        }
    elif strategy_type == "Bull_Call_Spread":
        # 买低卖高
        long_ratio = 0.95
        short_ratio = 1.00
        params = {
            "short_strike": round(price * short_ratio / 2.5) * 2.5,
            "long_strike": round(price * long_ratio / 2.5) * 2.5,
            "width": price * (short_ratio - long_ratio),
            "max_profit_estimate": price * 0.03,
            "max_loss_estimate": price * 0.02
        }
    elif strategy_type == "Iron_Condor":
        # 卖宽跨式
        params = {
            "put_short": round(price * 0.92 / 2.5) * 2.5,
            "put_long": round(price * 0.88 / 2.5) * 2.5,
            "call_short": round(price * 1.08 / 2.5) * 2.5,
            "call_long": round(price * 1.12 / 2.5) * 2.5,
            "width": price * 0.08,
            "max_profit_estimate": price * 0.015,
            "max_loss_estimate": price * 0.04
        }
    else:
        params = {"note": "观望"}
    
    return params

def get_stock_data(symbol, vix, vix_ma, deviation, vix_signal):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist.empty:
            return None
        
        price = hist['Close'].iloc[-1]
        price = price.item() if hasattr(price, 'item') else price
        
        estimated_iv, hv = get_stock_iv_from_hv(ticker, price)
        iv = estimated_iv if not pd.isna(estimated_iv) else hv
        iv = iv if not pd.isna(iv) else 35
        
        sentiment, sent_ratio = get_sentiment(symbol)
        
        # 计算评分
        spread_data = {
            'rr_ratio': 1.0,
            'liquidity': 10,
            'safety_distance': 15,
            'params_match': 0.7
        }
        
        composite_score = calculate_composite_score(
            spread_data['rr_ratio'],
            spread_data['liquidity'],
            spread_data['safety_distance'],
            spread_data['params_match'],
            sentiment
        )
        
        # 推荐策略类型
        strategy_type, strategy_desc = recommend_strategy_type(vix_signal, sentiment, iv, composite_score)
        
        # 计算策略参数
        strategy_params = calculate_strategy_details(price, iv, strategy_type, sentiment)
        
        # 决策
        if strategy_type == "None":
            decision = "🔴禁止"
            position = 0
        elif composite_score >= 50:
            decision = "✅开仓"
            position = int(composite_score)
        elif composite_score >= 30:
            decision = "🟡试探"
            position = int(composite_score * 0.6)
        else:
            decision = "🔴禁止"
            position = 0
        
        return {
            'symbol': symbol,
            'price': price,
            'iv': iv,
            'hv': hv,
            'vix': vix,
            'vix_signal': vix_signal,
            'sentiment': sentiment,
            'sentiment_ratio': sent_ratio,
            'composite_score': composite_score,
            'strategy_type': strategy_type,
            'strategy_desc': strategy_desc,
            'strategy_params': strategy_params,
            'decision': decision,
            'position': position
        }
    except Exception as e:
        print(f"   ⚠️ {symbol}: {e}")
        return None

# ==================== 主程序 ====================
print("="*80)
print("🚀 垂直价差策略 V4 (多策略推荐)")
print("="*80)

vix, vix_ma, deviation = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")

results = []
print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")

for sym in STOCKS:
    data = get_stock_data(sym, vix, vix_ma, deviation, vix_signal)
    if data:
        results.append(data)
        
        print(f"{data['decision']} {sym:5s} \${data['price']:7.2f} "
              f"IV:{data['iv']:5.1f}% 评分:{data['composite_score']:3.0f} "
              f"{data['strategy_desc']}")

# 排序
results.sort(key=lambda x: x['composite_score'], reverse=True)

# 保存
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('DROP TABLE IF EXISTS vertical_spreads_v4')
c.execute('''CREATE TABLE vertical_spreads_v4 (
    id INTEGER PRIMARY KEY, RunDateTime TEXT, Symbol TEXT, Price REAL, IV REAL,
    VIX_Signal TEXT, Sentiment TEXT, Composite_Score REAL,
    Strategy_Type TEXT, Strategy_Desc TEXT,
    Decision TEXT, Position INTEGER)''')

for r in results:
    c.execute('INSERT INTO vertical_spreads_v4 VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)', 
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), r['symbol'], r['price'], r['iv'],
         r['vix_signal'], r['sentiment'], r['composite_score'],
         r['strategy_type'], r['strategy_desc'],
         r['decision'], r['position']))
conn.commit()
conn.close()

print(f"\n✅ 已保存到 {DB_PATH}")

# 详细报告
print("\n" + "="*80)
print("📋 策略推荐详情")
print("="*80)

for r in results:
    if r['decision'] != "🔴禁止":
        print(f"\n{'='*60}")
        print(f"📈 {r['symbol']} - {r['strategy_desc']}")
        print(f"{'='*60}")
        print(f"   价格: ${r['price']:.2f}")
        print(f"   IV: {r['iv']:.1f}% | VIX信号: {r['vix_signal']}")
        print(f"   舆情: {r['sentiment']} ({r['sentiment_ratio']:.0%})")
        print(f"   综合评分: {r['composite_score']:.0f}/100")
        
        sp = r['strategy_params']
        if r['strategy_type'] == "Bull_Put_Spread":
            print(f"\n   📌 Bull Put Spread (牛市看跌价差)")
            print(f"      卖出行权价: ${sp.get('short_strike', 'N/A')}")
            print(f"      买进行权价: ${sp.get('long_strike', 'N/A')}")
            print(f"      价差宽度: ${sp.get('width', 'N/A'):.2f}")
            print(f"      预计最大盈利: ${sp.get('max_profit_estimate', 'N/A'):.2f}")
            print(f"      预计最大亏损: ${sp.get('max_loss_estimate', 'N/A'):.2f}")
        elif r['strategy_type'] == "Bull_Call_Spread":
            print(f"\n   📌 Bull Call Spread (牛市看涨价差)")
            print(f"      买进行权价: ${sp.get('long_strike', 'N/A')}")
            print(f"      卖出行权价: ${sp.get('short_strike', 'N/A')}")
            print(f"      价差宽度: ${sp.get('width', 'N/A'):.2f}")
        elif r['strategy_type'] == "Iron_Condor":
            print(f"\n   📌 Iron Condor (铁鹰价差)")
            print(f"      Put卖: ${sp.get('put_short', 'N/A')} | Put买: ${sp.get('put_long', 'N/A')}")
            print(f"      Call卖: ${sp.get('call_short', 'N/A')} | Call买: ${sp.get('call_long', 'N/A')}")
        
        print(f"\n   建议仓位: {r['position']}%")

# 统计
print(f"\n📊 统计: ✅{sum(1 for r in results if r['decision']=='✅开仓')} | "
      f"🟡{sum(1 for r in results if r['decision']=='🟡试探')} | "
      f"🔴{sum(1 for r in results if r['decision']=='🔴禁止')}")

# 策略分布
print("\n📊 策略分布:")
strategy_counts = {}
for r in results:
    t = r['strategy_type']
    strategy_counts[t] = strategy_counts.get(t, 0) + 1
for t, c in strategy_counts.items():
    print(f"   {t}: {c}个")
