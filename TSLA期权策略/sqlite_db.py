#!/usr/bin/env python3
"""
SQLite 版期权策略回测数据库
标的: TSLA | 基准价: 开盘后1小时
"""

import sqlite3
import pandas as pd
from datetime import datetime, date, time
import json

DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/backtest.db'

def init_db():
    """初始化数据库表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. 标的日线数据
    c.execute('''
        CREATE TABLE IF NOT EXISTS stock_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            trade_date DATE NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL,
            volume INTEGER,
            amount REAL,
            benchmark_price REAL,
            benchmark_time TIME DEFAULT '10:00:00',
            returns REAL,
            volatility REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')
    
    # 2. 期权链数据
    c.execute('''
        CREATE TABLE IF NOT EXISTS option_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            trade_date DATE NOT NULL,
            option_symbol TEXT NOT NULL,
            expiry_date DATE NOT NULL,
            strike_price REAL NOT NULL,
            option_type TEXT NOT NULL,
            bid REAL, ask REAL, last_price REAL, midpoint REAL, mark_price REAL,
            delta REAL, gamma REAL, theta REAL, vega, rho REAL,
            open_interest INTEGER, volume INTEGER,
            implied_vol REAL,
            underlying_price REAL,
            intrinsic_value REAL, extrinsic_value REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(option_symbol, trade_date)
        )
    ''')
    
    # 3. 策略信号
    c.execute('''
        CREATE TABLE IF NOT EXISTS strategy_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            trade_date DATE NOT NULL,
            signal_type TEXT NOT NULL,
            signal_strength REAL,
            leg1_type TEXT, leg1_action TEXT, leg1_strike REAL, leg1_expiry DATE, leg1_premium REAL,
            leg2_type TEXT, leg2_action TEXT, leg2_strike REAL, leg2_expiry DATE, leg2_premium REAL,
            total_score REAL, risk_reward_ratio REAL, liquidity_score REAL, iv_score REAL, theta_score REAL,
            benchmark_price REAL,
            decision_label TEXT DEFAULT '⏸️观望',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(strategy_name, symbol, trade_date)
        )
    ''')
    
    # 4. 回测结果
    c.execute('''
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            benchmark_time TIME DEFAULT '10:00:00',
            total_return REAL, annualized_return REAL, sharpe_ratio REAL,
            max_drawdown REAL, sortino_ratio REAL, calmar_ratio REAL,
            win_rate REAL, profit_loss_ratio REAL,
            total_trades INTEGER, winning_trades INTEGER, losing_trades INTEGER,
            avg_holding_days REAL, avg_profit REAL, avg_loss REAL,
            params TEXT, equity_curve TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 5. 多策略组合
    c.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_name TEXT NOT NULL UNIQUE,
            description TEXT,
            strategies TEXT NOT NULL,
            capital_allocation REAL DEFAULT 100000,
            rebalance_frequency TEXT DEFAULT 'weekly',
            start_date DATE, end_date DATE,
            total_return REAL, annualized_return REAL, sharpe_ratio REAL, max_drawdown REAL,
            portfolio_volatility REAL, correlation_matrix TEXT,
            var_95 REAL, cvar_95 REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 6. 持仓记录
    c.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_name TEXT, strategy_name TEXT,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            trade_date DATE NOT NULL,
            position_id TEXT UNIQUE,
            position_type TEXT, action TEXT, strike_price REAL,
            expiry_date DATE, quantity INTEGER,
            entry_price REAL, current_price REAL, exit_price REAL,
            pnl REAL, pnl_pct REAL,
            status TEXT DEFAULT 'OPEN', holding_days INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 7. 交易记录
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_name TEXT, strategy_name TEXT,
            symbol TEXT NOT NULL DEFAULT 'TSLA',
            trade_date DATE NOT NULL,
            trade_type TEXT NOT NULL,
            option_symbol TEXT, position_id TEXT,
            position_type TEXT, strike_price REAL, expiry_date DATE, quantity INTEGER,
            price REAL, commission REAL, multiplier INTEGER DEFAULT 100, total_cost REAL,
            underlying_price REAL, benchmark_price REAL,
            realized_pnl REAL, realized_pnl_pct REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_daily(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_option_date ON option_chain(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_signals_date ON strategy_signals(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)')
    
    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")

def insert_signal(signal: dict):
    """插入策略信号"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        INSERT OR REPLACE INTO strategy_signals 
        (strategy_name, symbol, trade_date, signal_type, signal_strength,
         leg1_type, leg1_action, leg1_strike, leg1_expiry, leg1_premium,
         leg2_type, leg2_action, leg2_strike, leg2_expiry, leg2_premium,
         total_score, risk_reward_ratio, liquidity_score, iv_score, theta_score,
         benchmark_price, decision_label, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal.get('strategy_name'), signal.get('symbol', 'TSLA'),
        signal.get('trade_date'), signal.get('signal_type'),
        signal.get('signal_strength'),
        signal.get('leg1_type'), signal.get('leg1_action'),
        signal.get('leg1_strike'), signal.get('leg1_expiry'),
        signal.get('leg1_premium'),
        signal.get('leg2_type'), signal.get('leg2_action'),
        signal.get('leg2_strike'), signal.get('leg2_expiry'),
        signal.get('leg2_premium'),
        signal.get('total_score'), signal.get('risk_reward_ratio'),
        signal.get('liquidity_score'), signal.get('iv_score'),
        signal.get('theta_score'), signal.get('benchmark_price'),
        signal.get('decision_label', '⏸️观望'), signal.get('notes')
    ))
    
    conn.commit()
    conn.close()

