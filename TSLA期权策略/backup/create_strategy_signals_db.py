import sqlite3
import pandas as pd
from datetime import datetime
import os

class StrategySignalsDB:
    """策略信号数据库管理类 - 使用完整优化后的表结构"""
    
    def __init__(self, db_path=None):
        if db_path is None:
            self.db_path = r"C:\Users\Admin\Desktop\期权\strategy_signals.db"
        else:
            self.db_path = db_path
        
        # 确保数据库存在
        self._create_database_if_not_exists()
    
    def _create_database_if_not_exists(self):
        """创建数据库（如果不存在）"""
        if not os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建策略信号表 - 使用完整优化后的表结构
            create_table_sql = '''
            CREATE TABLE IF NOT EXISTS StrategySignals (
                SignalID INTEGER PRIMARY KEY AUTOINCREMENT,
                RunDateTime TEXT NOT NULL,           -- 程序运行时间（YYYY-MM-DD HH:MM:SS）
                UnderlyingSymbol TEXT NOT NULL,      -- 如 "TSLA"
                OptionType TEXT CHECK(OptionType IN ('Call', 'Put')), -- 建议方向
                LongStrike REAL,                     -- 长腿行权价（如 405）
                ShortStrike REAL,                    -- 短腿行权价（如 370）
                SpreadWidth REAL,                    -- 价差宽度（自动计算：|LongStrike - ShortStrike|）
                VIXLevel REAL,                       -- 当前 VIX 水平
                IVLevel REAL,                        -- TSLA IV 水平
                IVRankEstimate REAL,                 -- 估算 IV Rank（百分位）
                IV_HV_Ratio REAL,                    -- IV / HV 比值
                HasEarnings BOOLEAN DEFAULT 0,       -- 是否有财报（0=否，1=是）
                VIX_TrendStatus TEXT,                -- "🟢绿灯", "🟡黄灯", "🔴红灯"
                IVCondition TEXT,                    -- "GREEN/YELLOW/RED"
                Decision TEXT,                       -- "✅开仓", "⚠️试探", "❌禁止"
                IsRealTrade BOOLEAN DEFAULT 0,       -- 是否为真实交易（0=模拟，1=真实）
                ProfitLoss REAL DEFAULT 0,           -- 盈利（正数）或亏损（负数）
                Cost REAL DEFAULT 0,                 -- 交易成本
                Notes TEXT,                          -- 手动备注（如"高IV风险"）
                CreatedTime TEXT DEFAULT CURRENT_TIMESTAMP,
                UpdatedTime TEXT DEFAULT CURRENT_TIMESTAMP
            );
            '''
            
            cursor.execute(create_table_sql)
            
            # 创建索引以提高查询性能
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rundatetime ON StrategySignals(RunDateTime);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_symbol ON StrategySignals(UnderlyingSymbol);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision ON StrategySignals(Decision);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_isrealtrade ON StrategySignals(IsRealTrade);')
            
            conn.commit()
            conn.close()
            print(f"✅ 成功创建策略信号数据库: {self.db_path}")
        else:
            print(f"✅ 策略信号数据库已存在: {self.db_path}")
    
    def insert_signal(self, signal_data):
        """插入策略信号记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        insert_sql = '''
        INSERT INTO StrategySignals (
            RunDateTime, UnderlyingSymbol, OptionType, LongStrike, ShortStrike,
            SpreadWidth, VIXLevel, IVLevel, IVRankEstimate, IV_HV_Ratio,
            HasEarnings, VIX_TrendStatus, IVCondition, Decision, IsRealTrade, 
            ProfitLoss, Cost, Notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        '''
        
        cursor.execute(insert_sql, signal_data)
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        print(f"✅ 成功插入策略信号，ID: {signal_id}")
        return signal_id
    
    def update_trade_result(self, signal_id, profit_loss, cost=0, is_real_trade=True):
        """更新交易结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        update_sql = '''
        UPDATE StrategySignals 
        SET IsRealTrade = ?, ProfitLoss = ?, Cost = ?, UpdatedTime = CURRENT_TIMESTAMP
        WHERE SignalID = ?;
        '''
        
        cursor.execute(update_sql, (int(is_real_trade), profit_loss, cost, signal_id))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"✅ 成功更新交易结果，SignalID: {signal_id}, 盈亏: {profit_loss}, 成本: {cost}")
        return rows_affected
    
    def get_latest_signals(self, symbol=None, limit=10):
        """获取最新的策略信号"""
        conn = sqlite3.connect(self.db_path)
        if symbol:
            query = "SELECT * FROM StrategySignals WHERE UnderlyingSymbol = ? ORDER BY RunDateTime DESC LIMIT ?;"
            df = pd.read_sql_query(query, conn, params=(symbol, limit))
        else:
            query = "SELECT * FROM StrategySignals ORDER BY RunDateTime DESC LIMIT ?;"
            df = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        return df
    
    def get_decision_stats(self):
        """获取决策统计信息"""
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            Decision,
            COUNT(*) as Count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM StrategySignals), 2) as Percentage
        FROM StrategySignals
        GROUP BY Decision
        ORDER BY Count DESC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    
    def get_performance_by_decision(self):
        """按决策类型统计绩效"""
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            Decision,
            COUNT(*) as TotalSignals,
            SUM(IsRealTrade) as RealTrades,
            AVG(CASE WHEN IsRealTrade = 1 THEN ProfitLoss END) as AvgPnL,
            SUM(CASE WHEN IsRealTrade = 1 THEN ProfitLoss END) as TotalPnL,
            SUM(CASE WHEN IsRealTrade = 1 AND ProfitLoss > 0 THEN 1 ELSE 0 END) as WinningTrades,
            SUM(CASE WHEN IsRealTrade = 1 AND ProfitLoss < 0 THEN 1 ELSE 0 END) as LosingTrades
        FROM StrategySignals
        GROUP BY Decision
        ORDER BY TotalPnL DESC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    
    def get_symbol_stats(self):
        """按标的统计信号情况"""
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            UnderlyingSymbol,
            COUNT(*) as TotalSignals,
            SUM(IsRealTrade) as RealTrades,
            AVG(CASE WHEN IsRealTrade = 1 THEN ProfitLoss END) as AvgPnL,
            SUM(CASE WHEN IsRealTrade = 1 THEN ProfitLoss END) as TotalPnL,
            SUM(CASE WHEN IsRealTrade = 1 AND ProfitLoss > 0 THEN 1 ELSE 0 END) as WinningTrades
        FROM StrategySignals
        GROUP BY UnderlyingSymbol
        ORDER BY TotalPnL DESC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

