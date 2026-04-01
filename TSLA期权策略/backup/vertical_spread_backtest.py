#!/usr/bin/env python3
"""
TSLA期权垂直价差策略 - Qlib回测版
独立运行，不干扰原策略
"""

import pandas as pd
import numpy as np
import yfinance as yf
import os
import sqlite3
from datetime import datetime, timedelta
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/backtest.db'

# ==================== 数据获取 ====================

def get_stock_price(symbol, days=30):
    """获取股票价格历史"""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{days}d")
    if hist.empty:
        return None
    return hist['Close'].tolist()

def get_iv(symbol):
    """获取隐含波动率"""
    ticker = yf.Ticker(symbol)
    try:
        opt = ticker.option_chain()
        puts = opt.puts
        if not puts.empty:
            return puts['impliedVolatility'].mean()
    except:
        pass
    return 0.35  # 默认35%

def get_option_price(symbol, strike, days, option_type="put"):
    """获取期权价格"""
    ticker = yf.Ticker(symbol)
    try:
        opts = ticker.option_chain()
        if option_type == "put":
            df = opts.puts
        else:
            df = opts.calls
        
        row = df[df['strike'] == strike]
        if not row.empty:
            return row.iloc[0]['lastPrice']
    except:
        pass
    # 如果获取不到，用BS模型
    return calculate_bs_price(symbol, strike, days, option_type)

def calculate_bs_price(symbol, strike, days, option_type="put", r=0.05):
    """Black-Scholes模型计算期权价格"""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="30d")
    if hist.empty:
        return 0
    
    S = hist['Close'].iloc[-1]
    K = strike
    T = days / 365
    sigma = get_iv(symbol)
    
    if T <= 0 or sigma <= 0:
        return 0
    
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    
    if option_type == "put":
        price = K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)
    else:
        price = S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    
    return price if price > 0 else 0

# ==================== 策略因子计算 ====================

def calculate_factors(price, iv, sentiment, days, strike=None):
    """计算策略因子"""
    if strike is None:
        strike = price * 0.95  # 默认95%行权价
    
    factors = {}
    
    # 安全距离因子
    factors['safety'] = max(0, (price - strike) / price) * 100
    
    # 流动性因子（基于IV）
    factors['liquidity'] = min(iv / 100 * 10, 10)
    
    # 舆情因子
    sentiment_map = {'bullish': 1.0, 'neutral': 0.5, 'bearish': 0.0}
    factors['sentiment'] = sentiment_map.get(sentiment, 0.5)
    
    # Theta因子
    factors['theta'] = calculate_theta(price, iv, days)
    
    return factors

def calculate_theta(price, iv, days):
    """计算Theta"""
    if days <= 0:
        return 0
    T = days / 365
    sigma = iv / 100
    # 简化Theta计算
    theta = price * sigma * np.sqrt(T) * 0.1
    return theta / days

def calculate_score(factors, days):
    """计算综合评分"""
    score = 0
    
    # 安全距离得分 (0-30)
    score += min(factors['safety'] * 3, 30)
    
    # 流动性得分 (0-20)
    score += factors['liquidity'] * 2
    
    # 舆情得分 (0-25)
    score += factors['sentiment'] * 25
    
    # Theta得分 (0-15)
    score += min(factors['theta'] * 15, 15)
    
    # 基础分
    score += 10
    
    return min(score, 100)

# ==================== 策略执行 ====================

def run_strategy(symbol, start_date, end_date):
    """运行回测"""
    print(f"\n{'='*50}")
    print(f"回测 {symbol} {start_date} ~ {end_date}")
    print(f"{'='*50}")
    
    # 模拟每日运行
    trades = []
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    while current_date <= end:
        date_str = current_date.strftime("%Y-%m-%d")
        
        try:
            # 获取数据
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="30d")
            if hist.empty:
                current_date += timedelta(days=1)
                continue
            
            price = hist['Close'].iloc[-1]
            iv = get_iv(symbol)
            
            # 模拟舆情（实际应爬取）
            import random
            sentiments = ['bullish', 'neutral', 'bearish']
            sentiment = random.choice(sentiments)
            
            # 计算评分
            factors = calculate_factors(price, iv, sentiment, 7)
            score = calculate_score(factors, 7)
            
            # 信号：阈值40分
            if score >= 40:
                signal = "BUY"
                trades.append({
                    'date': date_str,
                    'price': price,
                    'iv': iv,
                    'score': score,
                    'signal': signal,
                    'sentiment': sentiment
                })
                print(f"{date_str}: 价格${price:.2f}, IV={iv:.1f}%, 评分={score:.0f} -> BUY")
            
        except Exception as e:
            print(f"错误: {e}")
        
        current_date += timedelta(days=1)
    
    return trades

def save_to_qlib_format(trades, output_path):
    """保存为qlib格式"""
    if not trades:
        print("无交易记录")
        return
    
    df = pd.DataFrame(trades)
    df.to_csv(output_path, index=False)
    print(f"\n已保存到 {output_path}")
    print(df.head())

# ==================== 主程序 ====================

if __name__ == "__main__":
    symbol = "TSLA"
    start = "2026-02-01"
    end = "2026-03-04"
    
    trades = run_strategy(symbol, start, end)
    
    # 保存
    output = f"/root/.openclaw/workspace/quant/TSLA期权策略/{symbol}_backtest.csv"
    save_to_qlib_format(trades, output)
    
    # 统计
    if trades:
        buy_count = sum(1 for t in trades if t['signal'] == "BUY")
        print(f"\n统计: 买入信号 {buy_count} 次")
