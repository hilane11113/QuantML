#!/usr/bin/env python3
"""
股票助手 (Stock Assistant) - 智能股票期权分析系统
支持 A股(股票) + 美股(期权+股票)
"""

import sys
import os
import argparse
from datetime import datetime

# 导入前清除代理（A股需要直连）
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(var, None)

from agents import (
    AShareAgent, FundamentalAgent, format_fundamental_report, score_fundamental,
    PortfolioAgent, format_portfolio_report,
    OptionAgent, TechnicalAgent, SocialAgent,
    ResearcherTeam, RiskAgent, MemoryAgent, detect_market
)

def analyze_a_stock(symbol: str, include_fundamental: bool = False):
    """分析A股"""
    print(f"\n{'='*60}")
    print(" A股股票分析")
    print('='*60)
    
    # 技术分析
    agent = AShareAgent()
    tech_data = agent.run(symbol)
    
    # 基本面分析
    fundamental_data = {}
    fundamental_score = {}
    if include_fundamental:
        print()
        funda_agent = FundamentalAgent()
        fundamental_data = funda_agent.run(symbol)
        fundamental_score = score_fundamental(fundamental_data)
    
    # 打印报告
    from agents import format_a_stock_report
    print(format_a_stock_report(tech_data))
    
    if fundamental_data and "error" not in fundamental_data:
        print(format_fundamental_report(fundamental_data))
        print(f"\n🎯 基本面评分: {fundamental_score['level']} ({fundamental_score['total']}/100)")
        breakdown = fundamental_score.get('breakdown', {})
        print(f"   估值: {breakdown.get('valuation', 0)}/30 | 盈利: {breakdown.get('profitability', 0)}/40 | 成长: {breakdown.get('growth', 0)}/20 | 财务: {breakdown.get('financial', 0)}/10")

def analyze_us_stock(symbol: str):
    """分析美股（含期权）"""
    print(f"\n{'='*60}")
    print(" 美股股票分析 (完整版)")
    print('='*60)
    
    # Step 1: 技术分析
    print(f"\n{'='*60}")
    print(" STEP 1: 技术指标分析")
    print('='*60)
    
    tech_agent = TechnicalAgent()
    tech_data = tech_agent.run(symbol)
    
    if 'error' not in tech_data:
        print(f"  📈 价格: ${tech_data['price']}")
        print(f"  📊 趋势: {tech_data['trend']}")
        print(f"  📉 MA5: {tech_data['ma5']} | MA20: {tech_data['ma20']}")
        print(f"  📊 RSI: {tech_data['rsi']} ({tech_data['rsi_signal']})")
    else:
        print(f"  ❌ {tech_data['error']}")
    
    # Step 2: 社交媒体
    print(f"\n{'='*60}")
    print(" STEP 2: 社交媒体情绪")
    print('='*60)
    
    social_agent = SocialAgent()
    social_data = social_agent.run(symbol)
    
    print(f"  📱 情绪: {social_data.get('sentiment', 'N/A')} ({social_data.get('sentiment_score', 0)})")
    
    # Step 3: 期权分析
    print(f"\n{'='*60}")
    print(" STEP 3: 期权策略分析")
    print('='*60)
    
    option_agent = OptionAgent()
    option_data = option_agent.run(symbol)
    
    if 'error' in option_data:
        print(f"  ❌ {option_data['error']}")
        return
    
    print(f"  💰 价格: ${option_data['price']:.2f}")
    
    for i, s in enumerate(option_data['strategies'][:3], 1):
        print(f"\n  {i}. {s.get('type')}")
        if s.get('type') == 'Iron Condor':
            print(f"     [P]卖{s.get('short_put')}/买{s.get('long_put')} + [C]卖{s.get('short_call')}/买{s.get('long_call')}")
        else:
            print(f"     卖{s.get('short_strike')}/买{s.get('long_strike')}")
        print(f"     权利金: ${s.get('credit', 0):.2f} | RR: {s.get('rr_ratio', 0):.2f} | 评分: {s.get('score', 0)}")

def show_portfolio(args):
    """显示投资组合"""
    portfolio = PortfolioAgent()
    
    if args.clear:
        result = portfolio.clear_all()
        print(f"✅ {result['message']}")
        return
    
    positions = portfolio.get_positions()
    performance = portfolio.get_performance()
    print(format_portfolio_report(positions, performance))
    return positions, performance

