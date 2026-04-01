#!/usr/bin/env python3
"""
OptionAgent - 社交媒体情绪代理
使用 Finnhub + yFinance 新闻
"""

import requests
import json
import os

# 代理配置
PROXY = 'http://127.0.0.1:7897'
PROXIES = {'http': PROXY, 'https': PROXY}

# Finnhub API
FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'

def fetch_apewisdom_sentiment(symbol='TSLA'):
    """获取 apewisdom Reddit 舆情数据"""
    try:
        url = "https://apewisdom.io/api/v1.0/filter/all-stocks"
        resp = requests.get(url, proxies=PROXIES, timeout=10)
        data = resp.json()
        for item in data.get('results', []):
            if item.get('ticker', '').upper() == symbol.upper():
                mentions = int(item.get('mentions', 0))
                upvotes = int(item.get('upvotes', 0))
                rank = int(item.get('rank', 999))
                rank_24h = int(item.get('rank_24h_ago', 999))
                mentions_24h = int(item.get('mentions_24h_ago', 0)) if item.get('mentions_24h_ago') else 0
                rank_change = rank_24h - rank
                mentions_change = mentions - mentions_24h
                sentiment_ratio = upvotes / mentions if mentions > 0 else 0
                # 情绪评分
                if sentiment_ratio > 10:
                    ape_sentiment = 'bullish'
                elif sentiment_ratio < 5:
                    ape_sentiment = 'bearish'
                else:
                    ape_sentiment = 'neutral'
                return {
                    'mentions': mentions,
                    'upvotes': upvotes,
                    'rank': rank,
                    'rank_change': rank_change,
                    'mentions_change': mentions_change,
                    'sentiment': ape_sentiment,
                    'sentiment_ratio': round(sentiment_ratio, 2)
                }
    except:
        pass
    return {}

def fetch_finnhub_sentiment(symbol='TSLA'):
    """获取Finnhub社交情绪"""
    try:
        url = f"https://finnhub.io/api/v1/stock/social-sentiment"
        params = {'symbol': symbol, 'token': FINNHUB_KEY}
        
        response = requests.get(url, params=params, proxies=PROXIES, timeout=8)
        
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}

def fetch_yfinance_news(symbol='TSLA'):
    """使用yFinance获取新闻作为舆论参考"""
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        news = stock.news
        
        if news:
            return [{'title': n.get('title', ''), 'publisher': n.get('publisher', '')} for n in news[:5]]
    except:
        pass
    return []

def fetch_finnhub_news(symbol='TSLA'):
    """获取Finnhub公司新闻"""
    try:
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=3)
        
        url = f"https://finnhub.io/api/v1/company-news"
        params = {
            'symbol': symbol,
            'from': start.strftime('%Y-%m-%d'),
            'to': end.strftime('%Y-%m-%d'),
            'token': FINNHUB_KEY
        }
        
        response = requests.get(url, params=params, proxies=PROXIES, timeout=8)
        
        if response.status_code == 200:
            articles = response.json()
            return [{'title': a.get('headline', ''), 'source': a.get('source', '')} for a in articles[:5]]
    except:
        pass
    return []

def call_minimax_llm(prompt, system_prompt="你是一个专业的金融舆情分析助手"):
    """调用 MiniMax LLM API"""
    try:
        from config import MINIMAX_API_KEY, MINIMAX_BASE_URL
        url = f"{MINIMAX_BASE_URL}/text/chatcompletion_v2"
        headers = {
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "MiniMax-Text-01",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 200
        }
        resp = requests.post(url, json=payload, headers=headers, proxies=PROXIES, timeout=8)
        result = resp.json()
        if 'choices' in result and result['choices']:
            return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"LLM调用失败: {e}", flush=True)
    return ""

def analyze_sentiment_llm(news_list):
    """使用 LLM 分析新闻情绪"""
    if not news_list:
        return 'neutral', 50, ""
    
    titles = [n.get('title', '') for n in news_list if n.get('title')]
    if not titles:
        return 'neutral', 50, ""
    
    news_text = "\n".join([f"- {t}" for t in titles[:8]])
    
    prompt = f"""请分析以下新闻标题的总体情绪，判断是"看涨(bullish)"、"看跌(bearish)"还是"中性(neutral)"。

新闻标题：
{news_text}

请直接回复，格式如下（只输出这一行）：
情绪: 看涨/看跌/中性
评分: 0~100（看涨越高分，看跌越低分，中性50分）
理由: 一句话说明原因"""

    response = call_minimax_llm(prompt, "你是一个专业的金融舆情分析助手，擅长判断新闻对股价的影响。")
    
    sentiment = 'neutral'
    score = 50
    
    if response:
        import re
        s_match = re.search(r'情绪[：:]\s*(看涨|看跌|中性|bullish|bearish|neutral)', response)
        sc_match = re.search(r'评分[：:]\s*(\d+)', response)
        
        if s_match:
            s = s_match.group(1)
            if s in ['看涨', 'bullish']:
                sentiment = 'bullish'
            elif s in ['看跌', 'bearish']:
                sentiment = 'bearish'
            else:
                sentiment = 'neutral'
        
        if sc_match:
            score = int(sc_match.group(1))
    
    return sentiment, score, response

