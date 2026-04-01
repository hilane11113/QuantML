#!/usr/bin/env python3
"""
研究经理 Prompt 构建函数 (manager_prompt.py)

对应 ResearchManager.build_prompt() 的逻辑：
- rationale ≤30 字
- max_tokens=800
- 输出结构化 JSON 决策
"""

__all__ = ['ManagerPromptBuilder']


class ManagerPromptBuilder:
    """构建研究经理的 prompt"""

    @staticmethod
    def build_prompt(state):
        """
        构建研究经理的 prompt。
        
        Args:
            state: dict，包含 situation, history, past_memories, option_data 等字段
        
        Returns:
            str: 构造好的 prompt 字符串
        """
        situation = state.get('situation', '')
        history = state.get('history', '')
        memories = state.get('past_memories', [])
        option_data = state.get('option_data', {})

        # 获取最佳策略
        strategies = option_data.get('strategies', []) if isinstance(option_data, dict) else []
        best = strategies[0] if strategies and isinstance(strategies[0], dict) else {}

        # 截断辩论历史（避免 prompt 过长导致模型返回空）
        if len(history) > 400:
            history = history[:400] + '\n...（辩论历史已截断）'

        past_str = ManagerPromptBuilder._format_memories(memories)

        prompt = f"""你是投资组合经理兼辩论主持人。你的职责是：

1. 仔细评估本轮辩论，判定最终立场
2. 不能因为两边都有道理就和稀泥，必须给出明确决策
3. 决策：强烈买入 / 买入 / 观望 / 轻仓观望 / 拒绝
4. 同时给出具体的交易计划

当前市场情况：
{situation}

辩论历史：
{history}

推荐策略信息：
- 策略类型：{best.get('type', 'N/A')}
- 综合评分：{best.get('composite_score', 'N/A')}
- 风险回报比：{best.get('rr_ratio', 'N/A')}
- 建议仓位：{best.get('position', 'N/A')}%
- Theta：{best.get('theta', 'N/A')}/天
- 到期日：{best.get('actual_expiry_date', 'N/A')}

历史反思（避免重复犯错）：
{past_str}

请严格按以下JSON格式输出（不要有其他内容）：
{{
    "decision": "你的最终决策（买入/观望/拒绝等）",
    "confidence": "决策信心度（高/中/低）",
    "rationale": "30字以内的决策理由",
    "action_plan": "具体操作计划，包括入场时机、仓位、止损位",
    "risk_note": "主要风险提示"
}}
"""
        return prompt

    @staticmethod
    def _format_memories(memories):
        """格式化历史记忆"""
        if not memories:
            return "无历史反思记录。"
        lines = []
        for m in memories:
            lines.append(
                f"- [{m.get('timestamp','')}] {m.get('symbol','')} "
                f"行动:{m.get('final_action','')} "
                f"结果:{m.get('outcome','')} "
                f"教训:{m.get('lessons', m.get('pnl_info',''))}"
            )
        return '\n'.join(lines) if lines else "无历史反思记录。"
