#!/usr/bin/env python3
"""
垂直价差推荐策略 (Vertical Spread Recommender)
基于 TSLA Short Put Spread 策略逻辑，扩展到多标的筛选

逻辑:
- VIX < MA10 → 绿灯区 (适合做空波动率策略: Bull Put Spread)
- VIX > MA10 → 红灯区 (禁止开仓)
- VIX 在 MA10 附近 → 黄灯区 (试探)

个股条件:
- IV: 30-50% 绿灯
- IV/HV: 100-140% 绿灯
- 无重大事件
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ============== 配置 ==============
PROXY = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

# 扫描标的池
STOCKS = ['TSLA', 'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'AMD', 'NFLX', 'SPY', 'QQQ', 'IWM']

# 数据库
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spreads.db'

def setup_proxy():
    print(f"✅ 代理设置: {PROXY}")

def get_vix_data():
    """获取VIX和MA10"""
    try:
        vix = yf.download("^VIX", period="30d", interval="1d")["Close"]
        if len(vix) < 10:
            return np.nan, np.nan
        current = vix.iloc[-1]
        ma10 = vix.tail(10).mean()
        current = current.item() if isinstance(current, pd.Series) else current
        ma10 = ma10.item() if isinstance(ma10, pd.Series) else ma10
        
        # 计算MA10趋势
        ma10_yesterday = vix.tail(19).head(10).mean()
        ma10_yesterday = ma10_yesterday.item() if isinstance(ma10_yesterday, pd.Series) else ma10_yesterday
        ma10_rising = current > ma10_yesterday
        
        return current, ma10, ma10_rising
    except Exception as e:
        print(f"⚠️ VIX获取失败: {e}")
        return np.nan, np.nan, True

def calculate_hv(prices, window=30):
    """计算历史波动率"""
    if len(prices) < window + 1:
        return np.nan
    returns = np.log(prices / prices.shift(1))
    hv = returns.tail(window).std() * np.sqrt(252)
    hv = hv.item() if isinstance(hv, pd.Series) else hv
    return hv * 100

def get_stock_data(symbol):
    """获取个股数据"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="60d")
        
        if hist.empty:
            return None
        
        price = hist['Close'].iloc[-1]
        price = price.item() if isinstance(price, pd.Series) else price
        
        # HV
        hv = calculate_hv(hist['Close'])
        
        # IV
        iv = np.nan
        expiries = ticker.options
        if expiries:
            today = datetime.today().date()
            valid = [e for e in expiries if datetime.strptime(e, "%Y-%m-%d").date() > today + timedelta(days=1)]
            if valid:
                opt = ticker.option_chain(valid[0])
                puts = opt.puts
                if not puts.empty:
                    atm = min(puts['strike'], key=lambda x: abs(x - price))
                    atm_put = puts[puts['strike'] == atm]
                    iv_val = atm_put.iloc[0].get('impliedVolatility', np.nan)
                    iv = (iv_val * 100) if pd.notna(iv_val) else np.nan
        
        # IV/HV
        iv_hv = (iv / hv * 100) if pd.notna(iv) and pd.notna(hv) and hv > 0 else np.nan
        
        return {
            'price': price,
            'iv': iv,
            'hv': hv,
            'iv_hv': iv_hv,
            'expiries': valid if expiries else []
        }
    except Exception as e:
        print(f"  ⚠️ {symbol}: {e}")
        return None