def insert_trade(trade: dict):
    """插入交易记录"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO trades
        (portfolio_name, strategy_name, symbol, trade_date, trade_type,
         option_symbol, position_type, strike_price, expiry_date, quantity,
         price, commission, multiplier, total_cost, underlying_price, benchmark_price,
         realized_pnl, realized_pnl_pct, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        trade.get('portfolio_name'), trade.get('strategy_name'),
        trade.get('symbol', 'TSLA'), trade.get('trade_date'),
        trade.get('trade_type'), trade.get('option_symbol'),
        trade.get('position_type'), trade.get('strike_price'),
        trade.get('expiry_date'), trade.get('quantity'),
        trade.get('price'), trade.get('commission', 0),
        trade.get('multiplier', 100), trade.get('total_cost'),
        trade.get('underlying_price'), trade.get('benchmark_price'),
        trade.get('realized_pnl'), trade.get('realized_pnl_pct'),
        trade.get('notes')
    ))
    
    conn.commit()
    conn.close()

def insert_backtest_result(result: dict):
    """插入回测结果"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO backtest_results
        (strategy_name, symbol, start_date, end_date, benchmark_time,
         total_return, annualized_return, sharpe_ratio, max_drawdown,
         sortino_ratio, calmar_ratio, win_rate, profit_loss_ratio,
         total_trades, winning_trades, losing_trades, avg_holding_days,
         avg_profit, avg_loss, params, equity_curve)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        result.get('strategy_name'), result.get('symbol', 'TSLA'),
        result.get('start_date'), result.get('end_date'),
        result.get('benchmark_time', '10:00:00'),
        result.get('total_return'), result.get('annualized_return'),
        result.get('sharpe_ratio'), result.get('max_drawdown'),
        result.get('sortino_ratio', 0), result.get('calmar_ratio', 0),
        result.get('win_rate'), result.get('profit_loss_ratio', 0),
        result.get('total_trades'), result.get('winning_trades'),
        result.get('losing_trades'), result.get('avg_holding_days', 0),
        result.get('avg_profit'), result.get('avg_loss'),
        json.dumps(result.get('params', {})),
        json.dumps(result.get('equity_curve', []))
    ))
    
    conn.commit()
    conn.close()

def insert_portfolio(portfolio: dict):
    """插入多策略组合"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        INSERT OR REPLACE INTO portfolio
        (portfolio_name, description, strategies, capital_allocation,
         rebalance_frequency, start_date, end_date, total_return,
         annualized_return, sharpe_ratio, max_drawdown, portfolio_volatility,
         correlation_matrix, var_95, cvar_95)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        portfolio.get('portfolio_name'), portfolio.get('description'),
        json.dumps(portfolio.get('strategies', [])),
        portfolio.get('capital_allocation', 100000),
        portfolio.get('rebalance_frequency', 'weekly'),
        portfolio.get('start_date'), portfolio.get('end_date'),
        portfolio.get('total_return'), portfolio.get('annualized_return'),
        portfolio.get('sharpe_ratio'), portfolio.get('max_drawdown'),
        portfolio.get('portfolio_volatility'),
        json.dumps(portfolio.get('correlation_matrix', {})),
        portfolio.get('var_95'), portfolio.get('cvar_95')
    ))
    
    conn.commit()
    conn.close()

def query_signals(strategy_name=None, trade_date=None, limit=10):
    """查询信号"""
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM strategy_signals WHERE 1=1"
    params = []
    
    if strategy_name:
        query += " AND strategy_name = ?"
        params.append(strategy_name)
    if trade_date:
        query += " AND trade_date = ?"
        params.append(trade_date)
    
    query += " ORDER BY trade_date DESC, signal_strength DESC LIMIT ?"
    params.append(limit)
    
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def query_backtest_results(strategy_name=None):
    """查询回测结果"""
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM backtest_results WHERE 1=1"
    params = []
    
    if strategy_name:
        query += " AND strategy_name = ?"
        params.append(strategy_name)
    
    query += " ORDER BY total_return DESC"
    
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def query_portfolios():
    """查询多策略组合"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM portfolio ORDER BY total_return DESC", conn)
    conn.close()
    return df

