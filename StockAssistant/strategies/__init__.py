#!/usr/bin/env python3
"""
策略目录 __init__.py

strategies/ 目录用于独立策略模块管理。
引用 agents/ 中稳定的 Agent 实现。
"""

from agents.technical_agent import TechnicalAgent
from agents.social_agent import SocialAgent
from agents.option_agent import OptionAgent
from agents.risk_agent import RiskAgent
from agents.researcher import BullResearcher, BearResearcher, ResearchManager

__all__ = [
    'TechnicalAgent',
    'SocialAgent',
    'OptionAgent',
    'RiskAgent',
    'BullResearcher',
    'BearResearcher',
    'ResearchManager',
]
