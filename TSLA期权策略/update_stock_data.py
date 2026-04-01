#!/usr/bin/env python3
"""
qlib 股票数据更新脚本
- 使用 akshare 获取每日股票数据
- 存储到 SQLite 数据库
- 每日定时更新当天数据
"""

import sqlite3
import pandas as pd
from datetime import datetime, date
import os

DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/stock_data.db'

# 关注的股票列表
STOCKS = ['TSLA', 'NVDA', 'AMD', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META']

def init_stock_db():
    """初始化股票数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 股票日线数据
    c.execute('''
        CREATE TABLE IF NOT EXISTS stock_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            amount REAL,
            pct_change REAL,
            pre_close REAL,
            turnover_rate REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')
    
    # 指数数据
    c.execute('''
        CREATE TABLE IF NOT EXISTS index_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            pct_change REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')
    
    # VIX 数据
    c.execute('''
        CREATE TABLE IF NOT EXISTS vix_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            pct_change REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trade_date)
        )
    ''')
    
    # 创建索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_daily(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_stock_symbol ON stock_daily(symbol)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_index_date ON index_daily(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_vix_date ON vix_daily(trade_date)')
    
    conn.commit()
    conn.close()
    print(f"✅ 股票数据库初始化完成: {DB_PATH}")

def update_stock_data():
    """更新股票数据"""
    try:
        import akshare as ak
        
        conn = sqlite3.connect(DB_PATH)
        
        for symbol in STOCKS:
            try:
                # 尝试获取美股数据
                if symbol == 'TSLA':
                    df = ak.stock_us_spot_em()
                    df = df[df['代码'] == symbol]
                else:
                    # 使用 yfinance 作为备选
                    import yfinance as yf
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="5d")
                    
                    if hist.empty:
                        print(f"⚠️ {symbol} 无数据")
                        continue
                    
                    df = pd.DataFrame({
                        '日期': hist.index.strftime('%Y-%m-%d'),
                        '开盘': hist['Open'],
                        '收盘': hist['Close'],
                        '最高': hist['High'],
                        '最低': hist['Low'],
                        '成交量': hist['Volume']
                    })
                
                # 写入数据库
                for _, row in df.iterrows():
                    try:
                        conn.execute('''
                            INSERT OR REPLACE INTO stock_daily 
                            (symbol, trade_date, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            symbol,
                            row.get('日期', row.name),
                            row.get('开盘'),
                            row.get('最高'),
                            row.get('最低'),
                            row.get('收盘'),
                            row.get('成交量', 0)
                        ))
                    except:
                        pass
                
                conn.commit()
                print(f"✅ {symbol} 更新完成")
                
            except Exception as e:
                print(f"⚠️ {symbol} 更新失败: {e}")
        
        conn.close()
        print("✅ 股票数据更新完成")
        
    except ImportError:
        print("⚠️ 请安装 akshare: pip install akshare")

def update_vix_data():
    """更新 VIX 数据"""
    try:
        import yfinance as yf
        
        ticker = yf.Ticker("^VIX")
        hist = ticker.history(period="5d")
        
        if hist.empty:
            print("⚠️ VIX 无数据")
            return
        
        conn = sqlite3.connect(DB_PATH)
        
        for idx, row in hist.iterrows():
            trade_date = idx.strftime('%Y-%m-%d')
            conn.execute('''
                INSERT OR REPLACE INTO vix_daily 
                (trade_date, open, high, low, close)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                trade_date,
                row['Open'],
                row['High'],
                row['Low'],
                row['Close']
            ))
        
        conn.commit()
        conn.close()
        print("✅ VIX 数据更新完成")
        
    except Exception as e:
        print(f"⚠️ VIX 更新失败: {e}")

def get_latest_price(symbol):
    """获取最新价格"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT * FROM stock_daily WHERE symbol='{symbol}' ORDER BY trade_date DESC LIMIT 1",
        conn
    )
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_vix():
    """获取最新 VIX"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM vix_daily ORDER BY trade_date DESC LIMIT 1",
        conn
    )
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_stock_history(symbol, days=30):
    """获取历史数据"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT * FROM stock_daily WHERE symbol='{symbol}' ORDER BY trade_date DESC LIMIT {days}",
        conn
    )
    conn.close()
    return df

if __name__ == '__main__':
    print("=" * 50)
    print("📊 股票数据更新")
    print("=" * 50)
    
    # 初始化
    init_stock_db()
    
    # 更新数据
    update_stock_data()
    update_vix_data()
    
    # 显示最新数据
    print("\n📈 最新数据:")
    for symbol in STOCKS[:3]:
        latest = get_latest_price(symbol)
        if latest is not None:
            print(f"  {symbol}: ${latest['close']:.2f} ({latest['trade_date']})")
    
    vix = get_vix()
    if vix is not None:
        print(f"  VIX: {vix['close']:.2f} ({vix['trade_date']})")
