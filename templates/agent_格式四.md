# 多 Agent 协作分析报告模板

> 用于 StockAssistant 多 Agent 协作分析报告的固定格式定义
> 关联文件: `demo_multi_agent.py`

---

## 📋 报告结构

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🤖 {symbol} 多 Agent 协作分析报告  📅 {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ Agent 1: TechAgent (技术分析) ━━━━━━━━━━━━━━━━━━━
  📊 价格: ${price}
  📈 趋势: {trend}
  📉 RSI: {rsi} ({超卖/超买/中性})
  🛡️ 支撑: ${support} | 阻力: ${resistance}

━━━ Agent 2: SocialAgent (舆情分析) ━━━━━━━━━━━━━━━━━━━
  {🔴/🟢/🟡} 关键词情绪: {sentiment} ({score})
  {🔴/🟢/🟡} LLM情绪: {llm_sentiment} (评分: {llm_score})
  {🔴/🟢/🟡} apewisdom: {sentiment} (mentions={mentions})
  💬 LLM理由: {reason}

━━━ Agent 3: OptionAgent (期权分析) ━━━━━━━━━━━━━━━━━━━
  📊 VIX: {🟢🔴🟡} {vix_signal} ({vix_val})
  📉 IV: {iv_val}% | 舆情: {sentiment_label}
  {✅/🟡/🔴} {i}. {type} | 评分:{score} | 预测胜率:{win_rate} | {decision} | 仓位:{position}%
      到期:{expiry_date} ({days}天) | {strike_info}
      权利金:${credit} | 最大亏损:${max_loss} | 最大盈利:${max_profit}{theta_info}

  *Iron Condor 例：卖$short_put/买$long_putPut, 卖$short_call/买$long_callCall（4条腿）*

━━━ 🤖 ML 增强分析 (VolatilityPredictor) ━━━━━━━━━━━━━━━
  🧠 模型状态: {ml_enabled/未加载/未训练}
  📈 预测波动率: {ml_predicted_vol} (调整后: {ml_vol_adj})
  🏷️ 波动率 Regime: {🟢低/🟡正常/🔴高} {ml_regime}
  📊 VIX: {vix_val} ({vix_signal})
  📉 RSI(14): {ml_rsi_14} | MACD: {ml_macd_signal}
  🎯 ML信号: {ml_action}
  💬 ML理由: {ml_reason}
  ✅ 增强决策: {enhanced_decision}

━━━ Agent 4: ResearcherTeam (多轮辩论 {rounds}轮) ━━━━━━━

  🟢 === 看多论点 ===

  ── 第1轮看多 ──
    • {核心观点1}
    • {核心观点2}
    • {核心观点3}
    ...

  {完整论点正文，最多800字符}

  🔴 === 看空论点 ===

  ── 第1轮看空 ──
    • {核心观点1}
    • {核心观点2}
    ...

  {完整论点正文}

  ── 第2轮看多 ──
    • {核心观点1}
    ...

  ── 第2轮看空 ──
    • {核心观点1}
    ...

──────────────────────────────────────────────────
  ⚔️  综合决策
──────────────────────────────────────────────────
  {🟢/🔴/🟡} 决策: {decision}   {🟢/🔴/🟡} 信心: {confidence}
  📝 理由: {rationale}
  📋 计划: {action_plan}
  ⚠️ 风险: {risk_note}

━━━ Agent 5: RiskAgent (风险评估) ━━━━━━━━━━━━━━━━━━━━━
  🛡️ 风险等级: {🔴HIGH/🟡MEDIUM/🟢LOW}
  📊 仓位建议: {position_size}
  🛑 止损位: {stop_loss}
  💡 建议: {recommendation}
  💾 辩论记忆已保存 (ID={debate_id})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📋 综合结论
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 市场: ${price} | VIX {vix} ({vix_signal})
  💬 舆情: {sentiment_label}
  📈 策略: {best_strategy_type}
  🧠 ML: {ml_action} ({ml_regime}区)
  ⚔️ 辩论: {decision} ({confidence})
  🛡️ 风控: {risk_level} | {position_size}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  💡 综合建议: {action_plan}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎨 Emoji 规范

| 类型 | Emoji | 条件 |
|------|-------|------|
| 看多情绪 | 🟢 | bullish / 买入 / 强烈买入 |
| 看空情绪 | 🔴 | bearish / 拒绝 / 卖出 / HIGH |
| 中性情绪 | 🟡 | neutral / 观望 / 试探 / MEDIUM |
| 开仓信号 | ✅ | decision 包含"开仓" |
| 试探信号 | 🟡 | decision 包含"试探" |
| 禁止信号 | 🔴 | decision 包含"禁止" |
| VIX GREEN | 🟢 | vix_signal == 'GREEN' |
| VIX RED | 🔴 | vix_signal == 'RED' |

---

## 📝 修改日志

### 2026-03-26 v1.0
- 初始版本，从 demo_multi_agent.py 提取
- 5 Agent 独立区块格式
- 辩论过程（多空论点 + 决策）完整展示

### 2026-03-26 v1.1
- Agent 4 辩论展示优化
  - 每轮论点展示 800 字符（之前 280）
  - 自动提取 **加粗** 要点作为核心观点
  - 决策部分完整展示，不截断
  - 用分隔线 `──` 区分轮次

### 2026-03-27 v1.2
- 新增 **ML 增强分析区块**（Agent 3.5），位于 OptionAgent 与 ResearcherTeam 之间
  - 展示 VolatilityPredictor 的预测波动率、Regime、RSI、MACD、ML信号及置信度
  - 综合结论区新增 ML 一行（信号 + Regime + 置信度）
  - ml_signal 数据来源: `option['ml_signal']`（由 OptionAgent 调用 `MLSignalGenerator` 生成）

### 2026-04-01 v1.4
- Agent 3: 策略新增**到期日**和**预测胜率**字段
  - 到期: {expiry_date} ({days}天)
  - 预测胜率: {win_rate} (置信度:{confidence} | 历史样本:{n}笔)
- ML 区块: 新增波动率错配 (mispricing) 和动量背离 (divergence) 展示
- 模板修改日志更新
- Agent 3: 移除重复的 strike_info 打印行
- Agent 3: Iron Condor 展示完整4条腿（`卖$short_put/买$long_putPut, 卖$short_call/买$long_callCall`）
- Agent 4: `max_tokens` 500 → 1200，确保多轮辩论论点完整不断截
- ML 区块: 移除 ML信号行中的"置信度"字段（为固定规则赋值，无参考价值）
- 综合结论: ML 行移除置信度
- 模板同步更新上述所有变更

---

## 🔗 关联文件

- 主脚本: `/root/.openclaw/workspace/quant/StockAssistant/demo_multi_agent.py`
- Agent 定义:
  - `agents/technical_agent.py` → TechAgent
  - `agents/social_agent.py` → SocialAgent
  - `agents/option_agent.py` → OptionAgent
  - `agents/researcher.py` → ResearcherTeam (BullResearcher / BearResearcher / ResearchManager)
  - `agents/risk_agent.py` → RiskAgent
  - `agents/memory_agent.py` → MemoryAgent

---

## 💡 使用说明

当需要修改报告格式时：
1. 更新本模板文件
2. 对应修改 `demo_multi_agent.py` 中的 print 语句
3. 确保 emoji 规范一致
4. 更新修改日志
