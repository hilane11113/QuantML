#!/usr/bin/env python3
"""
OptionAgent - 技术指标代理
"""

import os
import warnings
import requests
import json
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'

import yfinance as yf
import pandas as pd
import numpy as np

def get_stock_data(symbol, period='3mo'):
    """获取股票数据，支持重试和备用源"""
    # 清除代理环境变量让 yfinance 自己处理
    for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
        os.environ.pop(var, None)

    # 一次失败直接返回，不重试（避免触发 yfinance 限流）
    try:
        stock = yf.Ticker(symbol)
        df = stock.history(period=period)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    return pd.DataFrame()


def calculate_ma(df, window):
    """移动平均线"""
    return df['Close'].rolling(window=window).mean()

def calculate_rsi(df, period=14):
    """RSI 相对强弱指标"""
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(df, fast=12, slow=26, signal=9):
    """MACD 指数平滑异同移动平均线"""
    ema_fast = df['Close'].ewm(span=fast).mean()
    ema_slow = df['Close'].ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram

def calculate_bollinger_bands(df, window=20, num_std=2):
    """布林带"""
    ma = df['Close'].rolling(window=window).mean()
    std = df['Close'].rolling(window=window).std()
    upper = ma + (std * num_std)
    lower = ma - (std * num_std)
    return upper, ma, lower

def calculate_volatility(df, period=20):
    """波动率"""
    returns = df['Close'].pct_change()
    volatility = returns.rolling(window=period).std() * np.sqrt(252)
    return volatility


def find_support_resistance(df, lookback=20):
    """
    基于最近 lookback 根 K 线找出支撑和阻力位。
    支撑 = 最近 N 根 K 线的局部最低价区域
    阻力 = 最近 N 根 K 线的局部最高价区域
    返回: (support, resistance)
    """
    if len(df) < lookback:
        return None, None
    recent = df.tail(lookback)
    # 最近20日最低价作为支撑
    support = round(recent['Low'].min(), 2)
    # 最近20日最高价作为阻力
    resistance = round(recent['High'].max(), 2)
    return support, resistance

