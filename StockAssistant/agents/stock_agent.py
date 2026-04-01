#!/usr/bin/env python3
"""
OptionAgent - 个股分析代理
独立于期权推荐的股票分析模块
"""

import os
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'

import yfinance as yf
import requests
import json
from datetime import datetime

# Finnhub API
FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'

def get_stock_info(symbol):
    """获取股票基本信息"""
    stock = yf.Ticker(symbol)
    info = stock.info
    
    return {
        'name': info.get('longName', info.get('shortName', symbol)),
        'sector': info.get('sector', 'N/A'),
        'industry': info.get('industry', 'N/A'),
        'market_cap': info.get('marketCap', 0),
        'pe_ratio': info.get('trailingPE', 0),
        'eps': info.get('trailingEps', 0),
        'dividend_yield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0,
        'beta': info.get('beta', 0),
        '52w_high': info.get('fiftyTwoWeekHigh', 0),
        '52w_low': info.get('fiftyTwoWeekLow', 0),
        'volume': info.get('volume', 0),
        'avg_volume': info.get('averageVolume', 0),
    }

def get_recommendations(symbol):
    """获取分析师评级"""
    stock = yf.Ticker(symbol)
    try:
        recs = stock.recommendations
        if recs is not None and not recs.empty:
            latest = recs.iloc[-1]
            return {
                'firm': latest.get('Firm', 'N/A'),
                'to_grade': latest.get('To Grade', 'N/A'),
                'from_grade': latest.get('From Grade', 'N/A'),
                'date': str(latest.name)[:10] if latest.name else 'N/A'
            }
    except:
        pass
    return {}

def get_price_targets(symbol):
    """获取价格目标"""
    stock = yf.Ticker(symbol)
    info = stock.info
    
    return {
        'current': info.get('currentPrice', 0),
        'target_low': info.get('targetLowPrice', 0),
        'target_mean': info.get('targetMeanPrice', 0),
        'target_high': info.get('targetHighPrice', 0),
    }

def get_analyst_sentiment(symbol):
    """获取分析师情绪"""
    targets = get_price_targets(symbol)
    recs = get_recommendations(symbol)
    
    current = targets.get('current', 0)
    target = targets.get('target_mean', 0)
    
    if current > 0 and target > 0:
        upside = (target - current) / current * 100
        if upside > 20:
            sentiment = '强烈看涨'
        elif upside > 10:
            sentiment = '看涨'
        elif upside > -10:
            sentiment = '中性'
        elif upside > -20:
            sentiment = '看跌'
        else:
            sentiment = '强烈看跌'
    else:
        sentiment = '未知'
        upside = 0
    
    return {
        'sentiment': sentiment,
        'upside': round(upside, 1) if upside else 0,
        'grade': recs.get('to_grade', 'N/A')
    }

def get_technical_summary(symbol):
    """技术面总结"""
    import pandas as pd
    import numpy as np
    
    stock = yf.Ticker(symbol)
    df = stock.history(period='3mo')
    
    if df.empty or len(df) < 20:
        return {'error': '数据不足'}
    
    # 均线
    ma5 = df['Close'].rolling(5).mean().iloc[-1]
    ma20 = df['Close'].rolling(20).mean().iloc[-1]
    ma60 = df['Close'].rolling(60).mean().iloc[-1] if len(df) >= 60 else ma20
    
    current = df['Close'].iloc[-1]
    
    # 趋势
    if current > ma20 > ma60:
        trend = '上涨趋势'
    elif current < ma20 < ma60:
        trend = '下跌趋势'
    else:
        trend = '震荡'
    
    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    
    # 支撑/阻力
    support = df['Low'].rolling(20).min().iloc[-1]
    resistance = df['High'].rolling(20).max().iloc[-1]
    
    return {
        'price': round(current, 2),
        'ma5': round(ma5, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
        'trend': trend,
        'rsi': round(rsi, 2),
        'support': round(support, 2),
        'resistance': round(resistance, 2),
    }

def get_news_sentiment(symbol):
    """新闻情绪"""
    try:
        url = f"https://finnhub.io/api/v1/company-news"
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=7)
        
        params = {
            'symbol': symbol,
            'from': start.strftime('%Y-%m-%d'),
            'to': end.strftime('%Y-%m-%d'),
            'token': FINNHUB_KEY
        }
        
        response = requests.get(url, params=params, 
                              proxies={'http': PROXY, 'https': PROXY}, timeout=10)
        
        if response.status_code == 200:
            articles = response.json()
            
            bullish = sum(1 for a in articles if any(k in a.get('headline','').lower() 
                for k in ['beat', 'gain', 'surge', 'rise', 'growth', 'bullish']))
            bearish = sum(1 for a in articles if any(k in a.get('headline','').lower() 
                for k in ['miss', 'drop', 'fall', 'decline', 'bearish', 'warn']))
            
            if bullish > bearish:
                sentiment = '看涨'
            elif bearish > bullish:
                sentiment = '看跌'
            else:
                sentiment = '中性'
            
            return {'sentiment': sentiment, 'count': len(articles)}
    except:
        pass
    return {'sentiment': '未知', 'count': 0}

