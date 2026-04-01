#!/usr/bin/env python3
"""
ResearcherAgent - 多轮辩论研究员
借鉴 TradingAgents 的多空辩论机制
"""

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
import json
import requests
import sys
import os

def call_llm(prompt, system_prompt="你是一个专业的金融分析师", model=None, max_tokens=1200, temperature=0.7, concise=False):
    """
    调用 LLM（OpenAI-compatible 格式）
    concise=True: 要求模型只输出核心观点（bullet points），不输出长段落
    """
    if model is None:
        model = LLM_MODEL
    try:
        url = f"{LLM_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        # concise 模式：要求输出核心要点，降低 max_tokens
        if concise:
            tokens = min(max_tokens, 800)
            messages[0]["content"] = system_prompt + "\n\n【重要】请只输出3-5个核心论点，用\"- \"开头，每个论点不超过80字，总字数不超过300字，不要输出完整段落。"
        else:
            tokens = max_tokens

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": tokens,
            "temperature": temperature
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        result = resp.json()
        if result.get('choices') and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            if content and content.strip():
                return content
        if result.get('error'):
            print(f"LLM API Error: {result['error']}", flush=True)
    except Exception as e:
        print(f"LLM Error: {e}", flush=True)
    # 重试一次
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        result = resp.json()
        if result.get('choices') and len(result['choices']) > 0:
            return result['choices'][0]['message']['content']
        if result.get('error'):
            print(f"LLM API Error (retry): {result['error']}", flush=True)
    except Exception as e:
        print(f"LLM Error (retry): {e}", flush=True)
    return ""


class BullResearcher:
    """看多研究员 - 借鉴 TradingAgents bull_researcher.py"""

    def __init__(self, memory_agent=None):
        self.memory_agent = memory_agent

    def build_prompt(self, state):
        """构建看多研究员的 prompt"""
        situation = state.get('situation', '')
        bull_history = state.get('bull_history', '')
        bear_history = state.get('bear_history', '')
        current_bear = state.get('current_bear_argument', '')
        memories = state.get('past_memories', [])

        # 截断历史（避免 prompt 过长导致模型返回空）
        # 截断时保证不破坏 [BULL_ARG] 或 [/BULL_ARG] 标签完整性
        def safe_truncate(text, limit):
            if len(text) <= limit:
                return text
            # 找到最后一个完整的 [BULL_ARG] 块
            truncated = text[:limit]
            last_open = truncated.rfind('[BULL_ARG]')
            last_close = truncated.rfind('[/BULL_ARG]')
            # 如果最后一个 [BULL_ARG] 没有对应的 [/BULL_ARG]，截断到它之前
            if last_open != -1 and (last_close == -1 or last_close < last_open):
                return truncated[:last_open]
            return truncated

        bull_history = safe_truncate(bull_history, 300)
        bear_history = safe_truncate(bear_history, 300)
        if len(current_bear) > 200:
            current_bear = current_bear[:200] + '\n...（空头论点已截断）'

        past_str = self._format_memories(memories)

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

    def _format_memories(self, memories):
        if not memories:
            return "无历史相似情景"
        lines = []
        for m in memories:
            lines.append(
                f"- [{m.get('timestamp','')} {m.get('symbol','')} ${m.get('price',0):.2f}] "
                f"当时决策:{m.get('final_action','')} 结果:{m.get('outcome','')} "
                f"多头理由:{m.get('bull_argument','')} 空头理由:{m.get('bear_argument','')}"
            )
        return '\n'.join(lines) if lines else "无历史相似情景"

    def analyze(self, state):
        system_prompt = """你是一个专业的金融看多分析师，擅长构建基于证据的买入论点。
风格：简洁有力，3-5个核心观点，每个观点一句话。"""

        prompt = self.build_prompt(state)
        response = call_llm(prompt, system_prompt, max_tokens=500, temperature=0.7, concise=True)

        argument = f"\n[BULL_ARG]\n{response}\n[/BULL_ARG]\n"
        new_state = {
            'bull_history': bull_history + '\n' + argument if (bull_history := state.get('bull_history', '')) else argument,
            'history': (state.get('history', '') + '\n' + argument),
            'current_bull_argument': argument,
            'count': state.get('count', 0) + 1,
        }
        return new_state, response