class TechnicalAgent:
    """技术分析代理"""
    
    def __init__(self):
        self.name = "TechnicalAgent"
    
    def analyze_with_context(self, symbol='TSLA', ctx=None):
        """
        使用统一数据上下文执行技术分析。
        不独立访问 yfinance，所有数据来自 ctx['history'] 和 ctx['price']。
        """
        if ctx is None:
            return self.analyze(symbol)

        df = ctx.get('history')
        price = ctx.get('price')

        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 5:
            return {
                'symbol': symbol,
                'price': round(price, 2) if price else None,
                'trend': '数据不足，无法判断',
                'ma5': None, 'ma20': None, 'ma60': None,
                'rsi': None, 'rsi_signal': '数据不足',
                'macd': None, 'macd_signal': '数据不足',
                'bollinger': None, 'volatility': None,
            }

        if price is None:
            price = float(df['Close'].iloc[-1])
        
        # 计算指标
        ma5 = calculate_ma(df, 5)
        ma20 = calculate_ma(df, 20)
        ma60 = calculate_ma(df, 60)
        rsi = calculate_rsi(df)
        macd, signal_line, histogram = calculate_macd(df)
        upper, middle, lower = calculate_bollinger_bands(df)
        volatility = calculate_volatility(df)
        
        current_price = df['Close'].iloc[-1]
        
        # 趋势判断
        trend = "震荡"
        if ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
            trend = "上涨"
        elif ma5.iloc[-1] < ma20.iloc[-1] < ma60.iloc[-1]:
            trend = "下跌"
        
        # RSI 判断
        rsi_val = rsi.iloc[-1]
        rsi_signal = "超买" if rsi_val > 70 else "超卖" if rsi_val < 30 else "中性"
        
        # MACD 判断
        macd_signal = "金叉" if macd.iloc[-1] > signal_line.iloc[-1] else "死叉"
        
        # 布林带位置
        if current_price > upper.iloc[-1]:
            bb_signal = "突破上轨"
        elif current_price < lower.iloc[-1]:
            bb_signal = "突破下轨"
        else:
            bb_signal = "区间内"
        
        return {
            'symbol': symbol,
            'price': round(current_price, 2),
            'trend': trend,
            'ma5': round(ma5.iloc[-1], 2),
            'ma20': round(ma20.iloc[-1], 2),
            'ma60': round(ma60.iloc[-1], 2) if len(df) >= 60 else None,
            'rsi': round(rsi_val, 2),
            'rsi_signal': rsi_signal,
            'macd': round(macd.iloc[-1], 2),
            'macd_signal': macd_signal,
            'bollinger': {
                'upper': round(upper.iloc[-1], 2),
                'middle': round(middle.iloc[-1], 2),
                'lower': round(lower.iloc[-1], 2),
                'signal': bb_signal
            },
            'volatility': round(volatility.iloc[-1] * 100, 2) if not pd.isna(volatility.iloc[-1]) else None
        }
    
    def analyze(self, symbol='TSLA'):
        """兼容旧接口：从 market_data 拿数据（保留降级路径）"""
        try:
            import market_data
            for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
                os.environ.pop(var, None)
            mkt = market_data.get_market_data(symbol, fetch_technicals=True)
            df = mkt.get('history')
            price = mkt.get('price')
            rsi_val = mkt.get('rsi')
            macd_val = mkt.get('macd')
        except Exception:
            df = None
            price = None
            rsi_val = None
            macd_val = None

        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 5:
            df_fallback = get_stock_data(symbol)
            if df_fallback is not None and not df_fallback.empty and len(df_fallback) >= 5:
                df = df_fallback
        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 5:
            if price is not None:
                return {
                    'symbol': symbol, 'price': round(price, 2),
                    'trend': '数据不足，无法判断', 'ma5': None, 'ma20': None, 'ma60': None,
                    'rsi': round(rsi_val, 2) if rsi_val else None,
                    'rsi_signal': '中性', 'macd': round(macd_val, 4) if macd_val else None,
                    'macd_signal': '数据不足', 'bollinger': None, 'volatility': None,
                }
            return {'error': '数据不足'}

        if price is None:
            price = float(df['Close'].iloc[-1])
        return self._compute_indicators(symbol, df, price)

    def _compute_indicators(self, symbol, df, price):
        """给定历史数据，计算所有技术指标"""
        ma5 = calculate_ma(df, 5)
        ma20 = calculate_ma(df, 20)
        ma60 = calculate_ma(df, 60)
        rsi = calculate_rsi(df)
        macd, signal_line, histogram = calculate_macd(df)
        upper, middle, lower = calculate_bollinger_bands(df)
        volatility = calculate_volatility(df)
        support, resistance = find_support_resistance(df)
        current_price = df['Close'].iloc[-1]

        trend = "震荡"
        if ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
            trend = "上涨"
        elif ma5.iloc[-1] < ma20.iloc[-1] < ma60.iloc[-1]:
            trend = "下跌"

        rsi_val = rsi.iloc[-1]
        rsi_signal = "超买" if rsi_val > 70 else "超卖" if rsi_val < 30 else "中性"
        macd_signal = "金叉" if macd.iloc[-1] > signal_line.iloc[-1] else "死叉"
        if current_price > upper.iloc[-1]:
            bb_signal = "突破上轨"
        elif current_price < lower.iloc[-1]:
            bb_signal = "突破下轨"
        else:
            bb_signal = "区间内"

        return {
            'symbol': symbol, 'price': round(current_price, 2), 'trend': trend,
            'ma5': round(ma5.iloc[-1], 2), 'ma20': round(ma20.iloc[-1], 2),
            'ma60': round(ma60.iloc[-1], 2) if len(df) >= 60 else None,
            'rsi': round(rsi_val, 2), 'rsi_signal': rsi_signal,
            'macd': round(macd.iloc[-1], 2), 'macd_signal': macd_signal,
            'bollinger': {
                'upper': round(upper.iloc[-1], 2),
                'middle': round(middle.iloc[-1], 2),
                'lower': round(lower.iloc[-1], 2),
                'signal': bb_signal
            },
            'volatility': round(volatility.iloc[-1] * 100, 2) if not pd.isna(volatility.iloc[-1]) else None,
            'support': support, 'resistance': resistance,
        }

    def analyze_with_context(self, symbol='TSLA', ctx=None):
        """
        使用统一数据上下文执行技术分析。
        不独立访问 yfinance，数据全来自 ctx['history'] 和 ctx['price']。
        """
        if ctx is None:
            return self.analyze(symbol)

        df = ctx.get('history')
        price = ctx.get('price')

        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 5:
            return {
                'symbol': symbol, 'price': round(price, 2) if price else None,
                'trend': '数据不足，无法判断', 'ma5': None, 'ma20': None, 'ma60': None,
                'rsi': None, 'rsi_signal': '数据不足',
                'macd': None, 'macd_signal': '数据不足',
                'bollinger': None, 'volatility': None,
            }

        if price is None:
            price = float(df['Close'].iloc[-1])
        return self._compute_indicators(symbol, df, price)

    def run(self, symbol='TSLA'):
        return self.analyze(symbol)

if __name__ == "__main__":
    agent = TechnicalAgent()
    result = agent.run('TSLA')
    
    print(f"📈 技术分析 - {result['symbol']}")
    print(f"  价格: ${result['price']}")
    print(f"  趋势: {result['trend']}")
    print(f"  MA5: {result['ma5']} | MA20: {result['ma20']}")
    print(f"  RSI: {result['rsi']} ({result['rsi_signal']})")
    print(f"  MACD: {result['macd']} ({result['macd_signal']})")
    print(f"  布林带: {result['bollinger']['signal']}")
    if result['volatility']:
        print(f"  波动率: {result['volatility']}%")
