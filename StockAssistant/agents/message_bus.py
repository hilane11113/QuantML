#!/usr/bin/env python3
"""
MessageBus - 多代理协作消息总线
实现代理间通信协调
"""

import asyncio
from typing import Dict, List, Callable, Any
from datetime import datetime
from collections import defaultdict

class MessageBus:
    """消息总线 - 代理间通信"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance
    
    def _init(self):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.message_history: List[Dict] = []
        self.agent_stats: Dict[str, Dict] = defaultdict(lambda: {
            "published": 0,
            "received": 0,
            "last_active": None
        })
    
    def subscribe(self, topic: str, callback: Callable):
        """订阅主题
        
        Args:
            topic: 主题名称
            callback: 回调函数
        """
        self.subscribers[topic].append(callback)
        print(f"  📝 订阅主题: {topic}")
    
    def publish(self, topic: str, data: Any, agent: str = "system"):
        """发布消息
        
        Args:
            topic: 主题名称
            data: 消息数据
            agent: 发布者
        """
        message = {
            "topic": topic,
            "data": data,
            "agent": agent,
            "timestamp": datetime.now().strftime('%H:%M:%S')
        }
        
        self.message_history.append(message)
        self.agent_stats[agent]["published"] += 1
        self.agent_stats[agent]["last_active"] = message["timestamp"]
        
        # 调用所有订阅者
        for callback in self.subscribers.get(topic, []):
            try:
                callback(message)
                self.agent_stats[agent]["received"] += 1
            except Exception as e:
                print(f"  ⚠️ 回调错误: {e}")
        
        # 保持历史简洁
        if len(self.message_history) > 100:
            self.message_history = self.message_history[-50:]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "topics": list(self.subscribers.keys()),
            "agents": dict(self.agent_stats),
            "recent_messages": self.message_history[-5:]
        }
    
    def clear(self):
        """清空总线"""
        self.subscribers.clear()
        self.message_history.clear()
        self.agent_stats.clear()


class Coordinator:
    """多代理协调器"""
    
    def __init__(self, message_bus: MessageBus = None):
        self.bus = message_bus or MessageBus()
        self.workflows: Dict[str, List[Dict]] = {}
    
    def register_workflow(self, name: str, steps: List[Dict]):
        """
        注册工作流
        
        Args:
            name: 工作流名称
            steps: 步骤列表 [{"agent": "tech", "action": "analyze", "publish": "tech_done", "subscribe": "start_analysis"}]
        """
        self.workflows[name] = steps
        print(f"  ✅ 注册工作流: {name} ({len(steps)}步)")
    
    def execute_workflow(self, name: str, initial_data: Any = None) -> Dict:
        """
        执行工作流
        
        Args:
            name: 工作流名称
            initial_data: 初始数据
        
        Returns:
            dict: 工作流执行结果
        """
        if name not in self.workflows:
            return {"error": f"未找到工作流: {name}"}
        
        print(f"\n🚀 执行工作流: {name}")
        print("=" * 50)
        
        results = {}
        current_data = initial_data
        
        for i, step in enumerate(self.workflows[name], 1):
            print(f"\n📍 步骤 {i}/{len(self.workflows[name])}: {step.get('name', step['agent'])}")
            
            agent_name = step['agent']
            action = step.get('action', 'run')
            
            # 获取agent
            agent = self._get_agent(agent_name)
            if agent is None:
                print(f"  ❌ Agent不存在: {agent_name}")
                continue
            
            # 执行action
            try:
                if callable(getattr(agent, action, None)):
                    result = getattr(agent, action)(current_data if current_data else step.get('data'))
                else:
                    result = agent.run(current_data if current_data else step.get('data'))
                
                results[agent_name] = result
                
                # 发布消息
                if 'publish' in step:
                    self.bus.publish(step['publish'], result, agent_name)
                    print(f"  📤 已发布: {step['publish']}")
                
                # 更新当前数据
                if result:
                    current_data = result
                    
            except Exception as e:
                print(f"  ❌ 执行错误: {e}")
                results[agent_name] = {"error": str(e)}
        
        print("\n" + "=" * 50)
        print(f"✅ 工作流完成: {name}")
        
        return results
    
    def _get_agent(self, name: str):
        """获取agent实例"""
        agents = {
            'a_stock': lambda: AStockAgentLite(),
            'fundamental': lambda: FundamentalAgentLite(),
            'technical': lambda: TechnicalAgentLite(),
            'option': lambda: OptionAgentLite(),
            'portfolio': lambda: PortfolioAgentLite(),
        }
        factory = agents.get(name)
        return factory() if factory else None


# 轻量版 Agent（用于协调）
class AStockAgentLite:
    def run(self, symbol):
        from agents import AShareAgent
        agent = AShareAgent()
        return agent.run(symbol)

class FundamentalAgentLite:
    def run(self, symbol):
        from agents import FundamentalAgent
        agent = FundamentalAgent()
        return agent.run(symbol)

class TechnicalAgentLite:
    def run(self, symbol):
        from agents import TechnicalAgent
        agent = TechnicalAgent()
        return agent.run(symbol)

class OptionAgentLite:
    def run(self, symbol):
        from agents import OptionAgent
        agent = OptionAgent()
        return agent.run(symbol)

class PortfolioAgentLite:
    def run(self, data):
        from agents import PortfolioAgent
        agent = PortfolioAgent()
        return {"positions": agent.get_positions(), "performance": agent.get_performance()}


# 全局实例
_bus = None

def get_message_bus() -> MessageBus:
    """获取消息总线单例"""
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus

def get_coordinator() -> Coordinator:
    """获取协调器"""
    return Coordinator(get_message_bus())


# 预设工作流
def register_stock_workflows(coordinator: Coordinator):
    """注册股票分析工作流"""
    
    # A股完整分析工作流
    coordinator.register_workflow("a_stock_full", [
        {"agent": "a_stock", "name": "技术分析", "publish": "tech_done"},
        {"agent": "fundamental", "name": "基本面分析", "subscribe": "tech_done", "publish": "fundamental_done"},
    ])
    
    # 美股完整分析工作流
    coordinator.register_workflow("us_stock_full", [
        {"agent": "technical", "name": "技术分析", "publish": "tech_done"},
        {"agent": "option", "name": "期权分析", "subscribe": "tech_done", "publish": "option_done"},
    ])
    
    # 投资组合分析工作流
    coordinator.register_workflow("portfolio_analysis", [
        {"agent": "portfolio", "name": "持仓分析", "publish": "portfolio_done"},
    ])
