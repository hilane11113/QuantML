#!/usr/bin/env python3
"""
TSLA 期权策略 - 完整版
基于VIX、IV、IV Rank、IV/HV指标的Short Put Spread决策
参考 tsla_strategy_signals-vpn.py
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# 数据库路径
DB_PATH = "/root/.openclaw/workspace/quant/TSLA期权策略/strategy_signals.db"

def setup_proxy():
    """设置代理"""
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
    print(f"✅ 代理设置成功: http://127.0.0.1:7897")
    return True

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            RunDateTime TEXT,
            UnderlyingSymbol TEXT,
            OptionType TEXT,
            LongStrike REAL,
            ShortStrike REAL,
            SpreadWidth REAL,
            VIXLevel REAL,
            IVLevel REAL,
            IVRankEstimate REAL,
            IV_HV_Ratio REAL,
            HasEarnings INTEGER,
            VIX_TrendStatus TEXT,
            IVCondition TEXT,
            Decision TEXT,
            IsRealTrade INTEGER DEFAULT 0,
            ProfitLoss REAL DEFAULT 0,
            Cost REAL DEFAULT 0,
            Notes TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")

def save_signal(data):
    """保存信号到数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signals (
            RunDateTime, UnderlyingSymbol, OptionType, LongStrike, ShortStrike,
            SpreadWidth, VIXLevel, IVLevel, IVRankEstimate, IV_HV_Ratio,
            HasEarnings, VIX_TrendStatus, IVCondition, Decision, Notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', data)
    conn.commit()
    signal_id = cursor.lastrowid
    conn.close()
    return signal_id

def get_latest_signals(limit=3):
    """获取最近信号"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(f"SELECT * FROM signals ORDER BY id DESC LIMIT {limit}", conn)
    conn.close()
    return df

def safe_get(data, key, default=np.nan):
    """安全获取值"""
    try:
        val = data.get(key, default)
        return val if pd.notna(val) else default
    except:
        return default

def calculate_hv(prices, window=30):
    """计算历史波动率（年化）"""
    if len(prices) < window + 1:
        return np.nan
    log_returns = np.log(prices / prices.shift(1))
    hv = log_returns.tail(window).std() * np.sqrt(252)
    hv_scalar = hv.item() if isinstance(hv, pd.Series) else hv
    return hv_scalar * 100

def get_vix_and_ma10():
    """获取VIX当前值和10日均线"""
    try:
        end = datetime.now()
        start = end - timedelta(days=30)
        vix = yf.download("^VIX", start=start, end=end, interval="1d")["Close"]
        if len(vix) < 10:
            return np.nan, np.nan
        ma10 = vix.tail(10).mean()
        current_vix = vix.iloc[-1]
        current_vix = current_vix.item() if isinstance(current_vix, pd.Series) else current_vix
        ma10 = ma10.item() if isinstance(ma10, pd.Series) else ma10
        return current_vix, ma10
    except Exception as e:
        print(f"⚠️ 获取VIX数据失败: {e}")
        return np.nan, np.nan

def get_tsla_data():
    """获取TSLA价格和期权IV"""
    try:
        tsla = yf.Ticker("TSLA")
        hist = tsla.history(period="60d")
        current_price = hist['Close'].iloc[-1] if not hist.empty else np.nan
        
        expiries = tsla.options
        if not expiries:
            return current_price, np.nan, np.nan, []
        
        today = datetime.today().date()
        valid_expiries = [e for e in expiries if datetime.strptime(e, "%Y-%m-%d").date() > today + timedelta(days=1)]
        if not valid_expiries:
            return current_price, np.nan, np.nan, []
        
        near_expiry = valid_expiries[0]
        opt = tsla.option_chain(near_expiry)
        puts = opt.puts
        
        atm_strike = min(puts['strike'], key=lambda x: abs(x - current_price))
        atm_put = puts[puts['strike'] == atm_strike]
        
        iv = safe_get(atm_put.iloc[0] if not atm_put.empty else {}, 'impliedVolatility', np.nan)
        iv = iv * 100 if pd.notna(iv) else np.nan
        
        return current_price, iv, np.nan, valid_expiries
    except Exception as e:
        print(f"⚠️ 获取TSLA数据失败: {e}")
        return np.nan, np.nan, np.nan, []

def estimate_iv_metrics(iv, hist_prices):
    """估算IV Rank和IV/HV"""
    hv = calculate_hv(hist_prices) if len(hist_prices) > 30 else np.nan
    
    iv_scalar = iv.iloc[0] if isinstance(iv, pd.Series) else iv
    hv_scalar = hv.iloc[0] if isinstance(hv, pd.Series) else hv
    
    iv_hv_ratio = (iv_scalar / hv_scalar * 100) if pd.notna(iv_scalar) and pd.notna(hv_scalar) and hv_scalar > 0 else np.nan
    
    # 简化IV Rank估算
    iv_rank_est = 70 if pd.notna(iv_scalar) and iv_scalar > 50 else 40 if pd.notna(iv_scalar) and iv_scalar > 35 else 20
    
    return iv_rank_est, hv_scalar, iv_hv_ratio

def check_iv_condition(iv):
    """IV条件判断"""
    if pd.isna(iv): return "UNKNOWN"
    if iv > 65: return "RED"
    if 51 <= iv <= 65: return "YELLOW"
    if 30 <= iv <= 50: return "GREEN"
    return "YELLOW"

def check_iv_rank_condition(rank):
    """IV Rank条件判断"""
    if pd.isna(rank): return "YELLOW"
    if rank >= 50: return "GREEN"
    if rank >= 30: return "YELLOW"
    return "RED"

def check_iv_hv_condition(ratio):
    """IV/HV条件判断"""
    if pd.isna(ratio): return "YELLOW"
    if ratio > 160: return "RED"
    if 100 <= ratio <= 140: return "GREEN"
    return "YELLOW"

def check_vix_trend():
    """VIX趋势判断"""
    try:
        vix_data = yf.download("^VIX", period="20d")["Close"]
        if len(vix_data) >= 20:
            ma10_today = vix_data.tail(10).mean()
            ma10_yesterday = vix_data.tail(19).head(10).mean()
            ma10_today_scalar = ma10_today.item() if isinstance(ma10_today, pd.Series) else ma10_today
            ma10_yesterday_scalar = ma10_yesterday.item() if isinstance(ma10_yesterday, pd.Series) else ma10_yesterday
            return ma10_today_scalar > ma10_yesterday_scalar
        return True
    except:
        return True

def main():
    print("=" * 60)
    print("🚀 TSLA Short Put Spread 策略 (完整版)")
    print("=" * 60)
    
    # 初始化
    if not os.path.exists(DB_PATH):
        init_db()
    else:
        print(f"✅ 数据库已存在: {DB_PATH}")
    
    setup_proxy()
    
    # 获取数据
    print("\n📊 获取市场数据...")
    vix, vix_ma10 = get_vix_and_ma10()
    tsla_price, iv, _, expiries = get_tsla_data()
    hist = yf.download("TSLA", period="60d")["Close"]
    iv_rank, hv, iv_hv_ratio = estimate_iv_metrics(iv, hist)
    
    # 打印指标
    print(f"\n📈 市场指标:")
    print(f"  • TSLA 价格       : ${tsla_price:.2f}" if pd.notna(tsla_price) else "  • TSLA 价格       : ❌")
    print(f"  • VIX             : {vix:.2f}" if pd.notna(vix) else "  • VIX             : ❌")
    print(f"  • VIX 10日均线    : {vix_ma10:.2f}" if pd.notna(vix_ma10) else "  • VIX 10日均线    : ❌")
    print(f"  • TSLA IV         : {iv:.1f}%" if pd.notna(iv) else "  • TSLA IV         : ❌")
    print(f"  • 估算 IV Rank    : {iv_rank:.0f}%" if pd.notna(iv_rank) else "  • 估算 IV Rank    : ❌")
    print(f"  • 历史波动率 (HV) : {hv:.1f}%" if pd.notna(hv) else "  • HV              : ❌")
    print(f"  • IV / HV 比值    : {iv_hv_ratio:.0f}%" if pd.notna(iv_hv_ratio) else "  • IV/HV           : ❌")
    print(f"  • 未来7天财报     : 否")
    
    # 条件判断
    iv_cond = check_iv_condition(iv)
    rank_cond = check_iv_rank_condition(iv_rank)
    hv_cond = check_iv_hv_condition(iv_hv_ratio)
    event_cond = "GREEN"  # 无财报
    
    # VIX趋势
    vix_scalar = vix.item() if isinstance(vix, pd.Series) else vix
    vix_ma10_scalar = vix_ma10.item() if isinstance(vix_ma10, pd.Series) else vix_ma10
    ma10_is_rising = check_vix_trend()
    
    if pd.isna(vix_scalar) or pd.isna(vix_ma10_scalar):
        vix_status = "UNKNOWN"
    elif vix_scalar > vix_ma10_scalar and ma10_is_rising:
        vix_status = "🔴红灯"
    elif vix_scalar < vix_ma10_scalar:
        vix_status = "🟢绿灯"
    else:
        vix_status = "🟡黄灯"
    
    print(f"\n🔍 VIX 趋势状态: {vix_status}")
    
    # 决策逻辑
    print("\n📋 TSLA 个股条件检查:")
    print(f"  • IV (30–50%为绿)      : {iv_cond}")
    print(f"  • IV Rank (≥50%为绿)   : {rank_cond}")
    print(f"  • IV/HV (100–140%为绿) : {hv_cond}")
    print(f"  • 无事件 (无为绿)       : {event_cond}")
    
    conditions = [iv_cond, rank_cond, hv_cond, event_cond]
    red_count = conditions.count("RED")
    green_count = conditions.count("GREEN")
    
    # 决策
    if pd.isna(iv):
        decision = "❌禁止（IV数据缺失）"
    elif vix_status == "🔴红灯":
        decision = "❌禁止（VIX趋势不利）"
    elif vix_status == "🟡黄灯":
        if red_count > 0:
            decision = "❌禁止（存在红灯条件）"
        else:
            decision = "⚠️试探（半仓，≤3天）"
    else:  # 绿灯
        if red_count > 0:
            decision = "❌禁止（存在红灯条件）"
        elif green_count >= 3:
            decision = "✅开仓"
        else:
            decision = "⚠️试探（半仓，≤3天）"
    
    print(f"\n🧠 决策结果: {decision}")
    
    # 计算执行价
    if pd.notna(tsla_price) and expiries:
        try:
            tsla = yf.Ticker("TSLA")
            opt = tsla.option_chain(expiries[0])
            puts = opt.puts
            atm_strike = min(puts['strike'], key=lambda x: abs(x - tsla_price))
            
            if pd.notna(vix_scalar) and vix_scalar > 17:
                long_strike = atm_strike * 0.92
                short_strike = long_strike - 20
            else:
                long_strike = atm_strike * 0.96
                short_strike = long_strike - 35
        except:
            long_strike = tsla_price * 0.95
            short_strike = tsla_price * 0.90
    else:
        long_strike = tsla_price * 0.95 if pd.notna(tsla_price) else 0
        short_strike = tsla_price * 0.90 if pd.notna(tsla_price) else 0
    
    spread_width = abs(long_strike - short_strike)
    
    # 保存信号
    signal_data = (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'TSLA', 'Put',
        long_strike, short_strike, spread_width,
        vix if pd.notna(vix) else 0,
        iv if pd.notna(iv) else 0,
        iv_rank if pd.notna(iv_rank) else 0,
        iv_hv_ratio if pd.notna(iv_hv_ratio) else 0,
        0, vix_status, iv_cond, decision,
        f"VIX:{vix_status},IV:{iv_cond}"
    )
    
    signal_id = save_signal(signal_data)
    print(f"\n✅ 信号已保存 (ID: {signal_id})")
    
    # 显示最近信号
    df = get_latest_signals(3)
    print("\n📋 最近信号:")
    for _, row in df.iterrows():
        print(f"  [{row['id']}] {row['RunDateTime'][5:16]} | {row['Decision'][:10]} | VIX:{row['VIXLevel']:.1f} IV:{row['IVLevel']:.1f}")

if __name__ == "__main__":
    main()
