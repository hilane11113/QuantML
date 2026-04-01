# 股票助手 (Stock Assistant)

智能股票+期权分析系统 | A股 + 美股

## 唤醒词

**"股票助手"** 或 **"分析股票"**

## 支持市场

| 市场 | 代码格式 | 分析内容 |
|------|----------|----------|
| **A股** | 6位数字 | 股票+技术指标+基本面+投资组合 |
| **美股** | 字母 | 股票+期权策略+技术分析 |

## 功能模块

### 1. 技术分析 ✅
- 实时价格
- MA5/10/20 均线
- RSI 指标
- 趋势判断

### 2. 基本面分析 ✅ (A股)
- 估值指标 (PE/PB/PS)
- 盈利能力 (ROE/ROA/毛利率)
- 成长性 (营收增速/利润增速)
- 财务状况 (资产负债率)
- 综合评分

### 3. 期权策略 ✅ (美股)
- Bull Put Spread
- Bull Call Spread
- Iron Condor
- 策略评分

### 4. 舆情分析 ✅
- Finnhub 新闻
- Reddit apewisdom 热度

### 5. 投资组合管理 ✅
- 持仓追踪
- 买入/卖出记录
- 盈亏统计
- 绩效评估

### 6. 策略对比 ✅
- 技术指标对比
- 期权策略对比
- 建议生成

### 7. LLM 对话增强 ✅ (新!)
- 自然语言交互
- 意图识别
- 智能问答

## 快速开始

```bash
cd /root/.openclaw/workspace/quant/StockAssistant

# A股分析
python main.py 000001           # 平安银行
python main.py 600519 -f        # 贵州茅台(含基本面)
python main.py 510050           # 上证50ETF

# 美股分析
python main.py TSLA             # 特斯拉
python main.py NVDA            # 英伟达

# 策略对比
python main.py 000001 --compare    # A股技术指标对比
python main.py TSLA --compare     # 美股期权策略对比

# 投资组合
python main.py -p               # 查看持仓
python main.py 000001 --trade buy -q 100 -t 10.5  # 买入
python main.py 000001 --trade sell -q 50 -t 11.0 # 卖出
python main.py --clear          # 清空持仓

# LLM 对话模式 ⭐新!
python main.py --chat          # 交互式对话
```

### 对话模式示例

```
👤 你: 帮我分析一下平安银行
🤖 助手: 平安银行(000001) 目前呈弱势整理态势...


👤 你: 我的持仓情况怎么样
🤖 助手: 您目前持有2只股票...
```

## 新增模块

## 新增模块

### 基本面评分体系

| 维度 | 权重 | 指标 |
|------|------|------|
| 估值 | 30分 | PE越低越高 |
| 盈利 | 40分 | ROE越高越高 |
| 成长 | 20分 | 营收增速 |
| 财务 | 10分 | 负债率越低越好 |

### 投资组合管理

| 功能 | 说明 |
|------|------|
| 持仓追踪 | 记录买入/卖出 |
| 盈亏计算 | 实时盈亏统计 |
| 绩效评估 | 胜率、总盈亏 |

## 项目结构

```
StockAssistant/
├── agents/
│   ├── a_stock_agent.py       # A股分析
│   ├── fundamental_agent.py    # 基本面分析 ⭐新
│   ├── portfolio_agent.py      # 投资组合 ⭐新
│   ├── option_agent.py        # 期权分析
│   ├── technical_agent.py      # 技术指标
│   ├── news_agent.py          # 新闻
│   ├── social_agent.py        # 社交舆情
│   └── ...
├── main.py                    # 主程序
├── portfolio.db              # 持仓数据库
└── decisions.db              # 决策数据库
```

## 数据源

| 市场 | 技术数据 | 基本面 |
|------|---------|--------|
| A股 | tushare | tushare (需权限) |
| 美股 | yfinance | - |
| 舆情 | Finnhub + apewisdom | - |

## TODO

- [ ] 增强基本面数据（需tushare权限）
- [ ] 添加模拟交易执行
- [ ] 添加回测引擎
- [ ] LLM对话增强
