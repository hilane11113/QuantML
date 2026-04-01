#!/usr/bin/env python3
"""
期权持仓量/Open Interest 统计
按MEMORY.md格式二输出：Put OI + Call OI 表格

用法:
  python3 option_oi_stats.py           # 默认 TSLA
  python3 option_oi_stats.py NVDA       # 指定 NVDA
  python3 option_oi_stats.py AAPL MSFT # 多个股票
"""

import yfinance as yf
import pandas as pd
import os
import sys
import warnings
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'
os.environ['http_proxy'] = PROXY
os.environ['https_proxy'] = PROXY

# 从命令行参数获取股票代码，默认TSLA
STOCKS = sys.argv[1:] if len(sys.argv) > 1 else ['TSLA']

def get_option_oi_data(ticker, stock_price):
    """获取期权OI和成交量数据"""
    try:
        # 获取所有到期日
        expirations = ticker.options
        if not expirations:
            return None, None
        
        all_puts = []
        all_calls = []
        
        for exp_date in expirations[:8]:  # 取前8个到期日（约2个月）
            try:
                opt = ticker.option_chain(exp_date)
                
                # 处理Put数据
                puts = opt.puts.copy()
                puts['expiry'] = exp_date
                puts['days_to_expiry'] = (pd.to_datetime(exp_date) - pd.Timestamp.now()).days
                all_puts.append(puts)
                
                # 处理Call数据
                calls = opt.calls.copy()
                calls['expiry'] = exp_date
                calls['days_to_expiry'] = (pd.to_datetime(exp_date) - pd.Timestamp.now()).days
                all_calls.append(calls)
            except:
                continue
        
        if not all_puts or not all_calls:
            return None, None
        
        puts_df = pd.concat(all_puts, ignore_index=True)
        calls_df = pd.concat(all_calls, ignore_index=True)
        
        return puts_df, calls_df
    except Exception as e:
        return None, None

def format_number(n):
    """格式化数字，添加千分位逗号"""
    if pd.isna(n):
        return "N/A"
    n = int(n)
    return f"{n:,}"

def format_change(c):
    """格式化成交量变化，加🔥emoji"""
    if pd.isna(c):
        return "N/A"
    c = int(c)
    if c > 10000:
        return f"+{format_number(c)} 🔥"
    elif c > 0:
        return f"+{format_number(c)}"
    else:
        return format_number(c)

def output_stock_oi(STOCK):
    """输出单个股票的OI统计"""
    print(f"\n{'='*60}")
    print(f"📈 处理: {STOCK}")
    print("="*60)
    
    try:
        ticker = yf.Ticker(STOCK)
        hist = ticker.history(period="1d")
        if hist.empty:
            print(f"❌ {STOCK} 无法获取股票数据")
            return
        
        price = hist['Close'].iloc[-1]
        price = price.item() if hasattr(price, 'item') else price
    except Exception as e:
        print(f"❌ {STOCK} 获取数据失败: {e}")
        return
    
    puts_df, calls_df = get_option_oi_data(ticker, price)
    
    if puts_df is None or calls_df is None:
        print(f"⚠️ {STOCK} 无期权数据")
        return
    
    print(f"\n📊 {STOCK} 期权持仓量（2个月内）")
    print(f"📈 现价: ${price:.2f}")
    
    # ==================== Put Open Interest ====================
    # 优先按OI降序，若OI全为0则按成交量
    puts_df['sort_key'] = puts_df['openInterest'].fillna(0) + puts_df['volume'].fillna(0) * 0.1
    puts_top = puts_df.nlargest(15, 'sort_key')[['expiry', 'strike', 'openInterest', 'volume']].copy()
    puts_top = puts_top[puts_top['openInterest'].fillna(0) > 0].head(10)  # 过滤OI>0
    
    # 如果OI数据太少，放宽条件
    if len(puts_top) < 5:
        puts_top = puts_df.nlargest(10, 'sort_key')[['expiry', 'strike', 'openInterest', 'volume']].copy()
    
    puts_top['expiry_short'] = puts_top['expiry'].apply(lambda x: x[5:] if x else '')
    puts_top['strike_str'] = puts_top['strike'].apply(lambda x: f"${x:.1f}")
    
    print("\n📉 Put Open Interest（看跌期权）")
    print("| Expiry | Strike | Open Int | 1-Day Chg |")
    print("|--------|--------|----------|-----------|")
    for _, row in puts_top.iterrows():
        print(f"| {row['expiry_short']:6s} | {row['strike_str']:7s} | {format_number(row['openInterest']):9s} | {format_change(row['volume']):10s} |")
    
    # ==================== Call Open Interest ====================
    calls_df['sort_key'] = calls_df['openInterest'].fillna(0) + calls_df['volume'].fillna(0) * 0.1
    calls_top = calls_df.nlargest(15, 'sort_key')[['expiry', 'strike', 'openInterest', 'volume']].copy()
    calls_top = calls_top[calls_top['openInterest'].fillna(0) > 0].head(10)
    
    if len(calls_top) < 5:
        calls_top = calls_df.nlargest(10, 'sort_key')[['expiry', 'strike', 'openInterest', 'volume']].copy()
    
    calls_top['expiry_short'] = calls_top['expiry'].apply(lambda x: x[5:] if x else '')
    calls_top['strike_str'] = calls_top['strike'].apply(lambda x: f"${x:.1f}")
    
    print("\n📈 Call Open Interest（看涨期权）")
    print("| Expiry | Strike | Open Int | 1-Day Chg |")
    print("|--------|--------|----------|-----------|")
    for _, row in calls_top.iterrows():
        print(f"| {row['expiry_short']:6s} | {row['strike_str']:7s} | {format_number(row['openInterest']):9s} | {format_change(row['volume']):10s} |")
    
    # ==================== 分析结论 ====================
    # 找出最大支撑和阻力（基于OI+成交量）
    puts_df['combined'] = puts_df['openInterest'].fillna(0) + puts_df['volume'].fillna(0) * 0.1
    calls_df['combined'] = calls_df['openInterest'].fillna(0) + calls_df['volume'].fillna(0) * 0.1
    
    max_put_idx = puts_df['combined'].idxmax()
    max_call_idx = calls_df['combined'].idxmax()
    
    max_put_oi_strike = puts_df.loc[max_put_idx, 'strike']
    max_call_oi_strike = calls_df.loc[max_call_idx, 'strike']
    
    print("\n💡 说明")
    print("- Open Int: 未平仓合约数量（Yahoo API数据可能不全）")
    print("- 1-Day Chg: 成交量")
    print("- 综合排序: OI×1 + 成交量×0.1")
    
    print(f"\n📊 {STOCK} 策略分析：")
    print(f"- 支撑区域：${max_put_oi_strike:.1f} 附近Put持仓量+成交量最大")
    print(f"- 阻力区域：${max_call_oi_strike:.1f} 附近Call持仓量+成交量最大")

# ==================== 主程序 ====================
print("="*60)
print("📊 期权持仓量/Open Interest 统计")
print("="*60)
print(f"📈 股票: {', '.join(STOCKS)}")

for STOCK in STOCKS:
    output_stock_oi(STOCK)

print(f"\n✅ OI统计完成: {', '.join(STOCKS)}")
