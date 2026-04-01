#!/usr/bin/env python3
"""
OptionAgent - 个股分析入口
独立于期权推荐的股票分析
"""

import sys
from datetime import datetime
from agents import StockAgent

def main(symbol='TSLA'):
    """主函数"""
    
    print(f"\n{'#'*60}")
    print(f"#  OptionAgent 个股分析")
    print(f"#  标的: {symbol} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'#'*60}")
    
    agent = StockAgent()
    result = agent.analyze(symbol)
    
    # 基本面
    info = result.get('info', {})
    print(f"\n{'='*60}")
    print(" 💰 基本面")
    print('='*60)
    print(f"  名称: {result.get('name')}")
    print(f"  行业: {result.get('sector')}")
    
    market_cap = info.get('market_cap', 0)
    if market_cap:
        if market_cap > 1e12:
            cap_str = f"${market_cap/1e12:.2f}T"
        elif market_cap > 1e9:
            cap_str = f"${market_cap/1e9:.2f}B"
        else:
            cap_str = f"${market_cap/1e6:.2f}M"
        print(f"  市值: {cap_str}")
    
    print(f"  PE: {info.get('pe_ratio', 'N/A')}")
    print(f"  EPS: ${info.get('eps', 'N/A')}")
    print(f"  股息率: {info.get('dividend_yield', 'N/A')}%")
    print(f"  Beta: {info.get('beta', 'N/A')}")
    print(f"  52周区间: ${info.get('52w_low', 0)} - ${info.get('52w_high', 0)}")
    
    # 技术面
    tech = result.get('technical', {})
    print(f"\n{'='*60}")
    print(" 📈 技术面")
    print('='*60)
    
    if 'error' not in tech:
        print(f"  当前价格: ${tech.get('price', 0)}")
        print(f"  趋势: {tech.get('trend', 'N/A')}")
        print(f"  MA5: ${tech.get('ma5', 0)} | MA20: ${tech.get('ma20', 0)}")
        print(f"  RSI: {tech.get('rsi', 0)}")
        print(f"  支撑位: ${tech.get('support', 0)}")
        print(f"  阻力位: ${tech.get('resistance', 0)}")
    else:
        print(f"  ❌ {tech.get('error')}")
    
    # 分析师
    analyst = result.get('analyst', {})
    print(f"\n{'='*60}")
    print(" 🎯 分析师观点")
    print('='*60)
    print(f"  市场情绪: {analyst.get('sentiment', 'N/A')}")
    print(f"  上涨空间: {analyst.get('upside', 0)}%")
    print(f"  分析师评级: {analyst.get('grade', 'N/A')}")
    
    # 新闻
    news = result.get('news', {})
    print(f"\n{'='*60}")
    print(" 📰 新闻情绪")
    print('='*60)
    print(f"  情绪: {news.get('sentiment', 'N/A')}")
    print(f"  近7天新闻: {news.get('count', 0)}条")
    
    # 综合建议
    print(f"\n{'='*60}")
    print(" ✅ 综合建议")
    print('='*60)
    print(f"  ═════════════════════════════════════")
    print(f"  建议: {result.get('recommendation')}")
    print(f"  评分: {result.get('score')}")
    print(f"  ═════════════════════════════════════")

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'TSLA'
    main(symbol)
