#!/usr/bin/env python3
"""
Backtrader 期权回测 - 进阶版
支持 Bull Put Spread / Bull Call Spread 等期权策略
"""

import backtrader as bt
import yfinance as yf
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import json

PROXY = 'http://127.0.0.1:7897'

DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/backtest.db'

# ==================== 期权定价 ====================

def black_scholes_call(S, K, T, r=0.05, sigma=0.3):
    """Black-Scholes 看涨期权定价"""
    from scipy.stats import norm
    if T <= 0:
        return max(S - K, 0)
    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

def black_scholes_put(S, K, T, r=0.05, sigma=0.3):
    """Black-Scholes 看跌期权定价"""
    from scipy.stats import norm
    if T <= 0:
        return max(K - S, 0)
    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)


# ==================== 期权策略 ====================

class BullPutSpread(bt.Strategy):
    """Bull Put Spread 回测策略"""
    
    params = (
        ('short_strike', None),   # 卖出行权价
        ('long_strike', None),    # 买进行权价
        ('expiry_days', 30),       # 到期天数
        ('iv', 0.30),              # 隐含波动率
    )
    
    def __init__(self):
        self.order = None
        self.entry_date = None
        self.entry_spread = None
        
        # 标的资产
        self.symbol = self.datas[0]
        
    def log(self, txt):
        print(f'{self.symbol.datetime.date(0)} {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'BUY {order.executed.size} @ ${order.executed.price:.2f}')
            else:
                self.log(f'SELL {order.executed.size} @ ${order.executed.price:.2f}')
        self.order = None
    
    def next(self):
        if self.order:
            return
        
        current_price = self.symbol.close[0]
        days_held = 0
        if self.entry_date:
            days_held = (self.symbol.datetime.date(0) - self.entry_date).days
        
        # 刚入场
        if not self.position and self.params.short_strike:
            # 开仓条件: 价格在行权价附近
            if current_price > self.params.short_strike * 0.95:
                # 计算价差
                T = self.params.expiry_days / 365
                short_premium = black_scholes_put(
                    current_price, self.params.short_strike, T, sigma=self.params.iv
                )
                long_premium = black_scholes_put(
                    current_price, self.params.long_strike, T, sigma=self.params.iv
                )
                spread = short_premium - long_premium
                
                self.entry_spread = spread
                self.entry_date = self.symbol.datetime.date(0)
                
                # 卖出价差 (做空)
                self.order = self.sell()
                self.log(f'Opened Bull Put Spread: ${spread:.2f}')
        
        # 持仓中
        elif self.position:
            # 计算当前价差
            T = max((self.params.expiry_days - days_held) / 365, 0.001)
            short_premium = black_scholes_put(
                current_price, self.params.short_strike, T, sigma=self.params.iv
            )
            long_premium = black_scholes_put(
                current_price, self.params.long_strike, T, sigma=self.params.iv
            )
            current_spread = short_premium - long_premium
            pnl = 0  # 默认值
            
            # 到期或止盈/止损
            if days_held >= self.params.expiry_days:
                # 到期结算
                pnl = self.entry_spread - current_spread
                self.order = self.buy()  # 平仓
                self.log(f'Expired: PnL = ${pnl:.2f}')
                self.entry_date = None
            elif self.entry_spread > 0:
                pnl = (self.entry_spread - current_spread) / self.entry_spread
                if pnl > 0.5:  # 盈利 50%
                    pnl_amt = self.entry_spread - current_spread
                    self.order = self.buy()
                    self.log(f'Take Profit: ${pnl_amt:.2f}')
                    self.entry_date = None
                elif pnl < -0.3:  # 亏损 30%
                    pnl_amt = self.entry_spread - current_spread
                    self.order = self.buy()
                    self.log(f'Stop Loss: ${pnl_amt:.2f}')
                    self.entry_date = None


class BuyAndHold(bt.Strategy):
    """买入持有策略 (基准)"""
    
    params = (
        ('target_allocation', 0.95),  # 目标仓位
    )
    
    def __init__(self):
        self.order = None
        
    def next(self):
        if self.order:
            return
        
        # 首次建仓
        if not self.position:
            size = int((self.broker.getvalue() * self.params.target_allocation) / self.data.close[0])
            if size > 0:
                self.order = self.buy(size=size)


# ==================== 回测引擎 ====================

def run_backtest_bull_put_spread(
    symbol='TSLA',
    short_strike=380,
    long_strike=365,
    expiry_days=30,
    iv=0.35,
    start_date='2025-01-01',
    end_date='2026-03-14',
    initial_cash=100000
):
    """运行 Bull Put Spread 回测"""
    
    print("=" * 60)
    print(f"Bull Put Spread 回测: {symbol}")
    print(f"Short Strike: ${short_strike} | Long Strike: ${long_strike}")
    print(f"到期天数: {expiry_days}天 | IV: {iv*100:.0f}%")
    print(f"期间: {start_date} ~ {end_date}")
    print("=" * 60)
    
    # 获取数据
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date)
    
    if df.empty:
        print(f"无数据: {symbol}")
        return None
    
    # 创建 Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% 佣金
    
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
    
    # 添加策略
    cerebro.addstrategy(
        BullPutSpread,
        short_strike=short_strike,
        long_strike=long_strike,
        expiry_days=expiry_days,
        iv=iv
    )
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # 打印初始资金
    print(f"\n初始资金: ${cerebro.broker.getvalue():,.2f}")
    
    # 运行回测
    results = cerebro.run()
    
    # 获取结果
    strat = results[0]
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    # 打印结果
    print(f"最终资金: ${cerebro.broker.getvalue():,.2f}")
    print(f"\n📊 绩效指标:")
    print(f"  总收益: {returns.get('rtot', 0)*100:.2f}%")
    print(f"  年化收益: {returns.get('rnorm100', 0):.2f}%")
    print(f"  夏普比率: {sharpe.get('sharperatio', 'N/A')}")
    print(f"  最大回撤: {dd.get('max', {}).get('drawdown', 0):.2f}%")
    
    # 交易统计
    if trades.get('total'):
        print(f"\n📈 交易统计:")
        print(f"  总交易数: {trades['total'].get('total', 0)}")
        print(f"  盈利交易: {trades['won'].get('total', 0) if 'won' in trades else 0}")
        print(f"  亏损交易: {trades['lost'].get('total', 0) if 'lost' in trades else 0}")
    
    return {
        'final_value': cerebro.broker.getvalue(),
        'total_return': returns.get('rtot', 0),
        'annualized_return': returns.get('rnorm100', 0),
        'sharpe_ratio': sharpe.get('sharperatio', 0),
        'max_drawdown': dd.get('max', {}).get('drawdown', 0),
    }