def trade_stock(args):
    """交易股票"""
    portfolio = PortfolioAgent()
    
    if args.action == 'buy':
        result = portfolio.buy(
            symbol=args.symbol,
            market=detect_market(args.symbol),
            quantity=args.quantity,
            price=args.price,
            reason=args.reason or "系统推荐"
        )
        if result['success']:
            print(f"\n✅ 买入成功!")
            print(f"   标的: {result['symbol']}")
            print(f"   数量: {result['quantity']}股")
            print(f"   价格: ${result['price']:.2f}")
            print(f"   总金额: ${result['total_cost']:.2f}")
        else:
            print(f"\n❌ 买入失败: {result.get('error', '未知错误')}")
    
    elif args.action == 'sell':
        result = portfolio.sell(
            symbol=args.symbol,
            market=detect_market(args.symbol),
            quantity=args.quantity,
            price=args.price,
            reason=args.reason or "止盈/止损"
        )
        if result['success']:
            print(f"\n✅ 卖出成功!")
            print(f"   标的: {result['symbol']}")
            print(f"   数量: {result['quantity']}股")
            print(f"   价格: ${result['price']:.2f}")
            print(f"   盈亏: ${result['pnl']:.2f}")
        else:
            print(f"\n❌ 卖出失败: {result.get('error', '未知错误')}")

