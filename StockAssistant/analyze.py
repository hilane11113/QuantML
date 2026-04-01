#!/usr/bin/env python3
"""
OptionAgent - 统一入口 (辩论版)
同时分析股票和期权，展示完整决策过程
"""

import sys
from datetime import datetime

from agents import StockAgent, NewsAgent, OptionAgent, TechnicalAgent, SocialAgent, ResearcherTeam, RiskAgent, MemoryAgent

def analyze_stock(symbol):
    """分析个股"""
    print(f"\n{'='*60}")
    print(f" 📊 个股分析 - {symbol}")
    print('='*60)
    
    agent = StockAgent()
    result = agent.analyze(symbol)
    
    info = result.get('info', {})
    tech = result.get('technical', {})
    analyst = result.get('analyst', {})
    
    print(f"  💰 {result.get('name')}")
    print(f"     行业: {result.get('sector')}")
    
    market_cap = info.get('market_cap', 0)
    if market_cap:
        cap_str = f"${market_cap/1e12:.2f}T" if market_cap > 1e12 else f"${market_cap/1e9:.2f}B"
        print(f"     市值: {cap_str}")
    
    print(f"     PE: {info.get('pe_ratio', 'N/A')} | EPS: ${info.get('eps', 'N/A')}")
    print(f"")
    print(f"  📈 技术面")
    if 'error' not in tech:
        print(f"     价格: ${tech.get('price', 0)} | 趋势: {tech.get('trend', 'N/A')}")
        print(f"     RSI: {tech.get('rsi', 0)} | 支撑: ${tech.get('support', 0)}")
    print(f"")
    print(f"  🎯 分析师")
    print(f"     情绪: {analyst.get('sentiment', 'N/A')} | 空间: {analyst.get('upside', 0)}%")
    print(f"")
    print(f"  ✅ 建议: {result.get('recommendation')} (评分: {result.get('score')})")
    
    return result, tech

def analyze_option_with_debate(symbol, news_data, tech_data):
    """期权分析 + 辩论"""
    print(f"\n{'='*60}")
    print(f" 📈 期权分析 - {symbol}")
    print('='*60)
    
    # 期权数据
    option_agent = OptionAgent()
    option_data = option_agent.run(symbol)
    
    print(f"\n  💰 当前价格: ${option_data.get('price', 0):.2f}")
    
    # 展示所有策略
    if option_data.get('strategies'):
        print(f"  📊 候选策略 (多维度评分):")
        for i, s in enumerate(option_data['strategies'], 1):
            expiry = s.get('expiry', 'N/A')
            print(f"\n  {i}. {s.get('type')} (到期: {expiry})")
            if s.get('type') == 'Iron Condor':
                print(f"     [P]卖{s.get('short_put')}/买{s.get('long_put')} + [C]卖{s.get('short_call')}/买{s.get('long_call')}")
            elif s.get('type') == 'Bull Call Spread':
                print(f"     买{s.get('long_strike')}/卖{s.get('short_strike')}")
            elif s.get('type') == 'Bull Put Spread':
                print(f"     卖{s.get('short_strike')}/买{s.get('long_strike')}")
            
            credit = s.get('credit') or s.get('debit') or s.get('premium') or 0
            print(f"     权利金: ${credit:.2f} | RR: {s.get('rr_ratio', 0):.2f} | 评分: {s.get('score', 0)}")
            print(f"     流动性: {s.get('liquidity', 'N/A')} | 安全距离: {s.get('safety', 'N/A')}%")
    
    # ===== 辩论机制 =====
    print(f"\n{'='*60}")
    print(f" 🗳️ 辩论机制 - 多空对决")
    print('='*60)
    
    researcher = ResearcherTeam()
    
    # 1. 多头观点
    print(f"\n  🟢 【多头研究员】寻找买入理由...")
    debate_result = researcher.debate(news_data, option_data, tech_data)
    print(f"     {debate_result.get('bull', 'N/A')}")
    
    # 2. 空头观点
    print(f"\n  🔴 【空头研究员】寻找观望理由...")
    print(f"     {debate_result.get('bear', 'N/A')}")
    
    # 3. 最终决策
    print(f"\n  ⚖️ 【决策者】综合判断...")
    final_decision = researcher.synthesize(debate_result, option_data)
    print(f"     🤖 {final_decision}")
    
    # 风险评估
    risk_agent = RiskAgent()
    risk_result = risk_agent.run(news_data, option_data, {})
    print(f"\n  ⚠️ 风险评估")
    print(f"     风险等级: {risk_result.get('risk_level')}")
    print(f"     仓位建议: {risk_result.get('position_size')}")
    print(f"     止损建议: {risk_result.get('stop_loss')}")
    
    return option_data, risk_result, debate_result, final_decision

def main(symbol='TSLA'):
    """主函数"""
    print(f"\n{'#'*60}")
    print(f"#  OptionAgent 智能分析系统 (辩论版)")
    print(f"#  标的: {symbol} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"#  模式: 股票 + 期权 + 辩论决策")
    print(f"{'#'*60}")
    
    # 1. 个股分析
    stock_result, tech_data = analyze_stock(symbol)
    
    # 2. 新闻
    news_agent = NewsAgent()
    news_data = news_agent.run(symbol)
    print(f"\n  📰 新闻: {news_data['news_count']}条 | 话题: {list(news_data['topics'].keys())[:3]}")
    
    # 3. 社交
    social_agent = SocialAgent()
    social_data = social_agent.run(symbol)
    print(f"  📱 情绪: {social_data.get('sentiment', 'N/A')}")
    
    # 4. 期权 + 辩论
    option_data, risk_result, debate_result, final_decision = analyze_option_with_debate(symbol, news_data, tech_data)
    
    # 5. 总结
    print(f"\n{'='*60}")
    print(f" 📋 决策总结")
    print('='*60)
    
    best = option_data.get('strategies', [{}])[0] if option_data.get('strategies') else {}
    
    print(f"""
  ┌─────────────────────────────────────────────────┐
  │ 📊 TSLA 完整分析报告                            │
  ├─────────────────────────────────────────────────┤
  │ 🏷️ 股票建议: {stock_result.get('recommendation')}           │
  │ 📈 技术趋势: {tech_data.get('trend', 'N/A')} (RSI: {tech_data.get('rsi', 0)})    │
  ├─────────────────────────────────────────────────┤
  │ 🗳️ 辩论过程                                    │
  │   🟢 多头: {debate_result.get('bull', '')[:40]}...  │
  │   🔴 空头: {debate_result.get('bear', '')[:40]}...  │
  ├─────────────────────────────────────────────────┤
  │ 📊 期权策略: {best.get('type', 'N/A')}                     │
  │ 💵 预期收益: ${best.get('credit', 0):.2f}                    │
  │ 🤖 最终决策: {final_decision[:30]}            │
  │ ⚠️ 风险等级: {risk_result.get('risk_level')}                         │
  │ 💼 仓位建议: {risk_result.get('position_size')}                │
  └─────────────────────────────────────────────────┘
""")

if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'TSLA'
    main(symbol)