class BearResearcher:
    """看空研究员 - 借鉴 TradingAgents bear_researcher.py"""

    def __init__(self, memory_agent=None):
        self.memory_agent = memory_agent

    def build_prompt(self, state):
        situation = state.get('situation', '')
        bear_history = state.get('bear_history', '')
        current_bull = state.get('current_bull_argument', '')
        memories = state.get('past_memories', [])

        # 截断历史（避免 prompt 过长导致模型返回空）
        if len(bear_history) > 150:
            bear_history = bear_history[:150] + '\n...（历史已截断）'
        if len(current_bull) > 200:
            current_bull = current_bull[:200] + '\n...（多头论点已截断）'

        past_str = self._format_memories(memories)

        prompt = f"""你是看空分析师，负责为股票投资构建有力的卖出/观望论点。

你的任务：
1. 基于提供的研报数据，构建看空的有力证据
2. 重点强调：风险因素、竞争劣势、负向指标
3. 用具体数据反驳多头的论点
4. 参考历史相似情景，避免重复过去的错误

当前市场情况：
{situation}

历史空头论点：
{bear_history}

最新多头论点（你需要反驳）：
{current_bull}

历史相似情景与反思：
{past_str}

请用"- "开头列出3-5个核心看空论点，每个论点不超过80字，总字数不超过300字。
"""
        return prompt

    def _format_memories(self, memories):
        if not memories:
            return "无历史相似情景"
        lines = []
        for m in memories:
            lines.append(
                f"- [{m.get('timestamp','')} {m.get('symbol','')} ${m.get('price',0):.2f}] "
                f"当时决策:{m.get('final_action','')} 结果:{m.get('outcome','')} "
                f"多头理由:{m.get('bull_argument','')} 空头理由:{m.get('bear_argument','')}"
            )
        return '\n'.join(lines) if lines else "无历史相似情景"

    def analyze(self, state):
        system_prompt = """你是一个专业的金融空头分析师，擅长识别风险和负面因素。
风格：简洁有力，3-5个核心观点，每个观点一句话。"""

        prompt = self.build_prompt(state)
        response = call_llm(prompt, system_prompt, max_tokens=500, temperature=0.7, concise=True)

        argument = f"\n[BEAR_ARG]\n{response}\n[/BEAR_ARG]\n"

        new_state = {
            'bear_history': bear_history + '\n' + argument if (bear_history := state.get('bear_history', '')) else argument,
            'history': (state.get('history', '') + '\n' + argument),
            'current_bear_argument': argument,
            'count': state.get('count', 0) + 1,
        }
        return new_state, response


class ResearchManager:
    """
    研究经理 - 借鉴 TradingAgents research_manager.py
    裁判角色：综合多空辩论，给出最终决策
    """

    def __init__(self, memory_agent=None):
        self.memory_agent = memory_agent

    def build_prompt(self, state):
        situation = state.get('situation', '')
        history = state.get('history', '')
        memories = state.get('past_memories', [])
        option_data = state.get('option_data', {})

        # 获取最佳策略
        strategies = option_data.get('strategies', [])
        best = strategies[0] if strategies else {}

        # 截断辩论历史（避免 prompt 过长导致模型返回空）
        if len(history) > 400:
            history = history[:400] + '\n...（辩论历史已截断）'

        past_str = self._format_memories(memories)

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

    def _format_memories(self, memories):
        if not memories:
            return "无历史反思记录。"
        lines = []
        for m in memories:
            lines.append(
                f"- [{m.get('timestamp','')}] {m.get('symbol','')} "
                f"行动:{m.get('final_action','')} 结果:{m.get('outcome','')} "
                f"教训:{m.get('lessons', m.get('pnl_info',''))}"
            )
        return '\n'.join(lines) if lines else "无历史反思记录。"

    def decide(self, state):
        system_prompt = """你是一个专业的投资组合经理，决策果断、不和稀泥。
你必须给出明确的决策（买入/观望/拒绝），并附带具体行动计划。"""

        prompt = self.build_prompt(state)

        # 先尝试结构化输出，如果失败则回退
        response = call_llm(prompt, system_prompt, max_tokens=800, temperature=0.3)

        # 解析 JSON
        decision_data = self._parse_json(response)
        if not decision_data:
            # 回退到非结构化
            decision_data = {
                'decision': '观望',
                'confidence': '低',
                'rationale': '决策解析失败，建议谨慎',
                'action_plan': response[:200] if response else '无法生成计划',
                'risk_note': '解析失败，保守操作'
            }

        return decision_data, response

    def _parse_json(self, response):
        import re
        def try_parse(text):
            try:
                return json.loads(text, strict=False), None
            except json.JSONDecodeError:
                pass
            m = re.search(r'\{[\s\S]*', text)
            if m:
                try:
                    return json.loads(m.group(0), strict=False), 'partial'
                except json.JSONDecodeError:
                    pass
            return None, 'failed'

        # 方法1：直接解析
        result, status = try_parse(response)
        if result and status is None:
            return result

        # 方法2：提取 ```json 块
        m = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if m:
            result, status = try_parse(m.group(1))
            if result:
                return result

        # 方法3：提取各字段（宽松匹配，支持截断无引号情况）
        partial = {}
        # 标准字段（有闭合引号）
        for field in ['decision', 'confidence']:
            m = re.search(f'"{field}"\\s*:\\s*"([^"\\n]*)"', response)
            if m:
                partial[field] = m.group(1).replace('\\"', '"').replace('\\n', '\n')
        # rationale / action_plan / risk_note：可能被截断，用宽松匹配
        for field in ['rationale', 'action_plan', 'risk_note']:
            # 匹配到下一个闭合引号，或到截断处
            m = re.search(f'"{field}"\\s*:\\s*"(.*?)"', response)
            if m:
                val = m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
                if val:
                    partial[field] = val
            else:
                # fallback：直接取到下一个换行（处理截断无引号的情况）
                m2 = re.search(f'"{field}"\\s*:\\s*"([^"\\n]+)', response)
                if m2:
                    partial[field] = m2.group(1).replace('\\"', '"').strip()
        if partial.get('decision'):
            partial.setdefault('confidence', '低')
            partial.setdefault('rationale', partial.get('rationale', '部分解析'))
            partial.setdefault('action_plan', '部分数据')
            partial.setdefault('risk_note', '部分数据')
            return partial

        return None


