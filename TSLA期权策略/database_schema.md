# 特斯拉期权策略回测数据库表结构设计

## 目标
- 标的: TSLA (特斯拉)
- 基准价: 美股开盘后1小时 (约 10:00 AM EST)
- 对接: 微软 Qlib

---

## 表结构设计 (MySQL/PostgreSQL)

### 1. 标的资产日线数据 (stock_daily)
存储特斯拉股票的基础价格数据

```sql
CREATE TABLE stock_daily (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    date DATE NOT NULL,
    open DECIMAL(10, 4),
    high DECIMAL(10, 4),
    low DECIMAL(10, 4),
    close DECIMAL(10, 4),
    volume BIGINT,
    amount DECIMAL(20, 4),
    
    -- 基准价字段 (开盘后1小时)
    benchmark_price DECIMAL(10, 4),  -- 10:00 AM EST 收盘价
    benchmark_time TIME DEFAULT '10:00:00',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(symbol, date)
);

-- Qlib 格式索引
CREATE INDEX idx_stock_daily_date ON stock_daily(date);
CREATE INDEX idx_stock_daily_symbol ON stock_daily(symbol);
```

### 2. 期权链数据 (option_chain)
存储每日期权链数据

```sql
CREATE TABLE option_chain (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,  -- 标的: TSLA
    date DATE NOT NULL,           -- 数据日期
    
    -- 期权基本信息
    option_symbol VARCHAR(30) NOT NULL,  -- 如: TSLA250307C00400000
    expiry_date DATE NOT NULL,           -- 到期日
    strike_price DECIMAL(10, 4) NOT NULL, -- 行权价
    option_type VARCHAR(1) NOT NULL,      -- C (Call) 或 P (Put)
    
    -- 价格数据
    bid DECIMAL(10, 4),
    ask DECIMAL(10, 4),
    last_price DECIMAL(10, 4),
    midpoint DECIMAL(10, 4),  -- (bid + ask) / 2
    mark DECIMAL(10, 4),       -- 结算价
    
    -- Greeks
    delta DECIMAL(10, 6),
    gamma DECIMAL(10, 6),
    theta DECIMAL(10, 6),
    vega DECIMAL(10, 6),
    rho DECIMAL(10, 6),
    
    -- 持仓量数据
    open_interest BIGINT,
    volume BIGINT,
    
    -- 隐含波动率
    implied_vol DECIMAL(10, 6),
    
    -- 标的价格 (用于计算)
    underlying_price DECIMAL(10, 4),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(option_symbol, date)
);

CREATE INDEX idx_option_chain_date ON option_chain(date);
CREATE INDEX idx_option_chain_expiry ON option_chain(expiry_date);
CREATE INDEX idx_option_chain_strike ON option_chain(strike_price);
CREATE INDEX idx_option_chain_type ON option_chain(option_type);
```

### 3. 策略信号表 (strategy_signals)
存储单策略的买卖信号

```sql
CREATE TABLE strategy_signals (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,  -- 策略名称: vertical_spread, iron_condor等
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    date DATE NOT NULL,
    
    -- 信号内容
    signal_type VARCHAR(10) NOT NULL,  -- BUY, SELL, CLOSE, HOLD
    signal_strength DECIMAL(5, 2),      -- 0-100 信号强度
    
    -- 策略详情
    leg1_type VARCHAR(1),   -- C 或 P
    leg1_action VARCHAR(4), -- BUY 或 SELL
    leg1_strike DECIMAL(10, 4),
    leg1_expiry DATE,
    
    leg2_type VARCHAR(1),
    leg2_action VARCHAR(4),
    leg2_strike DECIMAL(10, 4),
    leg2_expiry DATE,
    
    -- 评分
    score DECIMAL(10, 4),
    risk_reward_ratio DECIMAL(10, 4),
    liquidity_score DECIMAL(5, 2),
    iv_score DECIMAL(5, 2),
    theta_score DECIMAL(5, 2),
    
    -- 基准价 (开仓时使用)
    benchmark_price DECIMAL(10, 4),
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(strategy_name, symbol, date)
);

CREATE INDEX idx_signals_date ON strategy_signals(date);
CREATE INDEX idx_signals_strategy ON strategy_signals(strategy_name);
```

### 4. 回测结果表 (backtest_results)
存储单策略回测结果

```sql
CREATE TABLE backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    
    -- 回测期间
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    
    -- 基准价设置
    benchmark_time TIME DEFAULT '10:00:00',  -- 开盘后1小时
    
    -- 绩效指标
    total_return DECIMAL(10, 6),      -- 总收益率
    annualized_return DECIMAL(10, 6),  -- 年化收益率
    sharpe_ratio DECIMAL(10, 4),       -- 夏普比率
    max_drawdown DECIMAL(10, 6),       -- 最大回撤
    win_rate DECIMAL(10, 6),           -- 胜率
    
    -- 交易统计
    total_trades INT,
    winning_trades INT,
    losing_trades INT,
    
    -- 持仓统计
    avg_holding_days DECIMAL(10, 2),
    avg_profit DECIMAL(10, 4),
    avg_loss DECIMAL(10, 4),
    
    -- 策略参数
    params JSONB,  -- 策略参数存储
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_backtest_strategy ON backtest_results(strategy_name);
CREATE INDEX idx_backtest_period ON backtest_results(start_date, end_date);
```

