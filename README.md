# QuantML — 期权量化机器学习系统

**TSLA 期权策略的多层分析引擎**，整合多 Agent 协作、胜率预测、入场过滤三大模块。

---

## 🏗️ 项目架构

```
QuantML/  ← GitHub 仓库根目录
│
├── StockAssistant/          # 多 Agent 分析引擎
│   ├── agents/              # Agent 节点
│   │   ├── tech_agent.py       # 技术分析（RSI/均线/支撑阻力）
│   │   ├── social_agent.py     # 舆情分析（关键词+LLM+apewisdom）
│   │   ├── option_agent.py    # 期权分析（VIX/IV/希腊值/策略评分）
│   │   ├── researcher.py       # 多轮辩论（多空论点聚合）
│   │   └── risk_agent.py      # 风险评估（仓位/止损/风控建议）
│   ├── strategy_engine.py     # 策略引擎（含胜率预测+入场过滤器）
│   ├── unified_fetcher.py     # 统一数据获取（yfinance 一次拉取）
│   └── demo_multi_agent.py  # 主入口，按格式四输出
│
├── TSLA期权策略/            # 策略脚本（执行层）
│   ├── multi_strategy_v2.py  # 多策略组合 V2
│   ├── vertical_spread_v6.py  # 垂直价差 V6
│   └── strategy_engine.py    # 策略引擎（引用 StockAssistant）
│
└── QuantML/                # ML 模块（预测层）
    ├── models/
    │   ├── win_rate_predictor.py   # 胜率预测接口
    │   ├── train_win_rate_model.py # 训练脚本
    │   ├── win_rate_table.json    # 32组合历史胜率表
    │   └── win_rate_models.pkl    # LR+RF 模型
    └── data/
        └── market_full.pkl        # TSLA 5年市场数据
```

---

## 🔄 模块调用关系

```
用户请求
    ↓
demo_multi_agent.py（入口，按格式四输出）
    ↓
UnifiedDataFetcher → yfinance 一次获取（price/RSI/VIX/IV）
    ↓
[并行] TechAgent + SocialAgent + OptionAgent
    ↓
StrategyEngine（计算策略 + 入场过滤 + 胜率预测）
    ↓
ResearcherTeam（多空辩论）→ RiskAgent（风控）→ 综合结论
```

---

## 📊 核心功能

### 1. 多 Agent 协作分析
- 并行调用 5 个 Agent：技术面 + 舆情 + 期权 + 辩论 + 风控
- 辩论模块支持多轮论证，输出多空论点及置信度

### 2. 策略引擎（基于282笔数据分析优化）
- **VIX 信号参数**：GREEN(OTM 5%) / YELLOW(OTM 7%) / RED(OTM 10%)
- **入场过滤器**：RSI极端值/VIX>30/OTM<5% → 降低评分或拒绝
- **预测胜率**：查表(70%)+模型(30%) 融合输出

### 3. 胜率预测
- 32 个 RSI×VIX×OTM 组合的历史胜率统计
- LR + RF 机器学习模型（交叉验证）
- 置信区间：样本≥20笔→高 / ≥5笔→中 / <5笔→低

---

## 🚀 快速使用

### 多 Agent 分析（格式四输出）
```bash
cd StockAssistant
python3 demo_multi_agent.py TSLA
```

### 多策略分析
```bash
cd ../TSLA期权策略
python3 multi_strategy_v2.py TSLA
```

### 胜率预测
```python
from QuantML.models.win_rate_predictor import predict_win_rate
result = predict_win_rate(
    rsi=35, vix=18, otm_pct=-7.6,
    trend='下跌', strategy_type='ShortPut'
)
# result: {win_rate: 0.73, confidence: '中', n: 15, ci_low: 0.61, ci_high: 0.84}
```

---

## 📈 数据积累机制

| 触发 | 操作 |
|------|------|
| 新平仓交易 | 追加到交易记录 → 同步重训练 |
| 每50笔真实交易 | 重新训练模型，ML权重提升 |
| 每周 | `fetch_all_data.py --update` 更新市场数据 |

---

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成投资建议。期权交易存在风险，实际亏损由投资者自行承担。
