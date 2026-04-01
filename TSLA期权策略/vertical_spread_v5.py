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
    
    # 评分逻辑：偏离度越低分数越高
    score = 50 + max(min((20 - deviation) * 2, 25), -25)
    if vix < 15:
        score += 20
    elif vix > 30:
        score -= 20
    elif vix > 20:
        score -= 10
    score = max(0, min(100, score))
    return signal, score

def get_option_price_from_yfinance(ticker, strike, days_to_expiry, option_type="put"):
    """从yfinance获取真实期权价格，如果获取不到返回None"""
    try:
        opts = ticker.option_chain()
        if option_type == "put":
            df = opts.puts
        else:
            df = opts.calls
        
        # 找到最接近的行权价
        df = df[df['strike'] == strike]
        if df.empty:
            return None, "未找到期权"
        
        row = df.iloc[0]
        price = row['lastPrice']
        
        # 如果成交价为0或很小，尝试用bid-ask中间价
        if price <= 0.01 and row['bid'] > 0 and row['ask'] > 0:
            price = (row['bid'] + row['ask']) / 2
        
        if price <= 0.01:
            return None, "无有效价格"
        
        return price, "yfinance成交价"
    except Exception as e:
        return None, f"获取失败:{str(e)[:20]}"

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
    
    # Theta公式（每天）
    if option_type == "put":
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) - 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(-d1 + iv_decimal * math.sqrt(T)) * 0.01
    else:
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) + 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(d1 - iv_decimal * math.sqrt(T)) * 0.01
    
    return theta / 365  # 每日Theta

def calculate_theta_score(theta, premium, days_to_expiry):
    """计算Theta评分（平衡风格）
    - Theta效率 = Theta / sqrt(剩余天数)，标准化短期和长期
    - 权利金占比 = Theta / premium（每权利金赚多少Theta）
    """
    if days_to_expiry <= 0 or premium <= 0 or theta <= 0:
        return 0
    
    # Theta效率：每.sqrt(天)的Theta，平衡短期和长期
    theta_efficiency = theta / math.sqrt(days_to_expiry)
    
    # 权利金效率：Theta占权利金比例
    premium_efficiency = theta / premium * 100
    
    # 综合Theta评分（满分20分）
    # 平衡短期（高Theta但高风险）和长期（低Theta但稳定）
    theta_score = min(theta_efficiency * 500 + premium_efficiency * 2, 20)
    
    return theta_score

def calculate_composite_score(rr_ratio, liquidity_score, safety_distance, params_match, sentiment_score, theta_score=0):
    """综合评分（加入Theta调整）"""
    rr_score = min(rr_ratio / 2.0, 1.0) * 25
    liq_score = min(liquidity_score * 2, 15)
    safety_score = min(safety_distance * 2, 15)
    param_score = params_match * 10
    sentiment_scores = {"bullish": 20, "neutral": 10, "bearish": 0}
    sent_score = sentiment_scores.get(sentiment_score, 10)
    # Theta评分（平衡风格）
    theta_adj = theta_score
    
    total = rr_score + liq_score + safety_score + param_score + sent_score + theta_adj
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

def get_available_expirations(ticker):
    """获取ticker所有可用的到期日（包括周一、周三、周四、周五）"""
    from datetime import datetime, timedelta
    
    expirations = []
    base_date = datetime.now()
    
    # 搜索接下来30天所有的到期日
    for days in range(1, 30):
        date = base_date + timedelta(days=days)
        exp_date = date.strftime('%Y-%m-%d')
        try:
            opts = ticker.option_chain(exp_date)
            if not opts.puts.empty:
                actual_days = (date - base_date).days
                # 跳过周末到期的期权（可能流动性差）
                if date.weekday() in [0, 1, 2, 3, 4]:  # 周一到周五
                    expirations.append({
                        'date': exp_date,
                        'days': actual_days,
                        'options': opts
                    })
        except:
            pass
    
    return expirations

