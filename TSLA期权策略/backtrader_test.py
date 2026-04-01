#!/usr/bin/env python3
"""
Backtrader 集成 - 期权策略回测
对接现有 vertical_spread_v6.py 的策略信号
"""

import backtrader as bt
import yfinance as yf
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os

PROXY = 'http://127.0.0.1:7897'

# 数据库路径
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/backtest.db'

class OptionStrategy(bt.Strategy):
    """期权策略基类"""
    
    params = (
        ('symbol', 'TSLA'),
        ('strike', None),
        ('expiry', None),
        ('option_type', 'call'),  # call or put
        ('position_size', 100),
    )
    
    def __init__(self):
        self.order = None
        self.entry_price = None
        self.entry_date = None
        
    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            elif order.issell():
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')
        
        self.order = None
    
    def next(self):
        if self.order:
            return
        
        # 获取标的当前价格
        current_price = self.data.close[0]
        
        # 检查是否到期
        if self.entry_date:
            days_held = (self.datas[0].datetime.date(0) - self.entry_date).days
            if days_held >= self.params.days_to_expiry:
                self.close()
                self.log(f'Option expired, closing position')
                return
        
        # 检查是否止损/止盈
        if self.entry_price:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            if pnl_pct > 50:  # 止盈 50%
                self.close()
                self.log(f'Take profit: {pnl_pct:.1f}%')
            elif pnl_pct < -30:  # 止损 30%
                self.close()
                self.log(f'Stop loss: {pnl_pct:.1f}%')


class BullPutSpreadStrategy(bt.Strategy):
    """Bull Put Spread 策略"""
    
    params = (
        ('short_strike', None),
        ('long_strike', None),
        ('expiry_days', 30),
        ('position_size', 1),
    )
    
    def __init__(self):
        self.order = None
        self.entry_date = None
        self.short_leg = None
        self.long_leg = None
        
    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')
    
    def next(self):
        # 简化的 Bull Put Spread 模拟
        # 实际需要期权定价模型
        pass


def run_backtest(strategy_name='vertical_spread_v6', 
                 start_date='2025-01-01',
                 end_date='2026-03-14',
                 initial_cash=100000):
    """运行回测"""
    
    cerebro = bt.Cerebro()
    
    # 设置初始资金
    cerebro.broker.setcash(initial_cash)
    
    # 添加策略
    cerebro.addstrategy(OptionStrategy)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    print(f"Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")
    
    # 运行回测
    results = cerebro.run()
    
    # 获取分析结果
    strat = results[0]
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    
    print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}")
    print(f"Total Return: {returns.get('rtot', 0)*100:.2f}%")
    print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
    print(f"Max Drawdown: {dd.get('max', {}).get('drawdown', 0):.2f}%")
    
    return results


def get_signals_from_db(symbol='TSLA', limit=10):
    """从数据库获取策略信号"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"""SELECT * FROM strategy_signals 
            WHERE symbol='{symbol}' 
            ORDER BY trade_date DESC LIMIT {limit}""",
        conn
    )
    conn.close()
    return df


def get_stock_data(symbol, start_date, end_date):
    """获取股票数据用于回测"""
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date)
    
    # 转换为 Backtrader 格式
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
        openinterest=-1
    )
    
    return data


def quick_backtest(symbol='TSLA', start_date='2025-01-01', end_date='2026-03-14'):
    """快速回测示例 - 简单买入持有"""
    
    print("=" * 60)
    print(f"快速回测: {symbol}")
    print(f"期间: {start_date} ~ {end_date}")
    print("=" * 60)
    
    cerebro = bt.Cerebro()
    
    # 获取数据
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date)
    
    if df.empty:
        print(f"无数据: {symbol}")
        return
    
    # 添加数据
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
    )
    cerebro.adddata(data)
    
    # 设置资金
    cerebro.broker.setcash(100000.0)
    
    # 买入信号策略 (简单示例)
    class SimpleStrategy(bt.Strategy):
        def __init__(self):
            self.order = None
            self.buy_price = None
            
        def next(self):
            if self.order:
                return
            
            # 每日收盘前买入
            if not self.position:
                self.order = self.buy()
    
    cerebro.addstrategy(SimpleStrategy)
    
    # 分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    print(f"初始资金: ${cerebro.broker.getvalue():,.2f}")
    
    results = cerebro.run()
    
    final_value = cerebro.broker.getvalue()
    strat = results[0]
    
    # 获取分析结果
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    
    print(f"\n最终资金: ${final_value:,.2f}")
    print(f"总收益: {returns.get('rtot', 0)*100:.2f}%")
    print(f"年化收益: {returns.get('rnorm100', 0):.2f}%")
    print(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")
    print(f"最大回撤: {dd.get('max', {}).get('drawdown', 0):.2f}%")
    
    return {
        'final_value': final_value,
        'total_return': returns.get('rtot', 0),
        'annualized_return': returns.get('rnorm100', 0),
        'sharpe_ratio': sharpe.get('sharperatio', 0),
        'max_drawdown': dd.get('max', {}).get('drawdown', 0)
    }


if __name__ == '__main__':
    print("=" * 60)
    print("Backtrader 期权回测")
    print("=" * 60)
    
    # 查看数据库中的信号
    print("\n📊 数据库中的策略信号:")
    signals = get_signals_from_db('TSLA')
    print(signals[['trade_date', 'strategy_name', 'signal_type', 'decision_label']].head())
    
    # 运行快速回测
    print("\n🚀 运行回测 (买入持有):")
    result = quick_backtest('TSLA', '2025-01-01', '2026-03-14')