def chat_mode():
    """交互式对话模式"""
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💬 股票助手对话模式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输入问题即可获得回答，例如：
- "帮我分析一下平安银行"
- "我的持仓情况怎么样"
- "TSLA 现在适合买吗"
- "有什么推荐的策略"
- "quit" 或 "退出" 结束对话
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    
    from agents import LLMChatAgent, PortfolioAgent, intent_recognition, AShareAgent, OptionAgent
    
    chat_agent = LLMChatAgent()
    portfolio = PortfolioAgent()
    
    while True:
        try:
            user_input = input("\n👤 你: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit', '退出', 'q']:
                print("\n👋 再见！祝您投资顺利！")
                break
            
            # 意图识别
            intent = intent_recognition(user_input)
            
            # 根据意图处理
            if intent['intent'] == 'analyze' and intent.get('symbol'):
                symbol = intent['symbol']
                print(f"\n🔍 正在分析 {symbol}...")
                
                if detect_market(symbol).startswith('A_'):
                    agent = AShareAgent()
                    data = agent.run(symbol)
                    from agents import format_a_stock_report
                    print(format_a_stock_report(data))
                else:
                    option_agent = OptionAgent()
                    data = option_agent.run(symbol)
                    print(f"\n📈 {symbol} 分析:")
                    print(f"   价格: ${data.get('price', 0):.2f}")
                    if data.get('strategies'):
                        for s in data['strategies'][:2]:
                            print(f"   {s.get('type')}: ${s.get('credit', 0):.2f} (评分: {s.get('score', 0)})")
                
                # 获取上下文后让 LLM 总结
                positions = portfolio.get_positions()
                performance = portfolio.get_performance()
                context = {'positions': positions, 'performance': performance}
                
                response = chat_agent.chat(
                    f"用户询问了 {symbol} 的分析情况，请给出简短的投资建议。",
                    context
                )
                print(f"\n🤖 助手: {response}")
            
            elif intent['intent'] == 'portfolio':
                positions = portfolio.get_positions()
                performance = portfolio.get_performance()
                from agents import format_portfolio_report
                print(format_portfolio_report(positions, performance))
                
                response = chat_agent.chat(
                    "用户查询了持仓情况，请总结当前投资状态并给出建议。",
                    {'positions': positions, 'performance': performance}
                )
                print(f"\n🤖 助手: {response}")
            
            elif intent['intent'] == 'performance':
                positions = portfolio.get_positions()
                performance = portfolio.get_performance()
                response = chat_agent.chat(
                    f"用户查询绩效：总交易{performance['total_trades']}次，胜率{performance['win_rate']:.1f}%，总盈亏{performance['total_pnl']:.2f}元。请给出简短评价。",
                    {'positions': positions, 'performance': performance}
                )
                print(f"\n🤖 助手: {response}")
            
            else:
                # 对话模式
                positions = portfolio.get_positions()
                performance = portfolio.get_performance()
                context = {'positions': positions, 'performance': performance}
                
                response = chat_agent.chat(user_input, context)
                print(f"\n🤖 助手: {response}")
        
        except KeyboardInterrupt:
            print("\n\n👋 再见！祝您投资顺利！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {str(e)}")

def compare_strategies(symbol: str):
    """策略对比"""
    if detect_market(symbol).startswith('A_'):
        print("\n📊 A股策略对比 (技术指标)")
        agent = AShareAgent()
        data = agent.run(symbol)
        
        if 'technical' in data:
            tech = data['technical']
            rsi = tech.get('rsi', 50)
            
            print(f"\n{symbol} 技术指标:")
            print(f"  RSI: {rsi:.1f}")
            print(f"  MA5: {tech.get('ma5', 0):.3f}")
            print(f"  MA10: {tech.get('ma10', 0):.3f}")
            print(f"  MA20: {tech.get('ma20', 0):.3f}")
            
            print(f"\n📋 策略建议:")
            if rsi < 30:
                print("  🟢 RSI 超卖 - 建议: 买入/增持")
            elif rsi > 70:
                print("  🔴 RSI 超买 - 建议: 卖出/减仓")
            else:
                print("  🟡 RSI 正常 - 建议: 持有/观望")
                
            price = data.get('price', 0)
            ma5 = tech.get('ma5', 0)
            ma20 = tech.get('ma20', 0)
            
            if price > ma5 > ma20:
                print("  🟢 价格 > MA5 > MA20 - 强势上涨趋势")
            elif price < ma5 < ma20:
                print("  🔴 价格 < MA5 < MA20 - 下跌趋势")
            else:
                print("  🟡 均线纠缠 - 震荡整理")
    else:
        print("\n📊 美股策略对比 (期权)")
        option_agent = OptionAgent()
        option_data = option_agent.run(symbol)
        
        if 'strategies' in option_data:
            strategies = option_data['strategies']
            
            print(f"\n{symbol} 期权策略对比:")
            print(f"{'策略':<20} {'权利金':>10} {'风险回报':>10} {'评分':>8}")
            print("-" * 50)
            
            for s in strategies[:5]:
                print(f"{s.get('type', 'N/A'):<20} ${s.get('credit', 0):>9.2f} {s.get('rr_ratio', 0):>10.2f} {s.get('score', 0):>8}")
            
            # 推荐
            best = max(strategies, key=lambda x: x.get('score', 0))
            print(f"\n🎯 推荐策略: {best.get('type')} (评分: {best.get('score', 0)})")

def main():
    parser = argparse.ArgumentParser(description='股票助手 - A股+美股智能分析')
    parser.add_argument('symbol', nargs='?', help='股票代码 (A股6位/美股字母)')
    parser.add_argument('--fundamental', '-f', action='store_true', help='包含基本面分析(A股)')
    parser.add_argument('--portfolio', '-p', action='store_true', help='投资组合管理')
    parser.add_argument('--clear', action='store_true', help='清空投资组合')
    parser.add_argument('--trade', choices=['buy', 'sell'], help='交易操作')
    parser.add_argument('--quantity', '-q', type=int, default=100, help='交易数量')
    parser.add_argument('--price', '-t', type=float, default=0, help='交易价格(0=市价)')
    parser.add_argument('--reason', '-r', type=str, default='', help='交易理由')
    parser.add_argument('--compare', '-c', action='store_true', help='策略对比')
    parser.add_argument('--chat', action='store_true', help='交互式对话模式')
    
    args = parser.parse_args()
    
    # 对话模式
    if args.chat:
        chat_mode()
        return
    
    # 投资组合模式
    if args.portfolio or args.clear or args.trade:
        if args.symbol and args.trade:
            trade_stock(args)
        else:
            show_portfolio(args)
        return
    
    if not args.symbol:
        print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 股票助手 (Stock Assistant)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法:
  python main.py <代码>            分析股票
  python main.py 000001 -f          分析A股(含基本面)
  python main.py TSLA              分析美股
  python main.py TSLA --compare    策略对比
  python main.py -p                查看投资组合
  python main.py TSLA --trade buy -q 100 -t 10.5 买入
  python main.py --chat            交互式对话模式
  
示例:
  python main.py 510050 -f        分析A股ETF(含基本面)
  python main.py NVDA --compare   美股策略对比
  python main.py --chat            启动对话模式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
        return
    
    print(f"\n🔍 市场识别: {args.symbol} -> {detect_market(args.symbol)}")
    
    if detect_market(args.symbol).startswith('A_'):
        if args.compare:
            compare_strategies(args.symbol)
        else:
            analyze_a_stock(args.symbol, args.fundamental)
    else:
        if args.compare:
            compare_strategies(args.symbol)
        else:
            analyze_us_stock(args.symbol)

if __name__ == "__main__":
    main()