def compare_strategies():
    """对比多个策略"""
    
    results = []
    
    # 策略1: Bull Put Spread (保守)
    r1 = run_backtest_bull_put_spread(
        symbol='TSLA',
        short_strike=400,
        long_strike=380,
        expiry_days=30,
        iv=0.35,
        start_date='2025-01-01',
        end_date='2026-03-14',
        initial_cash=100000
    )
    if r1:
        r1['strategy'] = 'Bull Put Spread (保守)'
        results.append(r1)
    
    print("\n" + "="*60)
    
    # 策略2: Bull Put Spread (激进)
    r2 = run_backtest_bull_put_spread(
        symbol='TSLA',
        short_strike=420,
        long_strike=390,
        expiry_days=45,
        iv=0.40,
        start_date='2025-01-01',
        end_date='2026-03-14',
        initial_cash=100000
    )
    if r2:
        r2['strategy'] = 'Bull Put Spread (激进)'
        results.append(r2)
    
    # 对比结果
    print("\n" + "="*60)
    print("📊 策略对比")
    print("="*60)
    for r in results:
        print(f"\n{r['strategy']}:")
        print(f"  总收益: {r['total_return']*100:.2f}%")
        print(f"  年化: {r['annualized_return']:.2f}%")
        print(f"  夏普: {r['sharpe_ratio']:.2f}")
        print(f"  回撤: {r['max_drawdown']:.2f}%")
    
    return results


if __name__ == '__main__':
    print("=" * 60)
    print("Backtrader 期权策略回测")
    print("=" * 60)
    
    # 运行对比回测
    results = compare_strategies()
    
    # 保存结果到数据库
    if results:
        conn = sqlite3.connect(DB_PATH)
        for r in results:
            conn.execute('''
                INSERT INTO backtest_results 
                (strategy_name, symbol, start_date, end_date, total_return, 
                 annualized_return, sharpe_ratio, max_drawdown)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                r['strategy'], 'TSLA', '2025-01-01', '2026-03-14',
                r['total_return'], r['annualized_return'], 
                r['sharpe_ratio'], r['max_drawdown']/100
            ))
        conn.commit()
        conn.close()
        print("\n✅ 结果已保存到 backtest.db")
