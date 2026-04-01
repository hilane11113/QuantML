#!/usr/bin/env python3
"""
风控 Agent (risk_agent.py)

职责：调用 strategies/risk_strategy.py 进行风险评估。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import AgentBase
from strategies.risk_strategy import calculate_risk_level


class RiskAgent(AgentBase):
    """风控 Agent"""

    def __init__(self):
        super().__init__(Name="RiskAgent")

    def evaluate_with_context(self, symbol, ctx, decision, tech, option):
        """
        基于 ctx 数据和决策结果执行风险评估。

        参数:
            symbol: 股票代码
            ctx: 统一数据上下文
            decision: ResearcherTeam 的决策
            tech: TechAgent 结果
            option: OptionAgent 结果

        返回:
            dict: 风险评估结果
        """
        # 基础数据
        price = ctx.get('price') or option.get('price')
        vix = option.get('vix', 20)
        vix_signal = option.get('vix_signal', 'YELLOW')
        iv = option.get('iv', 35)
        rsi = tech.get('rsi')
        trend = tech.get('trend', '震荡')
        sentiment = option.get('sentiment', 'neutral')
        strategies = option.get('strategies', [])

        # 最佳策略
        best = strategies[0] if strategies else {}

        # 计算风险等级
        risk_info = calculate_risk_level(
            vix=vix,
            vix_signal=vix_signal,
            iv=iv,
            rsi=rsi,
            trend=trend,
            sentiment=sentiment,
            decision=decision.get('decision', '观望'),
            best_strategy=best,
        )

        return {
            'symbol': symbol,
            'price': price,
            'risk_level': risk_info.get('risk_level', 'MEDIUM'),
            'position_size': risk_info.get('position_size', '20-30%'),
            'stop_loss': risk_info.get('stop_loss', '权利金30%'),
            'reason': risk_info.get('reason', ''),
            'decision_confidence': decision.get('confidence', '中'),
        }

    def run(self, symbol, ctx, decision, tech, option):
        return self.evaluate_with_context(symbol, ctx, decision, tech, option)
