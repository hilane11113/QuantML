#!/usr/bin/env python3
"""
真实期权数据回测 - 完善版
支持 Bull Put Spread / Bull Call Spread / Iron Condor
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


# ==================== 期权数据获取 ====================

class OptionDataManager:
    """期权数据管理器"""
    
    def __init__(self, symbol):
        self.symbol = symbol
        self.ticker = yf.Ticker(symbol)
        self.cache = {}  # 缓存
        self.cache_date = None
        
    def get_expirations(self):
        """获取所有到期日"""
        return self.ticker.options
    
    def get_option_chain(self, expiry):
        """获取期权链"""
        cache_key = f"{self.symbol}_{expiry}"
        
        # 简单缓存 (当天有效)
        today = datetime.now().date()
        if cache_key in self.cache and self.cache_date == today:
            return self.cache[cache_key]
        
        try:
            opt = self.ticker.option_chain(expiry)
            self.cache[cache_key] = opt
            self.cache_date = today
            return opt
        except Exception as e:
            print(f"获取期权链失败: {e}")
            return None
    
    def get_option_price(self, strike, expiry, option_type='call'):
        """获取单个期权价格"""
        opt = self.get_option_chain(expiry)
        if opt is None:
            return None
        
        try:
            if option_type == 'call':
                df = opt.calls
            else:
                df = opt.puts
            
            row = df[df['strike'] == strike]
            
            if row.empty:
                return None
            
            row = row.iloc[0]
            
            # 计算中间价
            bid = row.get('bid', 0) or 0
            ask = row.get('ask', 0) or 0
            
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
            else:
                mid = row.get('lastPrice', 0) or 0
            
            return {
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'last': row.get('lastPrice', 0) or 0,
                'iv': row.get('impliedVolatility', 0) or 0,
                'oi': row.get('openInterest', 0) or 0,
                'volume': row.get('volume', 0) or 0,
                'delta': row.get('delta', 0) or 0,
                'gamma': row.get('gamma', 0) or 0,
                'theta': row.get('theta', 0) or 0,
                'vega': row.get('vega', 0) or 0,
            }
        except Exception as e:
            return None
    
    def find_best_strikes(self, expiry, current_price, strategy_type='bull_put_spread'):
        """找到最佳行权价"""
        opt = self.get_option_chain(expiry)
        if opt is None:
            return None, None
        
        puts = opt.puts
        calls = opt.calls
        
        if strategy_type == 'bull_put_spread':
            # 寻找 OTM put
            otm_puts = puts[puts['strike'] < current_price]
            otm_puts = otm_puts.sort_values('openInterest', ascending=False)
            
            if not otm_puts.empty:
                # 卖出的行权价 (高 OI)
                short_strike = otm_puts.iloc[0]['strike']
                # 买入的行权价 (更低价)
                long_strike = short_strike - 15  # 默认 15 美元价差
                return short_strike, long_strike
        
        elif strategy_type == 'bull_call_spread':
            # 寻找 OTM call
            otm_calls = calls[calls['strike'] > current_price]
            otm_calls = otm_calls.sort_values('openInterest', ascending=False)
            
            if not otm_calls.empty:
                short_strike = otm_calls.iloc[0]['strike']
                long_strike = short_strike + 15
                return short_strike, long_strike
        
        return None, None


# ==================== 回测策略 ====================

class BullPutSpreadBacktest(bt.Strategy):
    """Bull Put Spread 回测"""
    
    params = (
        ('short_strike', None),
        ('long_strike', None),
        ('expiry', None),
        ('position_size', 1),
        ('profit_target', 0.5),  # 盈利 50% 平仓
        ('stop_loss', 0.3),      # 亏损 30% 平仓
    )
    
    def __init__(self):
        self.order = None
        self.entry_date = None
        self.entry_credit = None  # 收到的权利金
        self.opt_manager = OptionDataManager(self.datas[0]._name)
        
    def log(self, txt):
        print(f'{self.datas[0].datetime.date(0)} {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None
    
    def next(self):
        if self.order:
            return
        
        current_price = self.data.close[0]
        
        # ============ 开仓 ============
        if not self.position and self.params.expiry:
            short_price = self.opt_manager.get_option_price(
                self.params.short_strike, self.params.expiry, 'put'
            )
            long_price = self.opt_manager.get_option_price(
                self.params.long_strike, self.params.expiry, 'put'
            )
            
            if short_price and long_price:
                credit = short_price['mid'] - long_price['mid']
                
                # 开仓条件: 标的价格高于卖出行权价
                if credit > 0 and current_price > self.params.short_strike * 0.95:
                    self.entry_credit = credit
                    self.entry_date = self.datas[0].datetime.date(0)
                    self.order = self.sell()
                    self.log(f'📗 开仓 Bull Put Spread: short=${self.params.short_strike} long=${self.params.long_strike} credit=${credit:.2f}')
        
        # ============ 持仓管理 ============
        elif self.position and self.entry_credit:
            short_price = self.opt_manager.get_option_price(
                self.params.short_strike, self.params.expiry, 'put'
            )
            long_price = self.opt_manager.get_option_price(
                self.params.long_strike, self.params.expiry, 'put'
            )
            
            if short_price and long_price:
                current_credit = short_price['mid'] - long_price['mid']
                
                # 计算盈亏百分比
                pnl_pct = (self.entry_credit - current_credit) / self.entry_credit
                
                # 止盈/止损
                if pnl_pct >= self.params.profit_target:
                    self.order = self.buy()
                    self.log(f'✅ 止盈: +{pnl_pct*100:.1f}%')
                    self.reset()
                elif pnl_pct <= -self.params.stop_loss:
                    self.order = self.buy()
                    self.log(f'🛑 止损: {pnl_pct*100:.1f}%')
                    self.reset()
    
    def reset(self):
        self.entry_date = None
        self.entry_credit = None


# ==================== 回测引擎 ====================

def run_backtest(
    symbol='TSLA',
    strategy_type='bull_put_spread',
    short_strike=380,
    long_strike=365,
    expiry='2026-03-20',
    start_date='2025-06-01',
    end_date='2026-03-14',
    initial_cash=100000,
    profit_target=0.5,
    stop_loss=0.3
):
    """运行回测"""
    
    print("=" * 60)
    print(f"期权回测: {symbol} | {strategy_type}")
    print(f"行权价: ${short_strike} / ${long_strike}")
    print(f"到期日: {expiry}")
    print(f"期间: {start_date} ~ {end_date}")
    print("=" * 60)
    
    # 获取股票数据
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date)
    
    if df.empty:
        print("无股票数据")
        return None
    
    # 创建 Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.001)
    
    # 添加数据
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='Open', high='High', low='Low', close='Close', volume='Volume'
    )
    cerebro.adddata(data, name=symbol)
    
    # 添加策略
    cerebro.addstrategy(
        BullPutSpreadBacktest,
        short_strike=short_strike,
        long_strike=long_strike,
        expiry=expiry,
        profit_target=profit_target,
        stop_loss=stop_loss
    )
    
    # 分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print(f"\n💰 初始资金: ${cerebro.broker.getvalue():,.2f}")
    
    results = cerebro.run()
    
    # 结果
    strat = results[0]
    returns = strat.analyzers.returns.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    final_value = cerebro.broker.getvalue()
    
    print(f"\n📊 回测结果:")
    print(f"  最终资金: ${final_value:,.2f}")
    print(f"  总收益: {returns.get('rtot', 0)*100:.2f}%")
    print(f"  年化收益: {returns.get('rnorm100', 0):.2f}%")
    print(f"  最大回撤: {dd.get('max', {}).get('drawdown', 0):.2f}%")
    
    if 'total' in trades:
        print(f"  总交易数: {trades['total'].get('total', 0)}")
        if 'won' in trades:
            print(f"  盈利交易: {trades['won'].get('total', 0)}")
        if 'lost' in trades:
            print(f"  亏损交易: {trades['lost'].get('total', 0)}")
    
    return {
        'final_value': final_value,
        'total_return': returns.get('rtot', 0),
        'annualized_return': returns.get('rnorm100', 0),
        'max_drawdown': dd.get('max', {}).get('drawdown', 0),
    }


def scan_and_backtest(symbol='TSLA'):
    """扫描最佳策略并回测"""
    
    print(f"\n{'='*60}")
    print(f"扫描 {symbol} 最佳策略")
    print(f"{'='*60}")
    
    opt_mgr = OptionDataManager(symbol)
    expirations = opt_mgr.get_expirations()
    
    if not expirations:
        print("无期权数据")
        return
    
    # 获取当前股价
    ticker = yf.Ticker(symbol)
    current_price = ticker.history(period='1d')['Close'].iloc[-1]
    print(f"当前股价: ${current_price:.2f}")
    
    # 尝试不同到期日
    for expiry in expirations[:3]:  # 只看前3个
        short_strike, long_strike = opt_mgr.find_best_strikes(
            expiry, current_price, 'bull_put_spread'
        )
        
        if short_strike and long_strike:
            print(f"\n到期日: {expiry}")
            print(f"推荐: Bull Put Spread ${short_strike} / ${long_strike}")
            
            # 回测
            result = run_backtest(
                symbol=symbol,
                strategy_type='bull_put_spread',
                short_strike=short_strike,
                long_strike=long_strike,
                expiry=expiry,
                start_date='2025-09-01',
                end_date='2026-03-14',
                initial_cash=100000
            )
            
            if result:
                print(f"  → 总收益: {result['total_return']*100:.2f}%")
    
    return result


if __name__ == '__main__':
    # 扫描最佳策略
    scan_and_backtest('TSLA')