def analyze_sentiment(news_list):
    """分析新闻情绪（使用词边界匹配避免误匹配）"""
    import re
    if not news_list:
        return 'neutral', 0

    bullish_keywords = ['bullish', 'upgrade', 'buy', 'gain', 'rise', 'soar', 'growth', 'beat', 'surge']
    bearish_keywords = ['bearish', 'downgrade', 'sell', 'drop', 'fall', 'decline', 'cut', 'warning', 'plunge']

    bullish = 0
    bearish = 0

    for news in news_list:
        title = str(news.get('title', '')).lower()

        bull_hit = any(re.search(r'\b' + re.escape(k) + r'\b', title) for k in bullish_keywords)
        bear_hit = any(re.search(r'\b' + re.escape(k) + r'\b', title) for k in bearish_keywords)

        if bull_hit:
            bullish += 1
        elif bear_hit:
            bearish += 1

    total = bullish + bearish
    if total == 0:
        return 'neutral', 0

    score = (bullish - bearish) / total

    if score > 0.3:
        return 'bullish', round(score, 2)
    elif score < -0.3:
        return 'bearish', round(score, 2)
    return 'neutral', round(score, 2)


def calculate_composite_sentiment(keyword_sent, keyword_score, llm_sent, llm_score, ape_sent, ape_ratio):
    """
    将三个情绪指标合并为一个综合评分（0-100）。
    - keyword_sent: bullish/neutral/bearish
    - keyword_score: -1~1 → 归一化到0-100
    - llm_score: 0-100
    - ape_sent: bullish/neutral/bearish
    - ape_ratio: upvotes/mentions
    返回: (composite_score, composite_label, detail_dict)
    """
    scores = []

    # 1. 关键词情绪 → 0-100
    kw_norm = (keyword_score + 1) * 50  # -1→0, 0→50, 1→100
    scores.append(kw_norm)

    # 2. LLM 情绪 → 0-100（直接使用，范围0-100）
    if llm_score > 0:
        scores.append(llm_score)

    # 3. apewisdom → 0-100
    if ape_sent == 'bullish':
        scores.append(65)
    elif ape_sent == 'bearish':
        scores.append(35)
    else:
        scores.append(50)

    composite = round(sum(scores) / len(scores), 1) if scores else 50

    # 综合标签
    if composite >= 58:
        label = '🟢 多头'
    elif composite <= 42:
        label = '🔴 空头'
    else:
        label = '🟡 中性'

    detail = {
        'keyword': f"{keyword_sent} ({keyword_score:+.2f})",
        'llm': f"{llm_sent} ({llm_score})",
        'apewisdom': f"{ape_sent} (ratio={ape_ratio:.1f})",
        'composite': f"{label} ({composite}/100)",
        'composite_score': composite,
        'composite_label': label,
    }
    return composite, label, detail

class SocialAgent:
    """社交媒体情绪代理"""
    
    def __init__(self):
        self.name = "SocialAgent"
    
    def run_with_context(self, symbol='TSLA', ctx=None):
        """
        使用统一数据上下文执行舆情分析。
        yfinance 新闻走 ctx['news']，不独立访问网络。
        """
        # 1. 尝试 Finnhub 社交情绪（独立数据源，不受 yfinance 限流影响）
        finnhub_data = fetch_finnhub_sentiment(symbol)

        # 2. 获取 Finnhub 新闻（独立数据源）
        finnhub_news = fetch_finnhub_news(symbol)

        # 3. 新闻来源：优先使用 ctx（已通过统一数据层获取）
        yf_news = []
        if ctx and ctx.get('news'):
            yf_news = [{'title': n.get('title', ''), 'publisher': n.get('publisher', '')}
                       for n in ctx['news'][:10]]
        else:
            yf_news = fetch_yfinance_news(symbol)  # 降级：独立获取

        # 合并所有新闻
        all_news = finnhub_news + yf_news

        # 分析情绪
        sentiment, score = analyze_sentiment(all_news)

        # 尝试从 Finnhub 数据中提取
        if finnhub_data and 'reddit' in finnhub_data:
            reddit_sentiment = finnhub_data['reddit'].get('avgSentiment', 0)
            if reddit_sentiment != 0:
                sentiment = 'bullish' if reddit_sentiment > 0 else 'bearish'
                score = round(reddit_sentiment, 2)

        # 4. 获取 apewisdom Reddit 舆情（独立数据源）
        ape_data = fetch_apewisdom_sentiment(symbol)
        ape_sent = ape_data.get('sentiment', 'neutral') if ape_data else 'neutral'
        ape_ratio = ape_data.get('sentiment_ratio', 0) if ape_data else 0

        # 5. LLM 情绪分析（基于新闻标题）
        llm_sentiment, llm_score, llm_response = analyze_sentiment_llm(all_news)

        # 6. 综合评分
        composite_score, composite_label, composite_detail = calculate_composite_sentiment(
            sentiment, score, llm_sentiment, llm_score, ape_sent, ape_ratio
        )

        return {
            'symbol': symbol,
            'sentiment': sentiment,
            'sentiment_score': score,
            'llm_sentiment': llm_sentiment,
            'llm_score': llm_score,
            'llm_reason': llm_response,
            'sources': {
                'finnhub_sentiment': bool(finnhub_data),
                'finnhub_news': len(finnhub_news),
                'yfinance_news': len(yf_news),
                'apewisdom': bool(ape_data),
                'llm': bool(llm_response)
            },
            'apewisdom': ape_data,
            'news': all_news[:3],
            'composite_sentiment': composite_detail,
        }

    def run(self, symbol='TSLA'):
        """执行社交媒体分析（兼容旧接口）"""
        return self.run_with_context(symbol, ctx=None)

if __name__ == "__main__":
    agent = SocialAgent()
    result = agent.run('TSLA')
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