def demo_usage():
    """演示数据库使用方法"""
    print("=== 策略信号数据库演示 ===\n")
    
    # 创建数据库实例
    db = StrategySignalsDB()
    
    # 插入示例信号
    sample_signal = (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # RunDateTime
        'TSLA',                                        # UnderlyingSymbol
        'Put',                                         # OptionType
        430.0,                                         # LongStrike
        425.0,                                         # ShortStrike
        5.0,                                           # SpreadWidth
        15.86,                                         # VIXLevel
        31.7,                                          # IVLevel
        20.0,                                          # IVRankEstimate
        89.0,                                          # IV_HV_Ratio
        0,                                             # HasEarnings (False)
        '🔴红灯',                                       # VIX_TrendStatus
        'GREEN',                                       # IVCondition
        '❌禁止',                                       # Decision
        0,                                             # IsRealTrade (False for now)
        0.0,                                           # ProfitLoss
        0.0,                                           # Cost
        'VIX趋势不利'                                   # Notes
    )
    
    print("1. 插入新策略信号:")
    signal_id = db.insert_signal(sample_signal)
    
    print("\n2. 获取最新信号:")
    latest_signals = db.get_latest_signals(limit=5)
    print(latest_signals[['SignalID', 'RunDateTime', 'UnderlyingSymbol', 'Decision', 'IsRealTrade', 'ProfitLoss']].to_string(index=False))
    
    # 更新交易结果
    print(f"\n3. 更新交易结果 (SignalID: {signal_id}):")
    db.update_trade_result(signal_id, profit_loss=125.50, cost=15.20, is_real_trade=True)
    
    print("\n4. 决策统计:")
    decision_stats = db.get_decision_stats()
    print(decision_stats.to_string(index=False))
    
    print("\n5. 按决策类型统计绩效:")
    performance_stats = db.get_performance_by_decision()
    print(performance_stats.to_string(index=False))
    
    print("\n6. 按标的统计:")
    symbol_stats = db.get_symbol_stats()
    print(symbol_stats.to_string(index=False))

#if __name__ == "__main__":
    #demo_usage()