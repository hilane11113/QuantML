-- ============================================================
-- 特斯拉期权策略回测数据库表结构
-- 标的: TSLA | 基准价: 美股开盘后1小时 (10:00 AM EST)
-- 数据库: MySQL 8.0+ 或 PostgreSQL 13+
-- ============================================================

-- ============================================================
-- 1. 标的资产日线数据
-- ============================================================
CREATE TABLE IF NOT EXISTS stock_daily (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    trade_date DATE NOT NULL,
    
    -- 基础价格
    open_price DECIMAL(12, 4),
    high_price DECIMAL(12, 4),
    low_price DECIMAL(12, 4),
    close_price DECIMAL(12, 4),
    volume BIGINT,
    amount DECIMAL(20, 4),
    
    -- 基准价 (开盘后1小时)
    benchmark_price DECIMAL(12, 4) COMMENT '10:00 AM EST 基准价',
    benchmark_time TIME DEFAULT '10:00:00',
    
    -- 预处理数据
    returns DECIMAL(10, 6) COMMENT '日收益率',
    volatility DECIMAL(10, 6),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_symbol_date (symbol, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='标的资产日线数据';

CREATE INDEX idx_stock_date ON stock_daily(trade_date);
CREATE INDEX idx_stock_symbol ON stock_daily(symbol);

-- ============================================================
-- 2. 期权链数据
-- ============================================================
CREATE TABLE IF NOT EXISTS option_chain (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    trade_date DATE NOT NULL,
    
    -- 期权标识
    option_symbol VARCHAR(50) NOT NULL,
    expiry_date DATE NOT NULL,
    strike_price DECIMAL(12, 4) NOT NULL,
    option_type ENUM('C', 'P') NOT NULL COMMENT 'C=Call, P=Put',
    
    -- 价格数据
    bid DECIMAL(12, 4),
    ask DECIMAL(12, 4),
    last_price DECIMAL(12, 4),
    midpoint DECIMAL(12, 4),
    mark_price DECIMAL(12, 4) COMMENT '结算价',
    
    -- Greeks
    delta DECIMAL(12, 6),
    gamma DECIMAL(12, 6),
    theta DECIMAL(12, 6),
    vega DECIMAL(12, 6),
    rho DECIMAL(12, 6),
    
    -- 持仓量
    open_interest BIGINT,
    volume BIGINT,
    
    -- 隐含波动率
    implied_vol DECIMAL(10, 6),
    
    -- 标的价格
    underlying_price DECIMAL(12, 4),
    
    -- 时间价值
    intrinsic_value DECIMAL(12, 4),
    extrinsic_value DECIMAL(12, 4),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_option_date (option_symbol, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='期权链数据';

CREATE INDEX idx_option_date ON option_chain(trade_date);
CREATE INDEX idx_option_expiry ON option_chain(expiry_date);
CREATE INDEX idx_option_strike ON option_chain(strike_price);
CREATE INDEX idx_option_type ON option_chain(option_type);

-- ============================================================
-- 3. 策略信号
-- ============================================================
CREATE TABLE IF NOT EXISTS strategy_signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    trade_date DATE NOT NULL,
    
    -- 信号
    signal_type ENUM('BUY', 'SELL', 'CLOSE', 'HOLD') NOT NULL,
    signal_strength DECIMAL(8, 2) COMMENT '0-100',
    
    -- 策略详情 - 腿1
    leg1_type ENUM('C', 'P'),
    leg1_action ENUM('BUY', 'SELL'),
    leg1_strike DECIMAL(12, 4),
    leg1_expiry DATE,
    leg1_premium DECIMAL(12, 4),
    
    -- 策略详情 - 腿2
    leg2_type ENUM('C', 'P'),
    leg2_action ENUM('BUY', 'SELL'),
    leg2_strike DECIMAL(12, 4),
    leg2_expiry DATE,
    leg2_premium DECIMAL(12, 4),
    
    -- 评分
    total_score DECIMAL(10, 4),
    risk_reward_ratio DECIMAL(10, 4),
    liquidity_score DECIMAL(8, 2),
    iv_score DECIMAL(8, 2),
    theta_score DECIMAL(8, 2),
    
    -- 基准价
    benchmark_price DECIMAL(12, 4),
    
    -- 决策标签
    decision_label ENUM('✅开仓', '🟡试探', '🔴禁止', '⏸️观望') DEFAULT '⏸️观望',
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_strategy_date (strategy_name, symbol, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='策略信号';

CREATE INDEX idx_signals_date ON strategy_signals(trade_date);
CREATE INDEX idx_signals_strategy ON strategy_signals(strategy_name);
CREATE INDEX idx_signals_decision ON strategy_signals(decision_label);

-- ============================================================
-- 4. 回测结果
-- ============================================================
CREATE TABLE IF NOT EXISTS backtest_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    strategy_name VARCHAR(50) NOT NULL,
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    
    -- 回测期间
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    
    -- 基准设置
    benchmark_time TIME DEFAULT '10:00:00',
    
    -- 绩效指标
    total_return DECIMAL(12, 6) COMMENT '总收益率',
    annualized_return DECIMAL(12, 6) COMMENT '年化收益率',
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(12, 6),
    sortino_ratio DECIMAL(10, 4),
    calmar_ratio DECIMAL(10, 4),
    win_rate DECIMAL(8, 6),
    profit_loss_ratio DECIMAL(10, 4),
    
    -- 交易统计
    total_trades INT,
    winning_trades INT,
    losing_trades INT,
    avg_holding_days DECIMAL(10, 2),
    avg_profit DECIMAL(12, 4),
    avg_loss DECIMAL(12, 4),
    
    -- 策略参数
    params JSON,
    
    -- equity curve (日收益)
    equity_curve JSON,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_backtest_strategy (strategy_name),
    INDEX idx_backtest_period (start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='回测结果';

-- ============================================================
-- 5. 多策略组合
-- ============================================================
CREATE TABLE IF NOT EXISTS portfolio (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    
    -- 策略配置
    strategies JSON NOT NULL COMMENT '[{"name": "vertical_spread", "weight": 0.4}, ...]',
    
    -- 资金配置
    capital_allocation DECIMAL(15, 2) DEFAULT 100000,
    rebalance_frequency ENUM('daily', 'weekly', 'monthly') DEFAULT 'weekly',
    
    -- 回测期间
    start_date DATE,
    end_date DATE,
    
    -- 绩效
    total_return DECIMAL(12, 6),
    annualized_return DECIMAL(12, 6),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(12, 6),
    
    -- 组合指标
    portfolio_volatility DECIMAL(12, 6),
    correlation_matrix JSON,
    
    -- 风险指标
    var_95 DECIMAL(12, 6) COMMENT 'Value at Risk 95%',
    cvar_95 DECIMAL(12, 6) COMMENT 'CVaR 95%',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='多策略组合';

-- ============================================================
-- 6. 持仓记录
-- ============================================================
CREATE TABLE IF NOT EXISTS positions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_name VARCHAR(50),
    strategy_name VARCHAR(50),
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    trade_date DATE NOT NULL,
    
    -- 持仓信息
    position_id VARCHAR(50) UNIQUE,
    position_type ENUM('C', 'P'),
    action ENUM('BUY', 'SELL') COMMENT '开仓方向',
    strike_price DECIMAL(12, 4),
    expiry_date DATE,
    quantity INT,
    
    -- 价格
    entry_price DECIMAL(12, 4),
    current_price DECIMAL(12, 4),
    exit_price DECIMAL(12, 4),
    
    -- 盈亏
    pnl DECIMAL(12, 4),
    pnl_pct DECIMAL(12, 6),
    
    -- 状态
    status ENUM('OPEN', 'CLOSED', 'ROLLED') DEFAULT 'OPEN',
    
    -- 持仓天数
    holding_days INT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_positions_date (trade_date),
    INDEX idx_positions_status (status),
    INDEX idx_positions_portfolio (portfolio_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='持仓记录';

-- ============================================================
-- 7. 交易记录
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    portfolio_name VARCHAR(50),
    strategy_name VARCHAR(50),
    symbol VARCHAR(10) NOT NULL DEFAULT 'TSLA',
    trade_date DATE NOT NULL,
    
    -- 交易类型
    trade_type ENUM('OPEN', 'CLOSE', 'ROLL', 'ADJUST') NOT NULL,
    
    -- 期权信息
    option_symbol VARCHAR(50),
    position_id VARCHAR(50),
    position_type ENUM('C', 'P'),
    strike_price DECIMAL(12, 4),
    expiry_date DATE,
    quantity INT,
    
    -- 价格
    price DECIMAL(12, 4),
    commission DECIMAL(10, 4),
    multiplier INT DEFAULT 100,
    total_cost DECIMAL(15, 4),
    
    -- 标的价格
    underlying_price DECIMAL(12, 4),
    benchmark_price DECIMAL(12, 4),
    
    -- 盈亏
    realized_pnl DECIMAL(12, 4),
    realized_pnl_pct DECIMAL(12, 6),
    
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_trades_date (trade_date),
    INDEX idx_trades_strategy (strategy_name),
    INDEX idx_trades_portfolio (portfolio_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易记录';

-- ============================================================
-- 视图: 每日信号汇总
-- ============================================================
CREATE OR REPLACE VIEW v_daily_signals AS
SELECT 
    trade_date,
    strategy_name,
    signal_type,
    signal_strength,
    decision_label,
    benchmark_price,
    risk_reward_ratio,
    created_at
FROM strategy_signals
ORDER BY trade_date DESC, signal_strength DESC;

-- ============================================================
-- 视图: 组合绩效
-- ============================================================
CREATE OR REPLACE VIEW v_portfolio_performance AS
SELECT 
    portfolio_name,
    start_date,
    end_date,
    total_return,
    annualized_return,
    sharpe_ratio,
    max_drawdown,
    (SELECT COUNT(*) FROM trades t WHERE t.portfolio_name = p.portfolio_name) as total_trades
FROM portfolio p
ORDER BY total_return DESC;