### 5. 多策略组合表 (portfolio)
存储多策略组合配置和结果

```sql
CREATE TABLE portfolio (
    id SERIAL PRIMARY KEY,
    portfolio_name VARCHAR(50) NOT NULL,  -- 组合名称
    description TEXT,
    
    -- 组合配置
    strategies JSONB NOT NULL,  -- 策略配置: [{"name": "vertical_spread", "weight": 0.5}, ...]
    
    -- 权重分配
    capital_allocation DECIMAL(10, 4),  -- 总资金分配
    rebalance_frequency VARCHAR(20),   -- 调仓频率: daily, weekly, monthly
    
    -- 回测期间
    start_date DATE,
    end_date DATE,
    
    -- 绩效指标
    total_return DECIMAL(10, 6),
    annualized_return DECIMAL(10, 6),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 6),
    
    -- 组合指标
    portfolio_volatility DECIMAL(10, 6),
    correlation_matrix JSONB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6. 持仓记录 (positions)
存储每日持仓状态

```sql
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_name VARCHAR(50),
    strategy_name VARCHAR(50),
    symbol VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    
    -- 持仓详情
    position_type VARCHAR(1),   -- C 或 P
    action VARCHAR(4),          -- BUY 或 SELL (开仓方向)
    strike_price DECIMAL(10, 4),
    expiry_date DATE,
    quantity INT,
    
    -- 价格
    entry_price DECIMAL(10, 4),
    current_price DECIMAL(10, 4),
    pnl DECIMAL(10, 4),         -- 盈亏
    
    -- 状态
    status VARCHAR(10) DEFAULT 'OPEN',  -- OPEN, CLOSED
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_positions_date ON positions(date);
CREATE INDEX idx_positions_status ON positions(status);
```

### 7. 交易记录 (trades)
存储每笔交易详情

```sql
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    portfolio_name VARCHAR(50),
    strategy_name VARCHAR(50),
    symbol VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    
    -- 交易类型
    trade_type VARCHAR(10) NOT NULL,  -- OPEN, CLOSE, ROLL
    
    -- 期权详情
    option_symbol VARCHAR(30),
    position_type VARCHAR(1),   -- C 或 P
    strike_price DECIMAL(10, 4),
    expiry_date DATE,
    quantity INT,
    
    -- 价格
    price DECIMAL(10, 4),
    commission DECIMAL(10, 4),
    multiplier INT DEFAULT 100,
    
    -- 标的价格
    underlying_price DECIMAL(10, 4),
    benchmark_price DECIMAL(10, 4),
    
    -- 盈亏
    pnl DECIMAL(10, 4),
    pnl_pct DECIMAL(10, 6),
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_date ON trades(trade_date);
CREATE INDEX idx_trades_strategy ON trades(strategy_name);
```

---

## Qlib 对接

### 数据目录结构
```
qlib_data/
└── csv/
    └── TSLA/
        ├── daily/
        │   └── TSLA.csv
        ├── option_chain/
        │   └── TSLA.csv
        └── signals/
            └── TSLA.csv
```

### Qlib 特征列命名规范
```python
# 股票数据 ($symbol/daily/$symbol.csv)
# $symbol = TSLA
$TSLA/
├── $TSLA.csv  # 日线数据
# 格式: date,open,high,low,close,volume,amount,benchmark_price

# 或使用 Qlib 的 BinCSVDump
```

### 示例: 将数据导出为 Qlib 格式

```python
import pandas as pd
from qlib.data import D
from qlib.tests.data import TestData

# 读取数据库
df = pd.read_sql("SELECT * FROM stock_daily WHERE symbol='TSLA'", conn)

# 转换为 Qlib 格式
qlib_df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'benchmark_price']]
qlib_df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'benchmark_price($TSLA)']
qlib_df.set_index('date').to_csv('qlib_data/csv/TSLA/daily/TSLA.csv')
```

---

## 基准价计算逻辑

```python
def get_benchmark_price(symbol='TSLA', date):
    """
    获取美股开盘后1小时的基准价
    美股开盘时间: 9:30 AM EST
    基准价: 10:00 AM EST 的价格
    """
    # 方式1: 使用当日9:30-10:00的区间价格
    # 方式2: 使用9:30开盘价+1小时后的价格
    # 方式3: 使用加权平均价格 (VWAP)
    
    return benchmark_price
```

---

## 使用示例

### 创建表
```bash
psql -U user -d options_db -f tables.sql
```

### 插入基准价数据
```sql
INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, benchmark_price)
VALUES ('TSLA', '2026-03-14', 260.00, 265.00, 258.00, 262.50, 50000000, 263.00);
```

### 查询信号
```sql
SELECT * FROM strategy_signals 
WHERE date = '2026-03-14' 
AND strategy_name = 'vertical_spread'
ORDER BY score DESC;
```
