#!/usr/bin/env python3
"""
Backtrader 期权回测 - 真实数据版
使用 yfinance 获取真实期权价格
"""

import backtrader as bt
import yfinance as yf
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

PROXY = 'http://127.0.0.1:7897'

DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/backtest.db'


def get_real_option_chain(symbol='TSLA', expiry_date=None):
    """获取真实期权链数据"""
    ticker = yf.Ticker(symbol)
    
    # 获取所有到期日
    expirations = ticker.options
    
    if not expirations:
        print(f"⚠️ {symbol} 没有期权数据")
        return None
    
    # 选择最近的到期日
    if expiry_date is None:
        expiry_date = expirations[0]
    
    # 获取该到期日的期权链
    opt = ticker.option_chain(expiry_date)
    
    return {
        'calls': opt.calls,
        'puts': opt.puts,
        'expiry': expiry_date
    }


def get_option_price(symbol, strike, expiry, option_type='call'):
    """获取指定期权的实时价格"""
    ticker = yf.Ticker(symbol)
    
    try:
        opt = ticker.option_chain(expiry)
        
        if option_type == 'call':
            df = opt.calls
        else:
            df = opt.puts
        
        # 找到对应行权价
        row = df[df['strike'] == strike]
        
        if row.empty:
            return None
        
        # 返回中间价
        bid = row['bid'].values[0]
        ask = row['ask'].values[0]
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else row['lastPrice'].values[0]
        
        return {
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'last': row['lastPrice'].values[0],
            'iv': row['impliedVolatility'].values[0] if 'impliedVolatility' in row.columns else None,
            'oi': row['openInterest'].values[0],
            'volume': row['volume'].values[0]
        }
    except Exception as e:
        print(f"获取期权价格失败: {e}")
        return None


