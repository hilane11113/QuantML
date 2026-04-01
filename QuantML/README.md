# QuantML — 期权量化机器学习系统

基于真实交易记录 + 历史回测数据的期权策略优化平台。

## 目录结构

```
QuantML/
├── data/                       # 历史数据
│   ├── market_full.pkl         # TSLA + VIX 合并数据 (5年, 1255个交易日)
│   ├── tsla_full.pkl           # TSLA 历史 + RSI/SMA
│   ├── vix_full.pkl            # VIX 历史
│   ├── spy_full.pkl            # SPY 市场基准
│   └── win_rate_models.pkl    # ML 模型 (LR + RF)
│   └── win_rate_table.json    # 32个组合的历史胜率表
├── models/
│   ├── train_win_rate_model.py # 训练脚本
│   ├── win_rate_predictor.py   # 预测接口
│   └── option_analysis.db       # 合并交易记录 (282笔)
└── README.md
```

## 核心模块

### 1. win_rate_predictor.py — 胜率预测
```python
from win_rate_predictor import predict_win_rate, load_models
load_models()
result = predict_win_rate(rsi=35, vix=18, otm_pct=-7.6,
                         trend='下跌', strategy_type='ShortPut')
# result: {win_rate, confidence, n, ci_low, ci_high, avg_pnl, ...}
```

### 2. train_win_rate_model.py — 训练/重训练
```bash
python3 models/train_win_rate_model.py
# 输出: win_rate_table.json + win_rate_models.pkl
```

### 3. option_analysis.py — 统计分析
```bash
python3 models/option_analysis.py  # 生成 RSI×VIX×OTM 矩阵
```

## 数据积累机制

| 触发 | 操作 |
|------|------|
| 新平仓交易 | 告诉我 → 追加到 option_analysis.db |
| 每50笔真实交易 | 重新训练模型，ML权重提升 |
| 每周 | `fetch_all_data.py --update` 更新市场数据 |

## 当前模型状态

- 真实交易: 34笔
- 回测交易: 248笔
- 总样本: 282笔
- LR CV-AUC: 0.483
- RF CV-AUC: 0.522
- 下次再训练目标: 真实交易 ≥ 50笔

## 策略参数（已集成到引擎）

| VIX 信号 | OTM% | short_ratio |
|----------|------|-------------|
| GREEN (VIX<15) | 5% | 0.95 |
| YELLOW (15≤VIX<25) | 7% | 0.93 |
| RED (VIX≥25) | 10% | 0.90 |

## 入场过滤器规则

| 条件 | 结果 |
|------|------|
| RSI<25 或 RSI>75 | 拒绝 |
| VIX>30 | 拒绝 |
| RSI 30-40 + VIX>25 | 降低仓位30% |
| OTM < 5% | 降低评分30% |

## 融合权重（胜率预测）

- 查表权重: 70%（基于真实交易统计）
- 模型权重: 30%（LR+RF，小样本不可靠）

## 数据来源

- 市场数据: yfinance → pickle 持久化
- 真实交易: Excel → SQLite → 训练
- 更新频率: 每日增量更新市场数据，每周重训练