# ============================================================
# 示例数据
# ============================================================

def insert_sample_data():
    """插入示例数据"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 检查是否已有数据
    c.execute("SELECT COUNT(*) FROM strategy_signals")
    if c.fetchone()[0] > 0:
        print("📋 示例数据已存在，跳过")
        conn.close()
        return
    
    # 插入示例信号
    sample_signals = [
        {
            'strategy_name': 'vertical_spread_v6',
            'trade_date': '2026-03-14',
            'signal_type': 'BUY',
            'signal_strength': 75.5,
            'leg1_type': 'P', 'leg1_action': 'SELL', 'leg1_strike': 250,
            'leg1_expiry': '2026-04-18', 'leg1_premium': 3.5,
            'leg2_type': 'P', 'leg2_action': 'BUY', 'leg2_strike': 240,
            'leg2_expiry': '2026-04-18', 'leg2_premium': 1.8,
            'total_score': 75.5, 'risk_reward_ratio': 2.5,
            'liquidity_score': 80, 'iv_score': 65, 'theta_score': 70,
            'benchmark_price': 263.50, 'decision_label': '✅开仓'
        },
        {
            'strategy_name': 'multi_strategy_v2',
            'trade_date': '2026-03-14',
            'signal_type': 'BUY',
            'signal_strength': 68.0,
            'leg1_type': 'P', 'leg1_action': 'SELL', 'leg1_strike': 255,
            'leg1_expiry': '2026-04-18', 'leg1_premium': 4.2,
            'leg2_type': 'C', 'leg2_action': 'BUY', 'leg2_strike': 275,
            'leg2_expiry': '2026-04-18', 'leg2_premium': 2.1,
            'total_score': 68.0, 'risk_reward_ratio': 1.8,
            'liquidity_score': 75, 'iv_score': 60, 'theta_score': 65,
            'benchmark_price': 263.50, 'decision_label': '🟡试探'
        }
    ]
    
    for signal in sample_signals:
        insert_signal(signal)
    
    # 插入示例回测结果
    sample_results = [
        {
            'strategy_name': 'vertical_spread_v6',
            'start_date': '2026-02-01',
            'end_date': '2026-03-14',
            'total_return': 0.349,
            'annualized_return': 2.95,
            'sharpe_ratio': 1.85,
            'max_drawdown': 0.12,
            'win_rate': 0.667,
            'total_trades': 12,
            'winning_trades': 8,
            'losing_trades': 4,
            'avg_profit': 185.0,
            'avg_loss': -80.0,
            'params': {'max_loss': 500, 'min_rr': 1.5}
        },
        {
            'strategy_name': 'multi_strategy_v2',
            'start_date': '2026-02-01',
            'end_date': '2026-03-14',
            'total_return': 0.285,
            'annualized_return': 2.41,
            'sharpe_ratio': 1.62,
            'max_drawdown': 0.15,
            'win_rate': 0.625,
            'total_trades': 18,
            'winning_trades': 11,
            'losing_trades': 7,
            'avg_profit': 160.0,
            'avg_loss': -75.0,
            'params': {'weights': [0.4, 0.3, 0.3]}
        }
    ]
    
    for result in sample_results:
        insert_backtest_result(result)
    
    # 插入示例组合
    sample_portfolio = {
        'portfolio_name': 'TSLA_Options_Combo',
        'description': 'TSLA期权多策略组合',
        'strategies': [
            {'name': 'vertical_spread', 'weight': 0.4, 'params': {'max_loss': 500}},
            {'name': 'iron_condor', 'weight': 0.3, 'params': {'width': 20}},
            {'name': 'bull_call', 'weight': 0.3, 'params': {'target_delta': 0.3}}
        ],
        'capital_allocation': 100000,
        'rebalance_frequency': 'weekly',
        'start_date': '2026-02-01',
        'end_date': '2026-03-14',
        'total_return': 0.315,
        'annualized_return': 2.66,
        'sharpe_ratio': 1.75,
        'max_drawdown': 0.13
    }
    
    insert_portfolio(sample_portfolio)
    
    print("📋 示例数据插入完成")
    conn.close()

if __name__ == '__main__':
    # 初始化数据库
    init_db()
    
    # 插入示例数据
    insert_sample_data()
    
    # 测试查询
    print("\n=== 策略信号 ===")
    print(query_signals())
    
    print("\n=== 回测结果 ===")
    print(query_backtest_results())
    
    print("\n=== 多策略组合 ===")
    print(query_portfolios())
