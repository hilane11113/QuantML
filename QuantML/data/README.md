# 数据文件说明

本目录包含胜率预测模型依赖的历史数据文件。

## 文件说明

| 文件 | 说明 |
|------|------|
| `win_rate_table.json` | 32个 RSI×VIX×OTM 组合的历史胜率表 |
| `win_rate_models.pkl` | 序列化后的 LR + RF 模型及编码器 |

## 训练数据

- `market_full.pkl`（TSLA 5年历史数据）不在本仓库中，需自行准备
- `期权记录.xlsx`（真实交易记录）不在本仓库中

## 重新训练

如需重新训练模型，请参考：
```bash
python QuantML/models/train_win_rate_model.py
```
