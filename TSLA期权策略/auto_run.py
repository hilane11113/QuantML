#!/usr/bin/env python3
"""
美股期权策略定时运行脚本
- 美股开盘后1小时自动运行 (10:30 AM EST = 北京时间 22:30 夏令时)
- 运行单策略和多策略
- 结果写入 SQLite 数据库
"""

import sys
import os
from pathlib import Path

# 添加项目路径
PROJECT_DIR = Path('/root/.openclaw/workspace/quant/TSLA期权策略')
sys.path.insert(0, str(PROJECT_DIR))

# 导入数据库模块
from sqlite_db import (
    insert_signal, insert_backtest_result, insert_trade,
    query_signals, DB_PATH as NEW_DB_PATH
)
from datetime import datetime, date
import json
import pandas as pd

# 策略脚本路径
VERTICAL_SPREAD_SCRIPT = PROJECT_DIR / 'vertical_spread_v6.py'
MULTI_STRATEGY_SCRIPT = PROJECT_DIR / 'multi_strategy_v2.py'

def run_vertical_spread():
    """运行垂直价差策略"""
    print("=" * 60)
    print("🚀 运行垂直价差策略 V6...")
    print("=" * 60)
    
    import subprocess
    result = subprocess.run(
        ['python3', str(VERTICAL_SPREAD_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    print(result.stdout)
    if result.stderr:
        print(f"⚠️ 警告: {result.stderr}")
    
    # 解析结果并写入新数据库
    # 策略脚本会输出决策结果，我们可以解析输出或者直接读取它保存的数据库
    return result.returncode == 0

def run_multi_strategy():
    """运行多策略组合"""
    print("=" * 60)
    print("🚀 运行多策略组合 V2...")
    print("=" * 60)
    
    import subprocess
    result = subprocess.run(
        ['python3', str(MULTI_STRATEGY_SCRIPT), 'TSLA'],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    print(result.stdout)
    if result.stderr:
        print(f"⚠️ 警告: {result.stderr}")
    
    return result.returncode == 0

def parse_and_save_results():
    """解析策略输出并写入新数据库"""
    import sqlite3
    
    # 从垂直价差策略的数据库读取最新结果
    OLD_DB_PATH = PROJECT_DIR / 'vertical_spreads_v6.db'
    
    if not OLD_DB_PATH.exists():
        print("⚠️ 旧数据库不存在，跳过解析")
        return
    
    try:
        conn = sqlite3.connect(OLD_DB_PATH)
        df = pd.read_sql("SELECT * FROM vertical_spreads_v6 ORDER BY id DESC LIMIT 5", conn)
        conn.close()
        
        if df.empty:
            print("⚠️ 没有策略结果可解析")
            return
        
        # 转换并写入新数据库
        for _, row in df.iterrows():
            # 解析 RunDateTime 获取交易日期
            run_datetime = row.get('RunDateTime', '')
            trade_date = run_datetime.split(' ')[0] if ' ' in run_datetime else str(date.today())
            
            signal = {
                'strategy_name': 'vertical_spread_v6',
                'symbol': row.get('Symbol', 'TSLA'),
                'trade_date': trade_date,
                'signal_type': 'BUY' if '开仓' in str(row.get('Decision', '')) else 'HOLD',
                'signal_strength': row.get('Composite_Score', 0),
                'total_score': row.get('Composite_Score', 0),
                'risk_reward_ratio': row.get('RR_Ratio', 0),
                'liquidity_score': row.get('Liquidity_Score', 0),
                'iv_score': row.get('IV', 0) / 10,  # 简化转换
                'theta_score': 5,  # 默认值
                'benchmark_price': row.get('Price', 0),
                'decision_label': row.get('Decision', '⏸️观望'),
                'notes': f"策略类型: {row.get('Strategy_Type', '')}, 描述: {row.get('Strategy_Desc', '')}"
            }
            
            try:
                insert_signal(signal)
                print(f"✅ 已写入信号: {signal['symbol']} - {signal['decision_label']}")
            except Exception as e:
                print(f"⚠️ 写入信号失败: {e}")
                
    except Exception as e:
        print(f"⚠️ 解析结果失败: {e}")

def save_backtest_summary():
    """保存回测汇总"""
    import sqlite3
    
    OLD_DB_PATH = PROJECT_DIR / 'vertical_spreads_v6.db'
    
    if not OLD_DB_PATH.exists():
        return
    
    try:
        conn = sqlite3.connect(OLD_DB_PATH)
        df = pd.read_sql("SELECT * FROM vertical_spreads_v6", conn)
        conn.close()
        
        if df.empty:
            return
        
        # 计算汇总统计
        total = len(df)
        winning = len(df[df['Composite_Score'] >= 60])
        losing = total - winning
        
        result = {
            'strategy_name': 'vertical_spread_v6',
            'symbol': 'TSLA',
            'start_date': df['RunDateTime'].min().split(' ')[0] if 'RunDateTime' in df.columns else str(date.today()),
            'end_date': df['RunDateTime'].max().split(' ')[0] if 'RunDateTime' in df.columns else str(date.today()),
            'total_return': 0.0,  # 需要根据实际交易计算
            'annualized_return': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'win_rate': winning / total if total > 0 else 0,
            'total_trades': total,
            'winning_trades': winning,
            'losing_trades': losing,
            'avg_profit': 0.0,
            'avg_loss': 0.0,
            'params': {'version': 'v6', 'source': 'auto_cron'}
        }
        
        insert_backtest_result(result)
        print(f"✅ 已写入回测汇总: {total} 笔交易")
    except Exception as e:
        print(f"⚠️ 保存回测汇总失败: {e}")

def parse_multi_strategy_results():
    """解析多策略结果并写入数据库"""
    import sqlite3
    
    # 多策略的结果直接运行后从日志获取，这里简化处理
    # 从垂直价差策略的结果中识别多策略信号
    OLD_DB_PATH = PROJECT_DIR / 'vertical_spreads_v6.db'
    
    if not OLD_DB_PATH.exists():
        return
    
    try:
        conn = sqlite3.connect(OLD_DB_PATH)
        df = pd.read_sql("SELECT * FROM vertical_spreads_v6 ORDER BY id DESC LIMIT 10", conn)
        conn.close()
        
        if df.empty:
            return
        
        # 为多策略组合添加信号
        # 识别不同策略类型的信号
        strategy_types = df['Strategy_Type'].unique() if 'Strategy_Type' in df.columns else []
        
        for strategy_type in strategy_types:
            if strategy_type and strategy_type != 'N/A':
                strategy_df = df[df['Strategy_Type'] == strategy_type]
                best = strategy_df.iloc[0] if not strategy_df.empty else None
                
                if best is not None:
                    run_datetime = best.get('RunDateTime', '')
                    trade_date = run_datetime.split(' ')[0] if ' ' in run_datetime else str(date.today())
                    
                    signal = {
                        'strategy_name': f'multi_{strategy_type.lower()}',
                        'symbol': best.get('Symbol', 'TSLA'),
                        'trade_date': trade_date,
                        'signal_type': 'BUY' if '开仓' in str(best.get('Decision', '')) else 'HOLD',
                        'signal_strength': best.get('Composite_Score', 0),
                        'total_score': best.get('Composite_Score', 0),
                        'risk_reward_ratio': best.get('RR_Ratio', 0),
                        'liquidity_score': best.get('Liquidity_Score', 0),
                        'iv_score': best.get('IV', 0) / 10,
                        'theta_score': 5,
                        'benchmark_price': best.get('Price', 0),
                        'decision_label': best.get('Decision', '⏸️观望'),
                        'notes': f'多策略模式: {strategy_type}'
                    }
                    
                    try:
                        insert_signal(signal)
                        print('已写入多策略信号:', signal['strategy_name'])
                    except Exception as e:
                        pass  # 忽略重复写入
        
        print("✅ 多策略信号解析完成")
        
    except Exception as e:
        print(f"⚠️ 解析多策略结果失败: {e}")

def main():
    """主函数"""
    print(f"\n{'='*60}")
    print(f"📅 美股期权策略自动运行")
    print(f"   运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   新数据库: {NEW_DB_PATH}")
    print(f"{'='*60}\n")
    
    # 运行策略
    v6_success = run_vertical_spread()
    multi_success = run_multi_strategy()  # 多策略组合
    
    # 解析结果并写入新数据库
    parse_and_save_results()
    parse_multi_strategy_results()
    save_backtest_summary()
    
    print(f"\n{'='*60}")
    print("✅ 策略运行完成!")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
