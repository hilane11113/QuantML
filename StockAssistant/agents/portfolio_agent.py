#!/usr/bin/env python3
"""
PortfolioAgent - 投资组合管理代理
模拟交易 + 持仓管理 + 绩效追踪
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = '/root/.openclaw/workspace/quant/StockAssistant/portfolio.db'

class PortfolioAgent:
    """投资组合管理"""
    
    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 持仓表
        c.execute('''CREATE TABLE IF NOT EXISTS positions
                     (id INTEGER PRIMARY KEY, symbol TEXT, market TEXT,
                      quantity INTEGER, avg_cost REAL, current_price REAL,
                      open_date TEXT, status TEXT)''')
        
        # 交易记录表
        c.execute('''CREATE TABLE IF NOT EXISTS trades
                     (id INTEGER PRIMARY KEY, symbol TEXT, market TEXT,
                      action TEXT, quantity INTEGER, price REAL,
                      trade_date TEXT, pnl REAL, reason TEXT)''')
        
        # 资金变动表
        c.execute('''CREATE TABLE IF NOT EXISTS capital
                     (id INTEGER PRIMARY KEY, date TEXT,
                      balance REAL, change REAL, reason TEXT)''')
        
        conn.commit()
        conn.close()
    
    def buy(self, symbol: str, market: str, quantity: int, price: float, 
            reason: str = "") -> dict:
        """
        买入股票
        
        Args:
            symbol: 股票代码
            market: 市场 (A_SHARE_SZ, A_SHARE_SH, US_STOCK)
            quantity: 数量
            price: 价格
            reason: 买入理由
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        total_cost = quantity * price
        trade_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 检查是否已有持仓
        c.execute("SELECT id, quantity, avg_cost FROM positions WHERE symbol=? AND market=? AND status='open'",
                 (symbol, market))
        existing = c.fetchone()
        
        if existing:
            # 追加买入
            pos_id, old_qty, old_cost = existing
            new_qty = old_qty + quantity
            new_avg_cost = (old_qty * old_cost + quantity * price) / new_qty
            c.execute("UPDATE positions SET quantity=?, avg_cost=? WHERE id=?",
                     (new_qty, new_avg_cost, pos_id))
        else:
            # 新建持仓
            c.execute("INSERT INTO positions (symbol, market, quantity, avg_cost, current_price, open_date, status) VALUES (?,?,?,?,?,?,?)",
                     (symbol, market, quantity, price, price, trade_date, 'open'))
        
        # 记录交易
        c.execute("INSERT INTO trades (symbol, market, action, quantity, price, trade_date, pnl, reason) VALUES (?,?,?,?,?,?,?,?)",
                 (symbol, market, 'BUY', quantity, price, trade_date, 0, reason))
        
        conn.commit()
        conn.close()
        
        return {
            "action": "BUY",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "total_cost": total_cost,
            "success": True
        }
    
    def sell(self, symbol: str, market: str, quantity: int, price: float,
             reason: str = "") -> dict:
        """
        卖出股票
        
        Args:
            symbol: 股票代码
            market: 市场
            quantity: 数量
            price: 价格
            reason: 卖出理由
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 检查持仓
        c.execute("SELECT id, quantity, avg_cost FROM positions WHERE symbol=? AND market=? AND status='open'",
                 (symbol, market))
        existing = c.fetchone()
        
        if not existing:
            conn.close()
            return {"error": "无持仓", "success": False}
        
        pos_id, held_qty, avg_cost = existing
        
        if quantity > held_qty:
            conn.close()
            return {"error": "持仓不足", "success": False}
        
        trade_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pnl = (price - avg_cost) * quantity
        
        if quantity == held_qty:
            # 全部卖出
            c.execute("UPDATE positions SET status='closed' WHERE id=?", (pos_id,))
        else:
            # 部分卖出
            c.execute("UPDATE positions SET quantity=? WHERE id=?", (held_qty - quantity, pos_id))
        
        # 记录交易
        c.execute("INSERT INTO trades (symbol, market, action, quantity, price, trade_date, pnl, reason) VALUES (?,?,?,?,?,?,?,?)",
                 (symbol, market, 'SELL', quantity, price, trade_date, pnl, reason))
        
        conn.commit()
        conn.close()
        
        return {
            "action": "SELL",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "pnl": pnl,
            "success": True
        }
    
    def get_positions(self) -> list:
        """获取当前持仓"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT symbol, market, quantity, avg_cost, current_price, open_date FROM positions WHERE status='open'")
        rows = c.fetchall()
        conn.close()
        
        positions = []
        for row in rows:
            positions.append({
                "symbol": row[0],
                "market": row[1],
                "quantity": row[2],
                "avg_cost": row[3],
                "current_price": row[4],
                "open_date": row[5],
                "pnl": (row[4] - row[3]) * row[2] if row[4] > 0 else 0,
                "pnl_pct": ((row[4] - row[3]) / row[3] * 100) if row[3] > 0 else 0
            })
        
        return positions
    
    def get_performance(self) -> dict:
        """获取绩效统计"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 总交易次数
        c.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
        total_trades = c.fetchone()[0]
        
        # 盈利次数
        c.execute("SELECT COUNT(*) FROM trades WHERE action='SELL' AND pnl>0")
        winning_trades = c.fetchone()[0]
        
        # 总盈亏
        c.execute("SELECT SUM(pnl) FROM trades WHERE action='SELL'")
        total_pnl = c.fetchone()[0] or 0
        
        # 获取当前持仓成本
        c.execute("SELECT SUM(quantity * avg_cost) FROM positions WHERE status='open'")
        position_cost = c.fetchone()[0] or 0
        
        conn.close()
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "position_cost": position_cost
        }
    
    def update_prices(self, prices: dict):
        """更新持仓价格"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        for symbol, price in prices.items():
            c.execute("UPDATE positions SET current_price=? WHERE symbol=? AND status='open'",
                     (price, symbol))
        
        conn.commit()
        conn.close()
    
    def clear_all(self):
        """清空所有数据（测试用）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM positions")
        c.execute("DELETE FROM trades")
        c.execute("DELETE FROM capital")
        conn.commit()
        conn.close()
        return {"success": True, "message": "已清空所有数据"}


def format_portfolio_report(positions: list, performance: dict) -> str:
    """格式化投资组合报告"""
    
    if not positions:
        report = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 投资组合报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏠 当前持仓: 空仓

📈 绩效统计:
   总交易次数: {trades}
   盈利次数: {winning}
   胜率: {win_rate:.1f}%
   总盈亏: {pnl:,.2f}元

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""".format(
            trades=performance['total_trades'],
            winning=performance['winning_trades'],
            win_rate=performance['win_rate'],
            pnl=performance['total_pnl']
        )
        return report
    
    total_value = sum(p['current_price'] * p['quantity'] for p in positions)
    total_cost = sum(p['avg_cost'] * p['quantity'] for p in positions)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    
    report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 投资组合报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏠 当前持仓 ({len(positions)}只):

"""
    
    for p in positions:
        emoji = "🟢" if p['pnl'] >= 0 else "🔴"
        sign = "+" if p['pnl'] >= 0 else ""
        report += f"""📌 {p['symbol']} ({p['market']})
   持仓: {p['quantity']}股 | 成本: {p['avg_cost']:.3f} | 现价: {p['current_price']:.3f}
   盈亏: {emoji} {sign}{p['pnl']:.2f}元 ({sign}{p['pnl_pct']:.2f}%)

"""
    
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    sign = "+" if total_pnl >= 0 else ""
    
    report += f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 汇总:
   总市值: {total_value:,.2f}元
   总成本: {total_cost:,.2f}元
   总盈亏: {emoji} {sign}{total_pnl:,.2f}元 ({sign}{total_pnl_pct:.2f}%)

📈 绩效统计:
   总交易次数: {performance['total_trades']}
   盈利次数: {performance['winning_trades']}
   胜率: {performance['win_rate']:.1f}%
   历史总盈亏: {performance['total_pnl']:,.2f}元
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    return report