class ResearcherTeam:
    """
    研究员团队 - 多轮辩论协调器
    借鉴 TradingAgents 的辩论流程
    """

    def __init__(self, memory_agent=None, max_rounds=2):
        self.memory_agent = memory_agent
        self.max_rounds = max_rounds
        self.bull = BullResearcher(memory_agent)
        self.bear = BearResearcher(memory_agent)
        self.manager = ResearchManager(memory_agent)

    def debate(self, news_data, option_data, tech_data):
        """
        执行多轮辩论
        返回: (bull_args, bear_args, final_decision)
        """
        # 1. 构造市场情况描述
        situation = self._build_situation(news_data, option_data, tech_data)

        # 2. 获取相似历史记忆
        past_memories = []
        if self.memory_agent:
            memories = self.memory_agent.retrieve_similar(
                situation,
                symbol=tech_data.get('symbol', 'TSLA'),
                n_matches=3
            )
            past_memories = memories

        # 3. 多轮辩论
        state = {
            'situation': situation,
            'history': '',
            'bull_history': '',
            'bear_history': '',
            'current_bull_argument': '',
            'current_bear_argument': '',
            'past_memories': past_memories,
            'option_data': option_data,
            'tech_data': tech_data,
            'count': 0,
        }

        print("  ⚔️ 多轮辩论开始...", flush=True)

        for round_i in range(self.max_rounds):
            print(f"  🟢 第 {round_i+1} 轮 - 看多分析...", flush=True)
            new_state, bull_resp = self.bull.analyze(state)
            state.update(new_state)  # 合并，不是替换
            print(f"     多头: {bull_resp[:80]}...", flush=True)

            print(f"  🔴 第 {round_i+1} 轮 - 看空分析...", flush=True)
            new_state, bear_resp = self.bear.analyze(state)
            state.update(new_state)  # 合并，不是替换
            print(f"     空头: {bear_resp[:80]}...", flush=True)

        # 4. 裁判综合决策
        print("  ⚖️ 研究经理综合决策...", flush=True)
        decision_data, full_response = self.manager.decide(state)

        print(f"  决策: {decision_data.get('decision','N/A')} | 信心: {decision_data.get('confidence','N/A')}", flush=True)

        return {
            'bull_args': state['bull_history'],
            'bear_args': state['bear_history'],
            'debate_history': state['history'],
            'decision': decision_data,
            'decision_raw': full_response,
            'past_memories': past_memories,
            'debate_rounds': self.max_rounds
        }

    def _build_situation(self, news_data, option_data, tech_data):
        """构建市场情况描述"""
        strategies = option_data.get('strategies', [])
        best = strategies[0] if strategies else {}

        topics = news_data.get('topics', {})
        topic_str = ' / '.join([f"{k}:{v}" for k, v in topics.items()]) if topics else '无特定主题'
        _price = option_data.get('price') or 0
        _sup = tech_data.get('support') or 0
        _res = tech_data.get('resistance') or 0
        _iv = option_data.get('iv') or 0
        _vix = option_data.get('vix') or 0

        return f"""股票: {tech_data.get('symbol','TSLA')} | 现价: $  {_price:.2f}
技术面: 趋势={tech_data.get('trend','N/A')} | RSI={tech_data.get('rsi','N/A')} | 支撑=${_sup:.2f} | 阻力=${_res:.2f}
波动率: IV={_iv:.1f}% | VIX={_vix:.2f} ({option_data.get('vix_signal','N/A')})
舆情: {option_data.get('sentiment','N/A')} (评分: {option_data.get('sentiment_score','N/A')})
热点: {topic_str}
推荐策略: {best.get('type','N/A')} | 评分: {best.get('composite_score','N/A')} | RR: {best.get('rr_ratio','N/A')} | 仓位: {best.get('position','N/A')}%
到期: {best.get('actual_expiry_date','N/A')} | Theta: {best.get('theta','N/A')}/天
情绪标签: {option_data.get('sentiment_label','N/A')}"""