def calculate_strategy_details(price, iv, strategy_type, sentiment, days_to_expiry=7, ticker=None, options_data=None):
    """根据策略类型计算详细参数（含Theta计算）
    优先使用yfinance真实成交价，如果获取不到则用BS模型
    options_data: 直接传入期权数据，避免重复请求
    """
    params = {}
    theta_short = 0
    theta_long = 0
    price_source = "BS模型"  # 默认来源
    
    if strategy_type == "Bull_Put_Spread":
        # 卖高买低（更激进：97%/93%）
        short_ratio = 0.97  # 距现价3%
        long_ratio = 0.93   # 距现价7%
        short_strike = round(price * short_ratio / 2.5) * 2.5
        long_strike = round(price * long_ratio / 2.5) * 2.5
        
        # 计算Theta（卖方-买方）
        theta_short = abs(calculate_theta(price, short_strike, iv, days_to_expiry, "put"))
        theta_long = abs(calculate_theta(price, long_strike, iv, days_to_expiry, "put"))
        
        # 权利金计算：优先使用传入的options_data，其次yfinance，最后BS模型
        if options_data is not None:
            # 直接从传入的期权数据中获取
            puts = options_data.puts
            p_short = puts[puts['strike'] == short_strike]
            p_long = puts[puts['strike'] == long_strike]
            
            if not p_short.empty and not p_long.empty:
                premium_short = p_short.iloc[0]['lastPrice']
                premium_long = p_long.iloc[0]['lastPrice']
                if premium_short > 0 and premium_long > 0:
                    price_source = "yfinance成交价"
                else:
                    premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "put")
                    premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "put")
                    price_source = "BS模型"
            else:
                premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "put")
                premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "put")
                price_source = "BS模型"
        elif ticker is not None:
            premium_short_src, src_short = get_option_price_from_yfinance(ticker, short_strike, days_to_expiry, "put")
            premium_long_src, src_long = get_option_price_from_yfinance(ticker, long_strike, days_to_expiry, "put")
            
            if premium_short_src is not None and premium_long_src is not None:
                premium_short = premium_short_src
                premium_long = premium_long_src
                price_source = "yfinance成交价"
            else:
                premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "put")
                premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "put")
                price_source = "BS模型"
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "put")
            premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "put")
        
        premium = premium_short - premium_long  # 卖出收到权利金 - 买入付出权利金 = 净权利金
        
        params = {
            "short_strike": short_strike,
            "long_strike": long_strike,
            "width": price * (short_ratio - long_ratio),
            "max_profit_estimate": premium,
            "max_loss_estimate": price * (short_ratio - long_ratio) - premium,
            "theta_short": theta_short,
            "theta_long": theta_long,
            "theta": theta_short - theta_long,
            "premium": premium,
            "premium_short": premium_short,
            "premium_long": premium_long,
            "days_to_expiry": days_to_expiry,
            "price_source": price_source
        }
    elif strategy_type == "Bull_Call_Spread":
        # 买低卖高（更激进：93%/97%）
        long_ratio = 0.93   # 距现价7%上涨
        short_ratio = 0.97  # 距现价3%上涨
        short_strike = round(price * short_ratio / 2.5) * 2.5
        long_strike = round(price * long_ratio / 2.5) * 2.5
        
        # 计算Theta
        theta_short = abs(calculate_theta(price, short_strike, iv, days_to_expiry, "call"))
        theta_long = abs(calculate_theta(price, long_strike, iv, days_to_expiry, "call"))
        
        # 权利金计算：优先使用传入的options_data，其次yfinance，最后BS模型
        if options_data is not None:
            calls = options_data.calls
            c_short = calls[calls['strike'] == short_strike]
            c_long = calls[calls['strike'] == long_strike]
            
            if not c_short.empty and not c_long.empty:
                premium_short = c_short.iloc[0]['lastPrice']
                premium_long = c_long.iloc[0]['lastPrice']
                if premium_short > 0 and premium_long > 0:
                    price_source = "yfinance成交价"
                else:
                    premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "call")
                    premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "call")
                    price_source = "BS模型"
            else:
                premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "call")
                premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "call")
                price_source = "BS模型"
        elif ticker is not None:
            premium_short_src, src_short = get_option_price_from_yfinance(ticker, short_strike, days_to_expiry, "call")
            premium_long_src, src_long = get_option_price_from_yfinance(ticker, long_strike, days_to_expiry, "call")
            
            if premium_short_src is not None and premium_long_src is not None:
                premium_short = premium_short_src
                premium_long = premium_long_src
                price_source = "yfinance成交价"
            else:
                premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "call")
                premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "call")
                price_source = "BS模型"
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days_to_expiry, "call")
            premium_long = calculate_option_price(price, long_strike, iv, days_to_expiry, "call")
        
        premium = premium_short - premium_long  # 卖出收到权利金 - 买入付出权利金 = 净权利金
        
        params = {
            "short_strike": short_strike,
            "long_strike": long_strike,
            "width": price * (short_ratio - long_ratio),
            "max_profit_estimate": premium,
            "max_loss_estimate": price * (short_ratio - long_ratio) - premium,
            "theta_short": theta_short,
            "theta_long": theta_long,
            "theta": theta_short - theta_long,  # 卖方 - 买方
            "premium": premium,
            "premium_short": premium_short,
            "premium_long": premium_long,
            "days_to_expiry": days_to_expiry,
            "price_source": price_source
        }
    elif strategy_type == "Iron_Condor":
        params = {
            "put_short": round(price * 0.92 / 2.5) * 2.5,
            "put_long": round(price * 0.88 / 2.5) * 2.5,
            "call_short": round(price * 1.08 / 2.5) * 2.5,
            "call_long": round(price * 1.12 / 2.5) * 2.5,
            "width": price * 0.08,
            "max_profit_estimate": price * 0.015,
            "max_loss_estimate": price * 0.04,
            "theta": 0,
            "days_to_expiry": days_to_expiry
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
        
        # 获取可用到期日
        expirations = get_available_expirations(ticker)
        
        # 选择最近的两个到期日
        best_expiry = None
        next_expiry = None
        if len(expirations) >= 1:
            best_expiry = expirations[0]
        if len(expirations) >= 2:
            next_expiry = expirations[1]
        
        # 计算策略参数（使用第一个可用到期日）
        if best_expiry:
            days_to_expiry = best_expiry['days']
            actual_date = best_expiry['date']
            strategy_params = calculate_strategy_details(price, iv, strategy_type, sentiment, days_to_expiry, ticker, best_expiry['options'])
            strategy_params['actual_expiry_date'] = actual_date
        else:
            days_to_expiry = 7
            strategy_params = calculate_strategy_details(price, iv, strategy_type, sentiment, days_to_expiry, ticker)
            strategy_params['actual_expiry_date'] = "未知"
        
        # 计算Theta评分（平衡风格）
        theta = strategy_params.get('theta', 0)
        premium = strategy_params.get('premium', price * 0.02)
        theta_score = calculate_theta_score(theta, premium, days_to_expiry)
        
        # 计算综合评分（加入Theta）
        composite_score = calculate_composite_score(
            spread_data['rr_ratio'],
            spread_data['liquidity'],
            spread_data['safety_distance'],
            spread_data['params_match'],
            sentiment,
            theta_score
        )
        
        # 决策
        if strategy_type == "None":
            decision = "🔴禁止"
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

# ==================== 多到期日扫描 ====================
EXPIRY_DAYS = [3, 7, 14]  # 扫描的到期日列表

def scan_multi_expiry(symbol, vix, vix_ma, deviation, vix_signal):
    """扫描多个到期日，选出最优组合"""
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
        
        # 获取可用到期日
        expirations = get_available_expirations(ticker)
        
        # 获取初始评分因子
        spread_data = {
            'rr_ratio': 1.0,
            'liquidity': 10,
            'safety_distance': 15,
            'params_match': 0.7
        }
        
        # 初始综合评分（不含Theta）
        base_score = calculate_composite_score(
            spread_data['rr_ratio'],
            spread_data['liquidity'],
            spread_data['safety_distance'],
            spread_data['params_match'],
            sentiment
        )
        
        # 推荐策略类型
        strategy_type, strategy_desc = recommend_strategy_type(vix_signal, sentiment, iv, base_score)
        
        if strategy_type == "None":
            return None
        
        # 扫描多个到期日，返回所有组合（用于备选）
        all_combos = []
        
        # 使用实际获取的到期日
        for exp in expirations:
            days = exp['days']
            exp_date = exp['date']
            options_data = exp['options']
            
            params = calculate_strategy_details(price, iv, strategy_type, sentiment, days, ticker, options_data)
            params['actual_expiry_date'] = exp_date
            theta = params.get('theta', 0)
            premium = params.get('premium', price * 0.02)
            
            # 计算Theta评分
            theta_score = calculate_theta_score(theta, premium, days)
            
            # 计算资金效率（Theta / 权利金）
            capital_efficiency = theta / premium * 100 if premium > 0 else 0
            
            # 计算综合评分（加入Theta和资金效率）
            composite_score = calculate_composite_score(
                spread_data['rr_ratio'],
                spread_data['liquidity'],
                spread_data['safety_distance'],
                spread_data['params_match'],
                sentiment,
                theta_score
            )
            
            # 计算平衡得分
            balance_score = theta * 50 + capital_efficiency * 0.5
            
            combo = {
                'symbol': symbol,
                'price': price,
                'iv': iv,
                'vix': vix,
                'vix_signal': vix_signal,
                'sentiment': sentiment,
                'sentiment_ratio': sent_ratio,
                'composite_score': composite_score,
                'balance_score': balance_score,
                'strategy_type': strategy_type,
                'strategy_desc': strategy_desc,
                'days_to_expiry': days,
                'theta': theta,
                'premium': premium,
                'capital_efficiency': capital_efficiency,
                'strategy_params': params
            }
            all_combos.append(combo)
        
        # 按综合评分排序
        all_combos.sort(key=lambda x: x['composite_score'], reverse=True)
        
        # 选择最优组合
        best_combo = all_combos[0] if all_combos else None
        
        # 为每个组合添加决策
        for combo in all_combos:
            if combo['composite_score'] >= 30:
                combo['decision'] = "🟡试探"
                combo['position'] = int(combo['composite_score'] * 0.6)
            else:
                combo['decision'] = "🔴禁止"
                combo['position'] = 0
        
        return best_combo, all_combos  # 返回最优和全部
        
    except Exception as e:
        print(f"   ⚠️ {symbol}: {e}")
        return None, []

# ==================== 主程序 ====================
print("="*80)
print("🚀 垂直价差策略 V6 (多到期日扫描)")
print("="*80)
print(f"📊 扫描到期日: {EXPIRY_DAYS}天内")

vix, vix_ma, deviation = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")

results = []
all_options = {}  # 存储所有标的的所有选项
print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")

for sym in STOCKS:
    best_data, all_data = scan_multi_expiry(sym, vix, vix_ma, deviation, vix_signal)
    if best_data:
        results.append(best_data)
        all_options[sym] = all_data  # 保存所有选项
        
        print(f"{best_data['decision']} {sym:5s} \${best_data['price']:7.2f} "
              f"IV:{best_data['iv']:5.1f}% 评分:{best_data['composite_score']:3.0f} "
              f"{best_data['strategy_desc']} 到期:{best_data['days_to_expiry']}天")

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
            expiry_date = sp.get('actual_expiry_date', f"{r['days_to_expiry']}天后")
            print(f"      到期日: {expiry_date}")
            print(f"      Theta: ${r.get('theta', 0):.3f}/天")
            src = sp.get('price_source', '')
            print(f"      权利金: ${r.get('premium', 0):.2f} ({src})")
            print(f"      资金效率: {r.get('capital_efficiency', 0):.2f}%")
        elif r['strategy_type'] == "Bull_Call_Spread":
            print(f"\n   📌 Bull Call Spread (牛市看涨价差)")
            print(f"      买进行权价: ${sp.get('long_strike', 'N/A')}")
            print(f"      卖出行权价: ${sp.get('short_strike', 'N/A')}")
            print(f"      价差宽度: ${sp.get('width', 'N/A'):.2f}")
            expiry_date = sp.get('actual_expiry_date', f"{r['days_to_expiry']}天后")
            print(f"      到期日: {expiry_date}")
            print(f"      Theta: ${r.get('theta', 0):.3f}/天")
            src = sp.get('price_source', '')
            print(f"      权利金: ${r.get('premium', 0):.2f} ({src})")
            print(f"      资金效率: {r.get('capital_efficiency', 0):.2f}%")
        elif r['strategy_type'] == "Iron_Condor":
            print(f"\n   📌 Iron Condor (铁鹰价差)")
            print(f"      Put卖: ${sp.get('put_short', 'N/A')} | Put买: ${sp.get('put_long', 'N/A')}")
            print(f"      Call卖: ${sp.get('call_short', 'N/A')} | Call买: ${sp.get('call_long', 'N/A')}")
            expiry_date = sp.get('actual_expiry_date', f"{r['days_to_expiry']}天后")
            print(f"      到期日: {expiry_date}")
        
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

# ==================== 显示TSLA所有备选方案 ====================
print("\n" + "="*80)
print("📋 TSLA 备选方案 (3/7/14天)")
print("="*80)

if 'TSLA' in all_options:
    for i, r in enumerate(all_options['TSLA'], 1):
        print(f"\n{'='*50}")
        print(f"🥇 方案{i}: {r['strategy_desc']} - {r['days_to_expiry']}天到期")
        print(f"{'='*50}")
        sp = r['strategy_params']
        print(f"   综合评分: {r['composite_score']:.0f}/100")
        
        if r['strategy_type'] == "Bull_Put_Spread":
            print(f"   卖出行权价: ${sp.get('short_strike', 'N/A')}")
            print(f"   买进行权价: ${sp.get('long_strike', 'N/A')}")
            print(f"   价差宽度: ${sp.get('width', 'N/A'):.2f}")
            print(f"   预计最大盈利: ${sp.get('max_profit_estimate', 'N/A'):.2f}")
            print(f"   预计最大亏损: ${sp.get('max_loss_estimate', 'N/A'):.2f}")
        else:
            print(f"   买进行权价: ${sp.get('long_strike', 'N/A')}")
            print(f"   卖出行权价: ${sp.get('short_strike', 'N/A')}")
            print(f"   价差宽度: ${sp.get('width', 'N/A'):.2f}")
        
        print(f"   Theta: ${r.get('theta', 0):.3f}/天")
        print(f"   权利金: ${r.get('premium', 0):.2f}")
        print(f"   资金效率: {r.get('capital_efficiency', 0):.2f}%")
        print(f"   建议仓位: {r['position']}%")