def check_decision(vix, vix_ma10, ma10_rising, iv, iv_hv):
    """决策判断"""
    # VIX状态
    if pd.isna(vix) or pd.isna(vix_ma10):
        vix_status = "UNKNOWN"
        allow = False
    elif vix > vix_ma10 and ma10_rising:
        vix_status = "🔴红灯"
        allow = False
    elif vix < vix_ma10:
        vix_status = "🟢绿灯"
        allow = True
    else:
        vix_status = "🟡黄灯"
        allow = True
    
    # 个股条件
    iv_cond = "GREEN" if pd.notna(iv) and 30 <= iv <= 50 else "YELLOW" if pd.notna(iv) and (iv < 30 or iv <= 65) else "RED"
    iv_hv_cond = "GREEN" if pd.notna(iv_hv) and 100 <= iv_hv <= 140 else "YELLOW" if pd.notna(iv_hv) else "RED"
    
    # 决策
    if not allow:
        decision = "❌禁止"
        reason = "VIX趋势不利"
    elif iv_cond == "RED" or iv_hv_cond == "RED":
        decision = "❌禁止"
        reason = "IV条件不利"
    elif iv_cond == "GREEN" and iv_hv_cond == "GREEN":
        decision = "✅开仓"
        reason = "条件满足"
    else:
        decision = "⚠️试探"
        reason = "部分条件满足"
    
    return vix_status, iv_cond, iv_hv_cond, decision, reason

def calculate_vertical_spread(symbol, data, vix):
    """计算垂直价差推荐"""
    if data is None:
        return None
    
    price = data['price']
    iv = data['iv']
    expiries = data.get('expiries', [])
    
    if pd.isna(price) or not expiries:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        opt = ticker.option_chain(expiries[0])
        puts = opt.puts
        
        if puts.empty:
            return None
        
        # Bull Put Spread: 卖出高执行价PUT，买入低执行价PUT
        # 选ATM附近作为short strike
        strikes = puts['strike'].sort_values().values
        atm = min(strikes, key=lambda x: abs(x - price))
        
        # 找到ATM位置
        idx = np.argmin(np.abs(strikes - atm))
        
        # Short Strike: ATM 或略低
        short_strike = strikes[idx] if strikes[idx] < price else strikes[idx - 1] if idx > 0 else strikes[idx]
        
        # Long Strike: Short - 15~25点
        long_strike = short_strike - 20
        
        # 确保Long Strike存在
        if long_strike < strikes.min():
            long_strike = strikes[0]
        
        spread_width = short_strike - long_strike
        
        # 估算权利金 (简化)
        short_premium = puts[puts['strike'] == short_strike]['bid'].mean() if 'bid' in puts.columns else 0
        long_premium = puts[puts['strike'] == long_strike]['ask'].mean() if 'ask' in puts.columns else 0
        
        credit = (short_premium - long_premium) * 100 if pd.notna(short_premium) and pd.notna(long_premium) else 0
        
        return {
            'short_strike': short_strike,
            'long_strike': long_strike,
            'width': spread_width,
            'credit': credit,
            'expiry': expiries[0],
            'max_loss': spread_width * 100 - credit
        }
    except Exception as e:
        return None

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vertical_spreads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        RunDateTime TEXT,
        Symbol TEXT,
        Price REAL,
        IV REAL,
        HV REAL,
        IV_HV_Ratio REAL,
        VIX_Level REAL,
        VIX_Status TEXT,
        IV_Condition TEXT,
        IV_HV_Condition TEXT,
        Decision TEXT,
        Reason TEXT,
        Short_Strike REAL,
        Long_Strike REAL,
        Spread_Width REAL,
        Credit REAL,
        Max_Loss REAL,
        Expiry TEXT
    )''')
    conn.commit()
    return conn

def save_signal(conn, data):
    """保存信号"""
    c = conn.cursor()
    c.execute('''INSERT INTO vertical_spreads (
        RunDateTime, Symbol, Price, IV, HV, IV_HV_Ratio, VIX_Level, VIX_Status,
        IV_Condition, IV_HV_Condition, Decision, Reason, Short_Strike, Long_Strike,
        Spread_Width, Credit, Max_Loss, Expiry
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        data['symbol'], data['price'], data['iv'], data['hv'], data['iv_hv'],
        data['vix'], data['vix_status'], data['iv_cond'], data['iv_hv_cond'],
        data['decision'], data['reason'], data.get('short_strike'), 
        data.get('long_strike'), data.get('width'), data.get('credit'),
        data.get('max_loss'), data.get('expiry')
    ))
    conn.commit()

