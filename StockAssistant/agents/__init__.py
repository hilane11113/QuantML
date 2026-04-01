#!/usr/bin/env python3
"""
StockAssistant - 代理模块
"""

from .news_agent import NewsAgent
from .option_agent import OptionAgent
from .technical_agent import TechnicalAgent
from .social_agent import SocialAgent
from .researcher import ResearcherTeam
from .risk_agent import RiskAgent
from .memory_agent import MemoryAgent
from .stock_agent import StockAgent
from .a_stock_agent import AShareAgent, detect_market, format_a_stock_report
from .fundamental_agent import FundamentalAgent, format_fundamental_report, score_fundamental
from .portfolio_agent import PortfolioAgent, format_portfolio_report
from .llm_agent import LLMChatAgent, intent_recognition, chat_with_llm
from .message_bus import (
    MessageBus, Coordinator, 
    get_message_bus, get_coordinator,
    register_stock_workflows
)
from .async_message_bus import (
    AsyncMessageBus, AsyncCoordinator,
    run_async_workflow, register_stock_workflows_async
)

__all__ = [
    'NewsAgent', 
    'OptionAgent', 
    'TechnicalAgent',
    'SocialAgent',
    'ResearcherTeam', 
    'RiskAgent',
    'MemoryAgent',
    'StockAgent',
    'AShareAgent',
    'detect_market',
    'format_a_stock_report',
    'FundamentalAgent',
    'format_fundamental_report',
    'score_fundamental',
    'PortfolioAgent',
    'format_portfolio_report',
    'LLMChatAgent',
    'intent_recognition',
    'chat_with_llm',
    'MessageBus',
    'Coordinator',
    'get_message_bus',
    'get_coordinator',
    'register_stock_workflows',
    'AsyncMessageBus',
    'AsyncCoordinator',
    'run_async_workflow',
    'register_stock_workflows_async'
]