class BullPutSpreadReal(bt.Strategy):
    """Bull Put Spread - 使用真实期权数据"""
    
    params = (
        ('short_strike', None),
        ('long_strike', None),
        ('expiry', None),
        ('position_size', 1),
    )
    
    def __init__(self):
        self.order = None
        self.entry_date = None
        self.entry_cost = None
        self.symbol = self.datas[0]._name
        
        # 存储期权价格
        self.option_data = {}
        
    def log(self, txt):
        print(f'{self.datas[0].datetime.date(0)} [{self.symbol}] {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.order = None
    
    def next(self):
        if self.order:
            return
        
        current_price = self.data.close[0]
        
        # 获取真实期权价格
        if not self.entry_date and self.params.expiry:
            # 尝试开仓
            try:
                # 卖出 put (short put)
                short_price = get_option_price(
                    self.symbol, 
                    self.params.short_strike, 
                    self.params.expiry, 
                    'put'
                )
                
                # 买入 put (long put)  
                long_price = get_option_price(
                    self.symbol,
                    self.params.long_strike,
                    self.params.expiry,
                    'put'
                )
                
                if short_price and long_price and short_price['mid'] > 0:
                    # 开仓价差
                    spread_cost = short_price['mid'] - long_price['mid']
                    
                    # 开仓条件: 标的价格高于卖出行权价
                    if current_price > self.params.short_strike * 0.95:
                        self.entry_cost = spread_cost
                        self.entry_date = self.datas[0].datetime.date(0)
                        
                        self.order = self.sell()  # 卖出价差
                        self.log(f'Opened BPS: short=${short_price["mid"]:.2f} long=${long_price["mid"]:.2f} spread=${spread_cost:.2f}')
                        
            except Exception as e:
                pass  # 忽略错误
        
        # 持仓中 - 检查平仓
        elif self.entry_date:
            try:
                # 计算当前价差
                short_price = get_option_price(
                    self.symbol,
                    self.params.short_strike,
                    self.params.expiry,
                    'put'
                )
                long_price = get_option_price(
                    self.symbol,
                    self.params.long_strike,
                    self.params.expiry,
                    'put'
                )
                
                if short_price and long_price:
                    current_spread = short_price['mid'] - long_price['mid']
                    
                    # 计算盈亏
                    pnl = self.entry_cost - current_spread
                    pnl_pct = pnl / self.entry_cost * 100 if self.entry_cost > 0 else 0
                    
                    # 止盈/止损/到期
                    if pnl_pct > 50:  # 盈利50%
                        self.order = self.buy()
                        self.log(f'Take Profit: ${pnl:.2f} ({pnl_pct:.1f}%)')
                        self.reset()
                    elif pnl_pct < -30:  # 亏损30%
                        self.order = self.buy()
                        self.log(f'Stop Loss: ${pnl:.2f} ({pnl_pct:.1f}%)')
                        self.reset()
                        
            except Exception as e:
                pass
    
    def reset(self):
        self.entry_date = None
        self.entry_cost = None


def run_real_backtest(symbol='TSLA', 
                      short_strike=380, 
                      long_strike=365,
                      expiry_days=30,
                      start_date='2025-01-01',
                      end_date='2026-03-14',
                      initial_cash=100000):
    """运行真实数据回测"""
    
    print("=" * 60)
    print(f"真实期权数据回测: {symbol}")
    print(f"Short Strike: ${short_strike} | Long Strike: ${long_strike}")
    print(f"到期天数: {expiry_days}")
    print(f"期间: {start_date} ~ {end_date}")
    print("=" * 60)
    
    # 先获取期权到期日
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    
    if not expirations:
        print(f"⚠️ {symbol} 没有期权数据")
        return None
    
    # 选择约30天后的到期日
    target_expiry = None
    for exp in expirations:
        exp_date = datetime.strptime(exp, '%Y-%m-%d')
        days = (exp_date - datetime.now()).days
        if 20 <= days <= 45:
            target_expiry = exp
            break
    
    if target_expiry is None:
        target_expiry = expirations[0]
    
    print(f"使用到期日: {target_expiry}")
    
    # 获取股票数据
    df = ticker.history(start=start_date, end=end_date)
    
    if df.empty:
        print(f"无股票数据")
        return None
    
    # 创建 Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    
    # 添加股票数据
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
    )
    cerebro.adddata(data, name=symbol)
    
    # 添加策略
    cerebro.addstrategy(
        BullPutSpreadReal,
        short_strike=short_strike,
        long_strike=long_strike,
        expiry=target_expiry
    )
    
    # 分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print(f"\n初始资金: ${cerebro.broker.getvalue():,.2f}")
    
    # 运行
    results = cerebro.run()
    
    # 结果
    strat = results[0]
    returns = strat.analyzers.returns.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    final_value = cerebro.broker.getvalue()
    
    print(f"\n最终资金: ${final_value:,.2f}")
    print(f"总收益: {returns.get('rtot', 0)*100:.2f}%")
    print(f"年化收益: {returns.get('rnorm100', 0):.2f}%")
    print(f"最大回撤: {dd.get('max', {}).get('drawdown', 0):.2f}%")
    
    if trades.get('total'):
        print(f"总交易: {trades['total'].get('total', 0)}")
    
    return {
        'final_value': final_value,
        'total_return': returns.get('rtot', 0),
        'annualized_return': returns.get('rnorm100', 0),
        'max_drawdown': dd.get('max', {}).get('drawdown', 0),
    }


def get_current_option_prices(symbol='TSLA'):
    """获取当前所有期权的实时价格"""
    
    print(f"\n获取 {symbol} 期权数据...")
    
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    
    if not expirations:
        print(f"⚠️ 无期权数据")
        return
    
    # 获取最近的到期日
    expiry = expirations[0]
    print(f"到期日: {expiry}")
    
    opt = ticker.option_chain(expiry)
    
    print(f"\n📊 Calls (看涨期权):")
    calls = opt.calls[['strike', 'bid', 'ask', 'lastPrice', 'impliedVolatility', 'openInterest', 'volume']]
    print(calls.head(10).to_string())
    
    print(f"\n📊 Puts (看跌期权):")
    puts = opt.puts[['strike', 'bid', 'ask', 'lastPrice', 'impliedVolatility', 'openInterest', 'volume']]
    print(puts.head(10).to_string())
    
    return {
        'calls': calls,
        'puts': puts,
        'expiry': expiry
    }


if __name__ == '__main__':
    print("=" * 60)
    print("真实期权数据回测")
    print("=" * 60)
    
    # 1. 先查看当前期权价格
    get_current_option_prices('TSLA')
    
    # 2. 运行回测
    print("\n" + "="*60)
    result = run_real_backtest(
        symbol='TSLA',
        short_strike=380,
        long_strike=365,
        expiry_days=30,
        start_date='2025-06-01',
        end_date='2026-03-14',
        initial_cash=100000
    )
    
    if result:
        print(f"\n✅ 回测完成")
