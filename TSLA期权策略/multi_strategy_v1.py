#!/usr/bin/env python3
"""
期权多策略组合推荐 V1
按照MEMORY.md模板格式输出：
- Bull Put Spread (A1/A2/A3)
- Bull Call Spread (B1/B2/B3)
- Short Put (C1/C2/C3)

用法:
  python3 multi_strategy_v1.py           # 默认 TSLA
  python3 multi_strategy_v1.py NVDA       # 指定 NVDA
  python3 multi_strategy_v1.py AAPL MSFT  # 多个股票
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import os
import math
from scipy.stats import norm
import json
import sys
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'

# 从命令行参数获取股票代码，默认TSLA
STOCKS = sys.argv[1:] if len(sys.argv) > 1 else ['TSLA']
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads_v4.db'

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
    """获取股票舆情（通过代理）"""
    try:
        import requests
        from datetime import datetime, timedelta
        
        FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'
        PROXY = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        # 直接调用 API（通过代理）
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&token={FINNHUB_KEY}"
        
        response = requests.get(url, proxies=PROXY, timeout=15)
        
        if response.status_code != 200:
            return "neutral", 0
        
        news = response.json()
        
        if not news:
            return "neutral", 0
        
        bull_kw = ['buy', 'upgrade', 'bull', 'growth', 'target', '上涨', '看好', '突破', '上调', '增持', '强劲', '超预期']
        bear_kw = ['sell', 'downgrade', 'bear', 'risk', 'warning', '下跌', '警告', '风险', '下调', '减持', '疲软', '不及预期']
        
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
    """VIX信号计算（精细化版）
    
    优化逻辑：同时考虑绝对水平和相对变化
    - VIX绝对值 > 30：直接RED（市场恐慌）
    - VIX绝对值 < 15：直接GREEN（极度平静）
    - VIX 15-30：综合偏离度判断，偏离度门槛收紧
    """
    if pd.isna(vix) or pd.isna(vix_ma):
        return "UNKNOWN", 0
    
    # 绝对水平优先判断
    if vix > 30:
        signal = "RED"
    elif vix < 15:
        signal = "GREEN"
    elif vix > 25:
        # VIX偏高（25+），严格收紧偏离度门槛
        if deviation < 3:
            signal = "GREEN"
        elif deviation < 10:
            signal = "YELLOW"
        else:
            signal = "RED"
    elif vix > 20:
        # VIX中偏高（20-25），收紧门槛
        if deviation < 5:
            signal = "GREEN"
        elif deviation < 15:
            signal = "YELLOW"
        else:
            signal = "RED"
    else:
        # VIX正常范围（15-20）
        if deviation < 20:
            signal = "GREEN"
        elif deviation < 50:
            signal = "YELLOW"
        else:
            signal = "RED"
    
    score = 50 + max(min(deviation * 2.5, 25), -25)
    if vix < 15:
        score += 20
    elif vix > 30:
        score -= 20
    elif vix > 20:
        score -= 10
    score = max(0, min(100, score))
    return signal, score

def calculate_option_price(price, strike, iv, days_to_expiry, option_type="put", r=0.05):
    """用Black-Scholes模型计算期权权利金"""
    if days_to_expiry <= 0:
        return 0
    T = days_to_expiry / 365
    if T <= 0:
        return 0
    
    S = price
    K = strike
    sigma = iv / 100
    r_rate = r
    
    d1 = (math.log(S / K) + (r_rate + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if option_type == "put":
        price = K * math.exp(-r_rate * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    else:
        price = S * norm.cdf(d1) - K * math.exp(-r_rate * T) * norm.cdf(d2)
    
    return price

def calculate_theta(price, strike, iv, days_to_expiry, option_type="put"):
    """计算单个期权的Theta（每日时间衰减）"""
    if days_to_expiry <= 0:
        return 0
    T = days_to_expiry / 365
    if T <= 0:
        return 0
    iv_decimal = iv / 100
    S = price
    K = strike
    
    d1 = (math.log(S / K) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
    
    if option_type == "put":
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) - 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(-d1 + iv_decimal * math.sqrt(T)) * 0.01
    else:
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) + 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(d1 - iv_decimal * math.sqrt(T)) * 0.01
    
    return theta / 365

def get_option_price_from_yfinance(ticker, strike, days_to_expiry, option_type="put"):
    """从yfinance获取真实期权价格"""
    try:
        opts = ticker.option_chain()
        if option_type == "put":
            df = opts.puts
        else:
            df = opts.calls
        
        df = df[df['strike'] == strike]
        if df.empty:
            return None, "未找到期权"
        
        row = df.iloc[0]
        price = row['lastPrice']
        
        if price <= 0.01 and row['bid'] > 0 and row['ask'] > 0:
            price = (row['bid'] + row['ask']) / 2
        
        if price <= 0.01:
            return None, "无有效价格"
        
        return price, "yfinance"
    except Exception as e:
        return None, str(e)[:20]

def calculate_composite_score(sentiment, theta_score=0):
    """综合评分"""
    sentiment_scores = {"bullish": 20, "neutral": 10, "bearish": 0}
    sent_score = sentiment_scores.get(sentiment, 10)
    return 70 + sent_score + theta_score  # 基础70分

def get_available_expirations(ticker):
    """获取ticker所有可用的到期日"""
    expirations = []
    base_date = datetime.now()
    
    for days in range(1, 30):
        date = base_date + timedelta(days=days)
        exp_date = date.strftime('%Y-%m-%d')
        try:
            opts = ticker.option_chain(exp_date)
            if not opts.puts.empty:
                actual_days = (date - base_date).days
                if date.weekday() in [0, 1, 2, 3, 4]:
                    expirations.append({
                        'date': exp_date,
                        'days': actual_days,
                        'options': opts
                    })
        except:
            pass
    
    return expirations

def calculate_bull_put_spread(price, iv, short_strike, long_strike, days, ticker=None, options_data=None):
    """计算Bull Put Spread"""
    # 权利金计算
    if options_data is not None:
        puts = options_data.puts
        p_short = puts[puts['strike'] == short_strike]
        p_long = puts[puts['strike'] == long_strike]
        
        if not p_short.empty and not p_long.empty:
            premium_short = p_short.iloc[0]['lastPrice']
            premium_long = p_long.iloc[0]['lastPrice']
            if premium_short <= 0.01:
                premium_short = calculate_option_price(price, short_strike, iv, days, "put")
            if premium_long <= 0.01:
                premium_long = calculate_option_price(price, long_strike, iv, days, "put")
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days, "put")
            premium_long = calculate_option_price(price, long_strike, iv, days, "put")
    elif ticker:
        premium_short_src, _ = get_option_price_from_yfinance(ticker, short_strike, days, "put")
        premium_long_src, _ = get_option_price_from_yfinance(ticker, long_strike, days, "put")
        
        premium_short = premium_short_src if premium_short_src else calculate_option_price(price, short_strike, iv, days, "put")
        premium_long = premium_long_src if premium_long_src else calculate_option_price(price, long_strike, iv, days, "put")
    else:
        premium_short = calculate_option_price(price, short_strike, iv, days, "put")
        premium_long = calculate_option_price(price, long_strike, iv, days, "put")
    
    premium = premium_short - premium_long
    max_loss = (short_strike - long_strike) - premium
    theta_short = abs(calculate_theta(price, short_strike, iv, days, "put"))
    theta_long = abs(calculate_theta(price, long_strike, iv, days, "put"))
    theta = theta_short - theta_long
    
    return {
        'short_strike': short_strike,
        'long_strike': long_strike,
        'premium': premium,
        'max_profit': premium * 100,  # 每组
        'max_loss': max_loss * 100,
        'theta': theta,
        'width': short_strike - long_strike
    }

def calculate_bull_call_spread(price, iv, long_strike, short_strike, days, ticker=None, options_data=None):
    """计算Bull Call Spread"""
    if options_data is not None:
        calls = options_data.calls
        c_short = calls[calls['strike'] == short_strike]
        c_long = calls[calls['strike'] == long_strike]
        
        if not c_short.empty and not c_long.empty:
            premium_short = c_short.iloc[0]['lastPrice']
            premium_long = c_long.iloc[0]['lastPrice']
            if premium_short <= 0.01:
                premium_short = calculate_option_price(price, short_strike, iv, days, "call")
            if premium_long <= 0.01:
                premium_long = calculate_option_price(price, long_strike, iv, days, "call")
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days, "call")
            premium_long = calculate_option_price(price, long_strike, iv, days, "call")
    elif ticker:
        premium_short_src, _ = get_option_price_from_yfinance(ticker, short_strike, days, "call")
        premium_long_src, _ = get_option_price_from_yfinance(ticker, long_strike, days, "call")
        
        premium_short = premium_short_src if premium_short_src else calculate_option_price(price, short_strike, iv, days, "call")
        premium_long = premium_long_src if premium_long_src else calculate_option_price(price, long_strike, iv, days, "call")
    else:
        premium_short = calculate_option_price(price, short_strike, iv, days, "call")
        premium_long = calculate_option_price(price, long_strike, iv, days, "call")
    
    premium = premium_short - premium_long  # 卖 - 买 = 净权利金（卖方收入）
    max_profit = (short_strike - long_strike - premium) * 100
    max_loss = premium * 100
    
    # Bull Call Spread: 买方theta为负，卖方theta为正
    theta_long = calculate_theta(price, long_strike, iv, days, "call")  # 买入call，theta为负
    theta_short = -calculate_option_price(price, short_strike, iv, days, "call") * 0.01  # 卖出call简化
    theta = abs(theta_long) * 0.1  # 简化计算
    
    return {
        'long_strike': long_strike,
        'short_strike': short_strike,
        'premium': premium,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'theta': theta,
        'width': short_strike - long_strike,
        'delta': 0.45  # 简化
    }

def calculate_short_put(price, iv, strike, days, ticker=None, options_data=None):
    """计算Short Put（裸卖看跌）"""
    if options_data is not None:
        puts = options_data.puts
        p = puts[puts['strike'] == strike]
        
        if not p.empty:
            premium = p.iloc[0]['lastPrice']
            if premium <= 0.01:
                premium = calculate_option_price(price, strike, iv, days, "put")
        else:
            premium = calculate_option_price(price, strike, iv, days, "put")
    elif ticker:
        premium_src, _ = get_option_price_from_yfinance(ticker, strike, days, "put")
        premium = premium_src if premium_src else calculate_option_price(price, strike, iv, days, "put")
    else:
        premium = calculate_option_price(price, strike, iv, days, "put")
    
    theta = abs(calculate_theta(price, strike, iv, days, "put"))
    
    return {
        'strike': strike,
        'premium': premium,
        'max_profit': premium * 100,
        'max_loss': (strike - premium) * 100,  # 跌到0的损失
        'theta': theta
    }

def calculate_score(strategy_params, strategy_type, price, days, iv, vix_signal="GREEN", sentiment="neutral"):
    """
    综合评分体系（100分制）
    - 安全距离: 30分
    - Theta收益: 20分
    - 到期天数: 20分
    - 流动性: 15分
    - 权利金效率: 15分
    """
    score = 0
    
    # 1. 安全距离 (30分) - 距离现价的百分比
    if strategy_type in ["Bull_Put", "Short_Put"]:
        strike = strategy_params.get('short_strike', strategy_params.get('strike', price))
        safety = (price - strike) / price * 100  # 距离现价百分比
    elif strategy_type == "Bull_Call":
        strike = strategy_params.get('long_strike', price)
        safety = (strike - price) / price * 100
    else:
        safety = 5
    
    # 安全距离评分: 每1%得3分，最高30分
    safety_score = min(safety * 3, 30)
    score += safety_score
    
    # 2. Theta收益 (20分) - 每日时间价值
    theta = strategy_params.get('theta', 0)
    # Theta评分: 每日Theta × 剩余天数，给20分
    theta_score = min(theta * days * 0.5, 20)
    score += theta_score
    
    # 3. 到期天数 (20分) - 时间越久theta越稳定
    # 1-7天: 10分, 8-14天: 15分, 15-30天: 20分
    if days <= 7:
        expiry_score = 10
    elif days <= 14:
        expiry_score = 15
    else:
        expiry_score = 20
    score += expiry_score
    
    # 4. 流动性 (15分) - 权利金/价差比例（简化的风控）
    premium = strategy_params.get('premium', 0)
    width = strategy_params.get('width', price * 0.05)
    
    if width > 0 and premium > 0:
        premium_ratio = premium / width
        liq_score = min(premium_ratio * 30, 15)  # 权利金/价差比例
    else:
        liq_score = 5
    score += liq_score
    
    # 5. 权利金效率 (15分) - ROI
    max_profit = strategy_params.get('max_profit', 0)
    if width > 0:
        roi = max_profit / (width * 100) * 100  # 权利金/最大亏损
        roi_score = min(roi * 10, 15)
    else:
        roi_score = 5
    score += roi_score
    
    # 6. 市场信号加分 (额外5分)
    if vix_signal == "GREEN":
        score += 5
    elif vix_signal == "YELLOW":
        score += 2
    
    # 7. 舆情加分 (额外5分)
    if sentiment == "bullish":
        score += 5
    elif sentiment == "neutral":
        score += 2
    
    return min(100, max(0, int(score)))

# ==================== 主程序 ====================
print("="*80)
print("🚀 期权多策略组合推荐 V1 (支持多股票)")
print("="*80)
print(f"📊 股票: {', '.join(STOCKS)}")

vix, vix_ma, deviation = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")

# 遍历每个股票
for STOCK in STOCKS:
    print(f"\n{'='*60}")
    print(f"📈 处理: {STOCK}")
    print("="*60)
    
    # 获取股票数据
    try:
        ticker = yf.Ticker(STOCK)
        hist = ticker.history(period="30d")
        if hist.empty:
            print(f"❌ {STOCK} 无法获取股票数据")
            continue
    except Exception as e:
        print(f"❌ {STOCK} 获取数据失败: {e}")
        continue
    
    price = hist['Close'].iloc[-1]
    price = price.item() if hasattr(price, 'item') else price
    
    estimated_iv, hv = get_stock_iv_from_hv(ticker, price)
    iv = estimated_iv if not pd.isna(estimated_iv) else hv
    iv = iv if not pd.isna(iv) else 35
    
    sentiment, sent_ratio = get_sentiment(STOCK)
    
    print(f"\n📈 {STOCK} 价格: ${price:.2f} | IV: {iv:.1f}% | 舆情: {sentiment}")
    
    # 获取可用到期日
    expirations = get_available_expirations(ticker)
    if not expirations:
        print(f"⚠️ {STOCK} 无可用期权到期日")
        continue
    
    # 过滤：只保留14天以内的到期日
    expirations = [e for e in expirations if e['days'] <= 14]
    if not expirations:
        print(f"⚠️ {STOCK} 14天内无到期日")
        continue
        
    print(f"📅 可用到期日(14天内): {[e['date'] for e in expirations[:5]]}")
    
    # ==================== 扫描所有到期日并收集所有组合 ====================
    all_results = {
        'Bull_Put': [],
        'Bull_Call': [],
        'Short_Put': []
    }
    
    # 扫描所有可用到期日
    for exp in expirations:
        days = exp['days']
        exp_date = exp['date']
        expiry_short = exp_date[5:] if exp_date else ""
        options_data = exp['options']
        
        # 不同的行权价组合
        ratios = [
            (0.97, 0.93),  # 保守
            (0.95, 0.91),  # 中等
            (0.93, 0.89),  # 激进
            (0.98, 0.94),  # 更保守
            (0.92, 0.88),  # 更激进
        ]
        
        for short_ratio, long_ratio in ratios:
            short_strike = round(price * short_ratio / 2.5) * 2.5
            long_strike = round(price * long_ratio / 2.5) * 2.5
            
            # Bull Put Spread
            bp = calculate_bull_put_spread(price, iv, short_strike, long_strike, days, ticker, options_data)
            bp['score'] = calculate_score(bp, 'Bull_Put', price, days, iv, vix_signal, sentiment)
            bp['days'] = days
            bp['expiry'] = expiry_short
            bp['strike_str'] = f"卖${short_strike:.0f}/买${long_strike:.0f}"
            all_results['Bull_Put'].append(bp)
            
            # Bull Call Spread
            long_s = round(price * (2 - short_ratio) / 2.5) * 2.5  # 反向
            short_s = round(price * (2 - long_ratio) / 2.5) * 2.5
            bc = calculate_bull_call_spread(price, iv, long_s, short_s, days, ticker, options_data)
            bc['score'] = calculate_score(bc, 'Bull_Call', price, days, iv, vix_signal, sentiment)
            bc['days'] = days
            bc['expiry'] = expiry_short
            bc['strike_str'] = f"买${long_s:.0f}/卖${short_s:.0f}"
            all_results['Bull_Call'].append(bc)
            
            # Short Put
            sp = calculate_short_put(price, iv, short_strike, days, ticker, options_data)
            sp['score'] = calculate_score(sp, 'Short_Put', price, days, iv, vix_signal, sentiment)
            sp['days'] = days
            sp['expiry'] = expiry_short
            sp['strike_str'] = f"卖${short_strike:.0f}"
            all_results['Short_Put'].append(sp)
    
    # 按评分降序排序，取前5
    for strategy in all_results:
        all_results[strategy].sort(key=lambda x: x['score'], reverse=True)
        all_results[strategy] = all_results[strategy][:5]
    
    # ==================== 输出格式化结果 ====================
    print("\n" + "-"*60)
    print(f"📊 {STOCK} 多策略组合推荐 | {datetime.now().strftime('%Y-%m-%d')}")
    print("-"*60)
    print(f"\n现价：${price:.2f} | IV: {iv:.1f}% | VIX: {vix:.2f}")
    
    # 🅰️ Bull Put Spread - 前5
    print("\n🅰️ 策略A：Bull Put Spread（看跌价差）- 温和看涨")
    print("| # | 行权价 | 到期日 | 权利金 | 最大盈利 | 最大亏损 | Theta | 评分 |")
    print("|---|--------|--------|--------|----------|----------|-------|------|")
    for i, bp in enumerate(all_results['Bull_Put'], 1):
        print(f"| {i} | {bp['strike_str']:10s} | {bp['expiry']:6s} | ${bp['premium']:.2f} | ${bp['max_profit']:.0f} | ${bp['max_loss']:.0f} | ${bp['theta']:.2f}/天 | {bp['score']} |")
    
    # 🅱️ Bull Call Spread - 前5
    print("\n🅱️ 策略B：Bull Call Spread（看涨价差）- 突破上涨")
    print("| # | 行权价 | 到期日 | 权利金 | 最大盈利 | 最大亏损 | Delta | 评分 |")
    print("|---|--------|--------|--------|----------|----------|-------|------|")
    for i, bc in enumerate(all_results['Bull_Call'], 1):
        print(f"| {i} | {bc['strike_str']:10s} | {bc['expiry']:6s} | ${abs(bc['premium']):.2f} | ${abs(bc['max_profit']):.0f} | ${abs(bc['max_loss']):.0f} | {bc.get('delta', 0.45):.2f} | {bc['score']} |")
    
    # 🅾️ Short Put - 前5
    print("\n🅾️ 策略C：Short Put（裸卖看跌）- 高Theta收益")
    print("| # | 行权价 | 到期日 | 权利金 | 最大盈利 | 最大亏损 | Theta | 评分 |")
    print("|---|--------|--------|--------|----------|----------|-------|------|")
    for i, sp in enumerate(all_results['Short_Put'], 1):
        print(f"| {i} | {sp['strike_str']:10s} | {sp['expiry']:6s} | ${sp['premium']:.2f} | ${sp['max_profit']:.0f} | ∞ | ${sp['theta']:.2f}/天 | {sp['score']} |")
    
    # 结论 - 找最优
    best_bp = all_results['Bull_Put'][0] if all_results['Bull_Put'] else None
    best_bc = all_results['Bull_Call'][0] if all_results['Bull_Call'] else None
    best_sp = all_results['Short_Put'][0] if all_results['Short_Put'] else None
    
    print(f"\n💡 {STOCK} 结论：")
    if best_bp:
        print(f"   🐂 温和看涨选 Bull Put: {best_bp['strike_str']} {best_bp['expiry']}, 评分{best_bp['score']}")
    if best_bc:
        print(f"   🚀 突破上涨选 Bull Call: {best_bc['strike_str']} {best_bc['expiry']}, 评分{best_bc['score']}")
    if best_sp:
        print(f"   ⚡ 极致Theta选 Short Put: {best_sp['strike_str']} {best_sp['expiry']}, 评分{best_sp['score']}")
    

print(f"\n✅ 多股票策略分析完成: {', '.join(STOCKS)}")