def generate_recommendation(info, tech, analyst, news):
    """生成综合建议"""
    score = 0
    
    # 技术面
    if tech.get('trend') == '上涨趋势':
        score += 2
    elif tech.get('trend') == '下跌趋势':
        score -= 2
    
    if tech.get('rsi', 50) < 30:
        score += 1  # 超卖
    elif tech.get('rsi', 50) > 70:
        score -= 1  # 超买
    
    # 分析师
    sentiment = analyst.get('sentiment', '')
    if '涨' in sentiment:
        score += 2
    elif '跌' in sentiment:
        score -= 2
    
    # 新闻
    if news.get('sentiment') == '看涨':
        score += 1
    elif news.get('sentiment') == '看跌':
        score -= 1
    
    # 生成建议
    if score >= 3:
        recommendation = '强烈推荐买入'
    elif score >= 1:
        recommendation = '建议买入'
    elif score >= -1:
        recommendation = '持有观望'
    elif score >= -3:
        recommendation = '建议减仓'
    else:
        recommendation = '建议卖出'
    
    return recommendation, score

class StockAgent:
    """个股分析代理"""
    
    def __init__(self):
        self.name = "StockAgent"
    
    def analyze(self, symbol='TSLA'):
        """执行个股分析"""
        
        # 获取各类数据
        info = get_stock_info(symbol)
        analyst = get_analyst_sentiment(symbol)
        tech = get_technical_summary(symbol)
        news = get_news_sentiment(symbol)
        
        # 生成建议
        recommendation, score = generate_recommendation(info, tech, analyst, news)
        
        return {
            'symbol': symbol,
            'name': info.get('name', symbol),
            'sector': info.get('sector', 'N/A'),
            'info': info,
            'analyst': analyst,
            'technical': tech,
            'news': news,
            'recommendation': recommendation,
            'score': score
        }
    
    def run(self, symbol='TSLA'):
        return self.analyze(symbol)

if __name__ == "__main__":
    agent = StockAgent()
    result = agent.run('TSLA')
    
    print(f"\n📊 个股分析 - {result['symbol']} ({result['name']})")
    print(f"   行业: {result['sector']}")
    print(f"\n💰 基本面")
    print(f"   市值: ${result['info'].get('market_cap', 0):,.0f}" if result['info'].get('market_cap') else "   市值: N/A")
    print(f"   PE: {result['info'].get('pe_ratio', 'N/A')}")
    print(f"   52周: ${result['info'].get('52w_low', 0)} - ${result['info'].get('52w_high', 0)}")
    
    print(f"\n📈 技术面")
    tech = result['technical']
    if 'error' not in tech:
        print(f"   价格: ${tech.get('price', 0)}")
        print(f"   趋势: {tech.get('trend', 'N/A')}")
        print(f"   RSI: {tech.get('rsi', 0)}")
        print(f"   支撑: ${tech.get('support', 0)} | 阻力: ${tech.get('resistance', 0)}")
    
    print(f"\n🎯 分析师")
    analyst = result['analyst']
    print(f"   情绪: {analyst.get('sentiment', 'N/A')}")
    print(f"   上涨空间: {analyst.get('upside', 0)}%")
    print(f"   评级: {analyst.get('grade', 'N/A')}")
    
    print(f"\n📰 新闻: {result['news'].get('sentiment', 'N/A')}")
    
    print(f"\n✅ 综合建议: {result['recommendation']} (评分: {result['score']})")
