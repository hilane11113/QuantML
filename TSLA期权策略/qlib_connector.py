#!/usr/bin/env python3
"""
期权策略回测数据库对接 Qlib 示例
标的: TSLA (特斯拉)
基准价: 美股开盘后1小时 (约10:00 AM EST)
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, date
import json

# ============================================================
# 数据库配置 (使用环境变量或配置文件)
# ============================================================

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'options_backtest',
    'user': 'your_user',
    'password': 'your_password'
}

# ============================================================
# 基准价计算
# ============================================================

def calculate_benchmark_price(df_intraday, method='vwap'):
    """
    计算美股开盘后1小时的基准价
    
    参数:
        df_intraday: 包含日内数据的DataFrame，需包含timestamp, price, volume列
        method: 计算方法
            - 'vwap': 成交量加权平均价
            - 'close': 1小时收盘价
            - 'twap': 时间加权平均价
    
    返回:
        benchmark_price: 基准价
    """
    # 假设数据已经过滤到 9:30 - 10:00 EST 时段
    if method == 'vwap':
        return (df_intraday['price'] * df_intraday['volume']).sum() / df_intraday['volume'].sum()
    elif method == 'twap':
        return df_intraday['price'].mean()
    elif method == 'close':
        return df_intraday['price'].iloc[-1]
    else:
        raise ValueError(f"Unknown method: {method}")


def get_benchmark_from_options_chain(conn, symbol='TSLA', trade_date=None):
    """
    从期权链数据获取基准价 (使用标的资产价格)
    期权链数据通常包含 underlying_price 字段
    """
    query = f"""
        SELECT DISTINCT ON (date) 
            date, 
            underlying_price as benchmark_price
        FROM option_chain
        WHERE symbol = '{symbol}'
        AND date = '{trade_date}'
        ORDER BY date, open_interest DESC
    """
    df = pd.read_sql(query, conn)
    return df


# ============================================================
# Qlib 数据格式转换
# ============================================================

def to_qlib_format(df, symbol='TSLA'):
    """
    将数据库数据转换为 Qlib 格式
    
    Qlib 日线数据格式:
    date,open,high,low,close,volume
    
    扩展格式 (包含基准价):
    date,open,high,low,close,volume,benchmark_price
    """
    qlib_df = df.copy()
    
    # 确保日期格式正确
    qlib_df['date'] = pd.to_datetime(qlib_df['date'])
    qlib_df.set_index('date', inplace=True)
    
    # 选择 Qlib 需要的列
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    
    # 如果有基准价，添加到最后一列
    if 'benchmark_price' in qlib_df.columns:
        qlib_df['benchmark_price($' + symbol + ')'] = qlib_df['benchmark_price']
        qlib_df.drop('benchmark_price', axis=1, inplace=True)
    
    return qlib_df[required_cols]


def export_to_qlib_csv(df, output_path):
    """
    导出为 Qlib CSV 格式
    """
    df.to_csv(output_path)
    print(f"Exported to Qlib format: {output_path}")


# ============================================================
# 策略信号数据结构
# ============================================================

def create_signal_record(
    strategy_name: str,
    trade_date: date,
    signal_type: str,
    score: float,
    leg1: dict = None,
    leg2: dict = None,
    benchmark_price: float = None,
    **kwargs
) -> dict:
    """
    创建策略信号记录
    
    参数:
        strategy_name: 策略名称
        trade_date: 交易日期
        signal_type: 信号类型 (BUY, SELL, CLOSE, HOLD)
        score: 策略评分
        leg1: 第一腿信息 {'type': 'C', 'action': 'SELL', 'strike': 400, 'expiry': date}
        leg2: 第二腿信息
        benchmark_price: 基准价
        **kwargs: 其他字段
    
    返回:
        dict: 信号记录
    """
    record = {
        'strategy_name': strategy_name,
        'symbol': 'TSLA',
        'date': trade_date.isoformat() if isinstance(trade_date, date) else trade_date,
        'signal_type': signal_type,
        'signal_strength': score,
        'benchmark_price': benchmark_price,
        'created_at': datetime.now().isoformat()
    }
    
    # 添加策略详情
    if leg1:
        record.update({
            'leg1_type': leg1.get('type'),
            'leg1_action': leg1.get('action'),
            'leg1_strike': leg1.get('strike'),
            'leg1_expiry': leg1.get('expiry').isoformat() if isinstance(leg1.get('expiry'), date) else leg1.get('expiry')
        })
    
    if leg2:
        record.update({
            'leg2_type': leg2.get('type'),
            'leg2_action': leg2.get('action'),
            'leg2_strike': leg2.get('strike'),
            'leg2_expiry': leg2.get('expiry').isoformat() if isinstance(leg2.get('expiry'), date) else leg2.get('expiry')
        })
    
    # 添加额外参数
    record.update(kwargs)
    
    return record


# ============================================================
# 回测结果记录
# ============================================================

def create_backtest_result(
    strategy_name: str,
    start_date: date,
    end_date: date,
    trades: list,
    benchmark_time: time = time(10, 0),
    **metrics
) -> dict:
    """
    创建回测结果记录
    """
    # 计算绩效指标
    winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]
    
    total_pnl = sum(t.get('pnl', 0) for t in trades)
    total_return = total_pnl / sum(t.get('entry_price', 1) * t.get('quantity', 1) * 100 for t in trades)
    
    result = {
        'strategy_name': strategy_name,
        'symbol': 'TSLA',
        'start_date': start_date.isoformat() if isinstance(start_date, date) else start_date,
        'end_date': end_date.isoformat() if isinstance(end_date, date) else end_date,
        'benchmark_time': benchmark_time.isoformat(),
        
        # 绩效指标
        'total_return': total_return,
        'annualized_return': total_return * 252 / max(len(trades), 1),
        'sharpe_ratio': metrics.get('sharpe_ratio', 0),
        'max_drawdown': metrics.get('max_drawdown', 0),
        'win_rate': len(winning_trades) / len(trades) if trades else 0,
        
        # 交易统计
        'total_trades': len(trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        
        # 平均盈亏
        'avg_profit': np.mean([t.get('pnl', 0) for t in winning_trades]) if winning_trades else 0,
        'avg_loss': np.mean([t.get('pnl', 0) for t in losing_trades]) if losing_trades else 0,
        
        'created_at': datetime.now().isoformat()
    }
    
    return result


# ============================================================
# 多策略组合
# ============================================================

def create_portfolio_config(
    portfolio_name: str,
    strategies: list,
    capital: float = 100000,
    rebalance: str = 'weekly'
) -> dict:
    """
    创建多策略组合配置
    
    参数:
        portfolio_name: 组合名称
        strategies: 策略列表 
            [
                {'name': 'vertical_spread', 'weight': 0.4, 'params': {...}},
                {'name': 'iron_condor', 'weight': 0.3, 'params': {...}},
                {'name': 'bull_call', 'weight': 0.3, 'params': {...}}
            ]
        capital: 总资金
        rebalance: 调仓频率
    """
    # 验证权重总和
    total_weight = sum(s.get('weight', 0) for s in strategies)
    if abs(total_weight - 1.0) > 0.01:
        raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
    
    config = {
        'portfolio_name': portfolio_name,
        'strategies': strategies,
        'capital_allocation': capital,
        'rebalance_frequency': rebalance,
        'created_at': datetime.now().isoformat()
    }
    
    return config


# ============================================================
# 示例: 使用现有数据
# ============================================================

if __name__ == '__main__':
    # 模拟数据
    sample_trades = [
        {'entry_price': 2.50, 'quantity': 1, 'pnl': 150, 'date': '2026-02-04'},
        {'entry_price': 3.00, 'quantity': 1, 'pnl': -80, 'date': '2026-02-11'},
        {'entry_price': 2.80, 'quantity': 1, 'pnl': 220, 'date': '2026-02-21'},
    ]
    
    # 创建回测结果
    result = create_backtest_result(
        strategy_name='vertical_spread_v6',
        start_date=date(2026, 2, 1),
        end_date=date(2026, 3, 14),
        trades=sample_trades,
        benchmark_time=time(10, 0),
        sharpe_ratio=1.85,
        max_drawdown=0.12
    )
    
    print("=== 回测结果 ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 创建信号
    signal = create_signal_record(
        strategy_name='vertical_spread_v6',
        trade_date=date(2026, 3, 14),
        signal_type='BUY',
        score=75.5,
        benchmark_price=263.50,
        leg1={'type': 'P', 'action': 'SELL', 'strike': 250, 'expiry': date(2026, 4, 18)},
        leg2={'type': 'P', 'action': 'BUY', 'strike': 240, 'expiry': date(2026, 4, 18)},
        risk_reward_ratio=2.5,
        liquidity_score=80,
        iv_score=65
    )
    
    print("\n=== 策略信号 ===")
    print(json.dumps(signal, indent=2, ensure_ascii=False))
    
    # 创建多策略组合
    portfolio = create_portfolio_config(
        portfolio_name='TSLA_Options_Combo',
        strategies=[
            {'name': 'vertical_spread', 'weight': 0.4, 'params': {'max_loss': 500}},
            {'name': 'iron_condor', 'weight': 0.3, 'params': {'width': 20}},
            {'name': 'bull_call', 'weight': 0.3, 'params': {'target_delta': 0.3}}
        ],
        capital=100000,
        rebalance='weekly'
    )
    
    print("\n=== 多策略组合 ===")
    print(json.dumps(portfolio, indent=2, ensure_ascii=False))
