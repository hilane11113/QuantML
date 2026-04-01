#!/usr/bin/env python3
"""
TSLA 期权策略 - 简化版
基于VIX和IV指标的Short Put Spread决策
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
    print("✅ 代理设置成功")
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

def get_vix():
    """获取VIX和MA10"""
    try:
        vix = yf.download("^VIX", period="30d")["Close"]
        if len(vix) < 10:
            return np.nan, np.nan
        vix_val = vix.iloc[-1]
        ma10 = vix.tail(10).mean()
        vix_val = vix_val.item() if isinstance(vix_val, pd.Series) else vix_val
        ma10 = ma10.item() if isinstance(ma10, pd.Series) else ma10
        return vix_val, ma10
    except Exception as e:
        print(f"⚠️ VIX获取失败: {e}")
        return np.nan, np.nan

def get_tsla():
    """获取TSLA价格和IV"""
    try:
        tsla = yf.Ticker("TSLA")
        hist = tsla.history(period="30d")
        price = hist['Close'].iloc[-1]
        price = price.item() if isinstance(price, pd.Series) else price
        
        # 获取期权IV
        expiries = tsla.options
        iv = np.nan
        if expiries:
            opt = tsla.option_chain(expiries[0])
            puts = opt.puts
            atm = min(puts['strike'], key=lambda x: abs(x - price))
            atm_put = puts[puts['strike'] == atm]
            iv = atm_put.iloc[0].get('impliedVolatility', np.nan)
            if pd.notna(iv):
                iv = iv * 100
        
        return price, iv
    except Exception as e:
        print(f"⚠️ TSLA数据获取失败: {e}")
        return np.nan, np.nan

def calculate_hv():
    """计算历史波动率"""
    try:
        hist = yf.download("TSLA", period="60d")["Close"]
        if len(hist) < 30:
            return np.nan
        returns = np.log(hist / hist.shift(1)).dropna()
        hv = returns.tail(30).std() * np.sqrt(252) * 100
        hv = hv.item() if isinstance(hv, pd.Series) else hv
        return hv
    except:
        return np.nan

def make_decision(vix, vix_ma10, iv, hv):
    """决策逻辑"""
    if pd.isna(vix) or pd.isna(iv):
        return "❌禁止（数据缺失）", "UNKNOWN"
    
    # VIX趋势判断
    if vix > vix_ma10:
        vix_status = "🔴红灯"
    elif vix < vix_ma10:
        vix_status = "🟢绿灯"
    else:
        vix_status = "🟡黄灯"
    
    # IV条件
    if iv > 65:
        iv_cond = "RED"
    elif iv > 50:
        iv_cond = "YELLOW"
    elif iv >= 30:
        iv_cond = "GREEN"
    else:
        iv_cond = "YELLOW"
    
    # 决策
    if vix_status == "🔴红灯":
        decision = "❌禁止（VIX趋势不利）"
    elif iv_cond == "RED":
        decision = "❌禁止（IV过高）"
    elif vix_status == "🟢绿灯" and iv_cond == "GREEN":
        decision = "✅开仓"
    elif vix_status == "🟡黄灯" or iv_cond == "YELLOW":
        decision = "⚠️试探（半仓）"
    else:
        decision = "❌禁止"
    
    return decision, vix_status

def main():
    print("=" * 50)
    print("🚀 TSLA Short Put Spread 策略 (简化版)")
    print("=" * 50)
    
    # 初始化数据库
    init_db()
    
    # 设置代理
    setup_proxy()
    
    # 获取数据
    print("\n📊 获取市场数据...")
    vix, vix_ma10 = get_vix()
    tsla_price, iv = get_tsla()
    hv = calculate_hv()
    
    # 计算IV/HV
    iv_hv_ratio = (iv / hv * 100) if pd.notna(iv) and pd.notna(hv) and hv > 0 else np.nan
    
    # 打印指标
    print(f"\n📈 市场指标:")
    print(f"  TSLA价格: ${tsla_price:.2f}" if pd.notna(tsla_price) else "  TSLA价格: ❌")
    print(f"  VIX: {vix:.2f}" if pd.notna(vix) else "  VIX: ❌")
    print(f"  VIX MA10: {vix_ma10:.2f}" if pd.notna(vix_ma10) else "  VIX MA10: ❌")
    print(f"  TSLA IV: {iv:.1f}%" if pd.notna(iv) else "  TSLA IV: ❌")
    print(f"  HV: {hv:.1f}%" if pd.notna(hv) else "  HV: ❌")
    print(f"  IV/HV: {iv_hv_ratio:.0f}%" if pd.notna(iv_hv_ratio) else "  IV/HV: ❌")
    
    # 决策
    decision, vix_status = make_decision(vix, vix_ma10, iv, hv)
    print(f"\n🧠 决策: {decision}")
    print(f"  VIX趋势: {vix_status}")
    
    # 计算执行价
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
        0,  # IVRank
        iv_hv_ratio if pd.notna(iv_hv_ratio) else 0,
        0,  # HasEarnings
        vix_status,
        "GREEN" if "绿灯" in vix_status else ("YELLOW" if "黄灯" in vix_status else "RED"),
        decision,
        f"VIX:{vix:.1f},IV:{iv:.1f}%"
    )
    
    signal_id = save_signal(signal_data)
    print(f"\n✅ 信号已保存 (ID: {signal_id})")
    
    # 显示最近信号
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM signals ORDER BY id DESC LIMIT 3", conn)
    conn.close()
    
    print("\n📋 最近信号:")
    for _, row in df.iterrows():
        print(f"  [{row['id']}] {row['RunDateTime'][:16]} | {row['Decision'][:10]} | VIX:{row['VIXLevel']:.1f} IV:{row['IVLevel']:.1f}")

if __name__ == "__main__":
    main()
