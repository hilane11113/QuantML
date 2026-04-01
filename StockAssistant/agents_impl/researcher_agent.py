#!/usr/bin/env python3
"""
多空辩论 Agent (researcher_agent.py)

引用自 agents/researcher.py。
"""

from agents.researcher import BullResearcher, BearResearcher, ResearchManager


class ResearcherAgent:
    """多空辩论 Agent（薄壳）"""

    def __init__(self, max_rounds=2):
        self.bull = BullResearcher()
        self.bear = BearResearcher()
        self.manager = ResearchManager()
        self.max_rounds = max_rounds

    def debate(self, symbol, tech, option, sentiment, memory=None):
        """执行多轮辩论，返回辩论结果。"""
        situation = (
            f"{symbol} ${tech.get('price')} "
            f"趋势:{tech.get('trend')} RSI={tech.get('rsi')} "
            f"VIX={option.get('vix')} ({option.get('vix_signal')}) IV={option.get('iv')}%"
        )
        state = {
            'situation': situation,
            'bull_history': '',
            'bear_history': '',
            'current_bull_argument': '',
            'current_bear_argument': '',
            'past_memories': memory or [],
            'option_data': {'strategies': option.get('strategies', [])},
            'tech_data': {'rsi': tech.get('rsi'), 'trend': tech.get('trend')},
        }
        for _ in range(self.max_rounds):
            s1, bull_r = self.bull.analyze(state)
            state.update(s1)
            state['bull_history'] = (state.get('bull_history', '') + '\n' + bull_r).strip()
            s2, bear_r = self.bear.analyze(state)
            state.update(s2)
            state['bear_history'] = (state.get('bear_history', '') + '\n' + bear_r).strip()

        history = f"多头:\n{state.get('bull_history','')}\n空头:\n{state.get('bear_history','')}"
        state_mgr = {
            'situation': situation,
            'history': history,
            'bull_history': state.get('bull_history', ''),
            'bear_history': state.get('bear_history', ''),
            'past_memories': state.get('past_memories', []),
            'option_data': {'strategies': option.get('strategies', [])},
            'tech_data': {'rsi': tech.get('rsi'), 'trend': tech.get('trend')},
        }
        decision, raw = self.manager.decide(state_mgr)
        return {
            'bull_history': state.get('bull_history', ''),
            'bear_history': state.get('bear_history', ''),
            'final_decision': decision,
            'raw_response': raw,
        }
