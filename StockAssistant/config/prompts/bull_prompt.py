#!/usr/bin/env python3
"""
看多 Prompt 构建函数 (bull_prompt.py)

对应 BullResearcher.build_prompt() 的逻辑：
- 论点每条 ≤80 字
- 截断规则（bull_history/bear_history/current_bear 过长时截断）
- 输出 bullet points，3-5 个核心论点
"""

__all__ = ['BullPromptBuilder']


class BullPromptBuilder:
    """构建看多研究员的 prompt"""

    @staticmethod
    def build_prompt(state):
        """
        构建看多研究员的 prompt。
        
        Args:
            state: dict，包含 situation, bull_history, bear_history,
                   current_bear_argument, past_memories 等字段
        
        Returns:
            str: 构造好的 prompt 字符串
        """
        situation = state.get('situation', '')
        bull_history = state.get('bull_history', '')
        bear_history = state.get('bear_history', '')
        current_bear = state.get('current_bear_argument', '')
        memories = state.get('past_memories', [])

        # 截断历史（避免 prompt 过长导致模型返回空）
        if len(bull_history) > 300:
            bull_history = bull_history[:300] + '\n...（历史论点已截断）'
        if len(bear_history) > 300:
            bear_history = bear_history[:300] + '\n...（历史论点已截断）'
        if len(current_bear) > 200:
            current_bear = current_bear[:200] + '\n...（空头论点已截断）'

        past_str = BullPromptBuilder._format_memories(memories)

        prompt = f"""你是看多分析师，负责为股票投资构建有力的买入论点。

你的任务：
1. 基于提供的研报数据，构建看多的有力证据
2. 重点强调：增长潜力、竞争优势、正向指标
3. 用具体数据反驳空头的论点
4. 参考历史相似情景，避免重复过去的错误

当前市场情况：
{situation}

历史看多论点：
{bull_history}

最新空头论点（你需要反驳）：
{current_bear}

历史相似情景与反思：
{past_str}

请用"- "开头列出3-5个核心看多论点，每个论点不超过80字，总字数不超过300字。
"""
        return prompt

    @staticmethod
    def _format_memories(memories):
        """格式化历史记忆"""
        if not memories:
            return "无历史相似情景"
        lines = []
        for m in memories:
            lines.append(
                f"- [{m.get('timestamp','')} {m.get('symbol','')} "
                f"${m.get('price',0):.2f}] "
                f"当时决策:{m.get('final_action','')} "
                f"结果:{m.get('outcome','')} "
                f"多头理由:{m.get('bull_argument','')} "
                f"空头理由:{m.get('bear_argument','')}"
            )
        return '\n'.join(lines) if lines else "无历史相似情景"
