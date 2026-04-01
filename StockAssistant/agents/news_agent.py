#!/usr/bin/env python3
"""
OptionAgent - 新闻代理
类似于 TradingAgents 的 News Analyst
"""

import os
import json
import subprocess
import requests
from datetime import datetime
from config import PROXY, NEWS_API, FINNHUB_KEY

# 财经新闻源
SOURCES = {
    'wallstreetcn': '华尔街见闻',
    'cls': '财联社',
    'gelonghui': '格隆汇',
    'jin10': '金十数据',
}

def fetch_news_api(source=None, max_items=20):
    """通过本地API获取新闻"""
    results = []
    sources_to_fetch = [source] if source else SOURCES.keys()
    
    for src in sources_to_fetch:
        try:
            result = subprocess.run(
                ['curl', '-s', f'{NEWS_API}?id={src}'],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            items = data.get('items', [])[:max_items]
            for item in items:
                item['source_name'] = SOURCES.get(src, src)
            results.extend(items)
        except:
            pass
    
    return results

def fetch_finnhub_news(symbol='AAPL', days=1):
    """获取Finnhub美股新闻"""
    from datetime import datetime, timedelta
    
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        url = f"https://finnhub.io/api/v1/company-news"
        params = {
            'symbol': symbol,
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d'),
            'token': FINNHUB_KEY
        }
        
        response = requests.get(url, params=params, proxies={
            'http': PROXY, 'https': PROXY
        }, timeout=15)
        
        if response.status_code == 200:
            articles = response.json()
            return [{
                'title': a.get('headline', ''),
                'source': 'Finnhub',
                'datetime': a.get('datetime', '')
            } for a in articles[:10]]
    except:
        pass
    
    return []

def analyze_topics(news_items):
    """分析热点话题"""
    topics = {}
    
    keywords_map = {
        '中东局势': ['伊朗', '以色列', '中东', '红海', '沙特', '石油', '原油'],
        'A股': ['A股', '上证', '深证', '创业板'],
        '港股': ['港股', '恒生', '台股'],
        '美股': ['美股', '纳斯达克', '标普'],
        '央行': ['央行', '美联储', '加息', '降息'],
        '黄金': ['黄金', '金价', '有色'],
        '能源': ['天然气', '能源', 'OPEC'],
        'AI科技': ['AI', '芯片', '英伟达', '科技'],
        '新能源车': ['新能源车', '电动车', '特斯拉'],
    }
    
    for item in news_items:
        title = item.get('title', '')
        for topic, keywords in keywords_map.items():
            if any(k in title for k in keywords):
                if topic not in topics:
                    topics[topic] = {'count': 0, 'items': []}
                topics[topic]['count'] += 1
                topics[topic]['items'].append(title[:50])
                break
    
    return topics

def generate_sentiment(topics):
    """生成市场情绪"""
    sentiments = []
    if '中东局势' in topics:
        sentiments.append("避险情绪升温")
    if 'A股' in topics:
        sentiments.append("A股关注度高")
    if '央行' in topics:
        sentiments.append("关注央行政策")
    return sentiments if sentiments else ["市场观望"]

class NewsAgent:
    """新闻代理"""
    
    def __init__(self):
        self.name = "NewsAgent"
    
    def run(self, symbol=None):
        """执行新闻分析"""
        # 获取新闻
        news_items = fetch_news_api()
        
        # 如果API获取失败，使用Finnhub
        if len(news_items) < 5:
            if symbol:
                news_items.extend(fetch_finnhub_news(symbol))
            else:
                for s in ['AAPL', 'TSLA', 'NVDA']:
                    news_items.extend(fetch_finnhub_news(s))
        
        # 分析话题
        topics = analyze_topics(news_items)
        sentiment = generate_sentiment(topics)
        
        return {
            'news_count': len(news_items),
            'topics': topics,
            'sentiment': sentiment,
            'news_items': news_items[:10]
        }

if __name__ == "__main__":
    agent = NewsAgent()
    result = agent.run('TSLA')
    print(json.dumps(result, indent=2, ensure_ascii=False))