def main():
    print("="*60)
    print("🚀 垂直价差推荐策略扫描")
    print("="*60)
    
    setup_proxy()
    
    # 获取VIX
    print("\n📊 获取VIX数据...")
    vix, vix_ma10, ma10_rising = get_vix_data()
    print(f"   VIX: {vix:.2f} | MA10: {vix_ma10:.2f} | 趋势: {'↑' if ma10_rising else '↓'}")
    
    vix_status = "🔴" if vix > vix_ma10 and ma10_rising else "🟢" if vix < vix_ma10 else "🟡"
    print(f"   状态: {vix_status}")
    
    # 扫描标的
    results = []
    print(f"\n🔍 扫描 {len(STOCKS)} 个标的...\n")
    
    for symbol in STOCKS:
        data = get_stock_data(symbol)
        
        if data is None:
            print(f"  {symbol}: ❌ 数据获取失败")
            continue
        
        vs = check_decision(vix, vix_ma10, ma10_rising, data['iv'], data['iv_hv'])
        
        result = {
            'symbol': symbol,
            'price': data['price'],
            'iv': data['iv'],
            'hv': data['hv'],
            'iv_hv': data['iv_hv'],
            'vix': vix,
            'vix_status': vs[0],
            'iv_cond': vs[1],
            'iv_hv_cond': vs[2],
            'decision': vs[3],
            'reason': vs[4]
        }
        
        # 计算价差
        spread = calculate_vertical_spread(symbol, data, vix)
        if spread:
            result.update(spread)
        
        results.append(result)
        
        # 输出
        iv_str = f"{data['iv']:.1f}%" if pd.notna(data['iv']) else "N/A"
        hv_str = f"{data['hv']:.1f}%" if pd.notna(data['hv']) else "N/A"
        iv_hv_str = f"{data['iv_hv']:.0f}%" if pd.notna(data['iv_hv']) else "N/A"
        
        print(f"  {vs[3]} {symbol:5s} \${data['price']:8.2f}  IV:{iv_str:>6s}  HV:{hv_str:>6s}  IV/HV:{iv_hv_str:>5s}")
    
    # 保存到数据库
    conn = init_db()
    for r in results:
        save_signal(conn, r)
    conn.close()
    
    print(f"\n✅ 信号已保存到: {DB_PATH}")
    
    # 推荐总结
    print("\n" + "="*60)
    print("📋 推荐总结")
    print("="*60)
    
    # 排序: 开仓 > 试探 > 禁止
    results.sort(key=lambda x: (x['decision'] == "✅开仓", x['decision'] == "⚠️试探", x['decision'] == "❌禁止"), reverse=True)
    
    for r in results:
        if r['decision'].startswith("✅"):
            print(f"\n✅ {r['symbol']} - Bull Put Spread 推荐")
            print(f"   价格: ${r['price']:.2f}")
            if 'short_strike' in r:
                print(f"   Short Strike: ${r['short_strike']:.2f}")
                print(f"   Long Strike:  ${r['long_strike']:.2f}")
                print(f"   价差宽度: ${r['width']:.2f}")
                print(f"   收取权利金: ${r['credit']:.2f}")
                print(f"   最大损失: ${r['max_loss']:.2f}")
                print(f"   到期日: {r.get('expiry', 'N/A')}")
    
    green_count = sum(1 for r in results if r['decision'].startswith("✅"))
    yellow_count = sum(1 for r in results if r['decision'].startswith("⚠️"))
    red_count = sum(1 for r in results if r['decision'].startswith("❌"))
    
    print(f"\n📊 统计: ✅开仓 {green_count} | ⚠️试探 {yellow_count} | ❌禁止 {red_count}")

if __name__ == "__main__":
    main()
