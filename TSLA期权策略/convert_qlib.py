#!/usr/bin/env python3
"""
将 stock_data.db 转换为 qlib 格式
qlib 格式: CSV文件，字段名为 $open, $high, $low, $close, $volume
"""

import sqlite3
import pandas as pd
from pathlib import Path
import os

STOCK_DB = '/root/.openclaw/workspace/quant/TSLA期权策略/stock_data.db'
QLIB_DATA_DIR = '/root/.openclaw/workspace/quant/TSLA期权策略/qlib_data/csv'

def convert_to_qlib_format():
    """转换为 qlib 格式"""
    
    conn = sqlite3.connect(STOCK_DB)
    
    # 获取所有股票
    stocks = conn.execute('SELECT DISTINCT symbol FROM stock_daily').fetchall()
    stocks = [s[0] for s in stocks]
    
    print(f"转换 {len(stocks)} 只股票到 qlib 格式...")
    
    for symbol in stocks:
        # 获取历史数据
        df = pd.read_sql(
            f"SELECT * FROM stock_daily WHERE symbol='{symbol}' ORDER BY trade_date",
            conn,
            parse_dates=['trade_date']
        )
        
        if df.empty:
            continue
        
        # 转换为 qlib 格式
        qlib_df = pd.DataFrame({
            '$open': df['open'],
            '$high': df['high'],
            '$low': df['low'],
            '$close': df['close'],
            '$volume': df['volume'],
            '$amount': df['amount'] if 'amount' in df.columns else 0
        })
        qlib_df.index = pd.to_datetime(df['trade_date'])
        qlib_df.index.name = 'date'
        
        # 创建目录
        stock_dir = Path(QLIB_DATA_DIR) / symbol
        stock_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存 CSV
        csv_path = stock_dir / f'{symbol}.csv'
        qlib_df.to_csv(csv_path)
        
        print(f"  ✅ {symbol}: {len(qlib_df)} 条 -> {csv_path}")
    
    conn.close()
    print(f"\n✅ 转换完成! 数据保存在: {QLIB_DATA_DIR}")

def get_qlib_data(symbol, start_date=None, end_date=None):
    """读取 qlib 格式数据"""
    csv_path = Path(QLIB_DATA_DIR) / symbol / f'{symbol}.csv'
    
    if not csv_path.exists():
        return None
    
    df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
    
    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]
    
    return df

if __name__ == '__main__':
    print("=" * 50)
    print("📊 转换为 qlib 格式")
    print("=" * 50)
    
    convert_to_qlib_format()
    
    # 测试读取
    print("\n📈 测试读取 qlib 数据:")
    df = get_qlib_data('TSLA', start_date='2026-03-01')
    if df is not None:
        print(df.tail())
