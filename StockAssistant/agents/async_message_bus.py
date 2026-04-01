#!/usr/bin/env python3
"""
异步消息总线 - 多代理协作
使用 asyncio 实现并行任务执行
"""

import asyncio
from typing import Dict, List, Callable, Any, Optional
from datetime import datetime
from collections import defaultdict
import threading

class AsyncMessageBus:
    """异步消息总线"""
    
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
        self._lock = threading.Lock()
    
    def subscribe(self, topic: str, callback: Callable):
        """订阅主题"""
        with self._lock:
            self.subscribers[topic].append(callback)
        print(f"  📝 订阅主题: {topic}")
    
    def publish(self, topic: str, data: Any, agent: str = "system"):
        """同步发布消息"""
        message = {
            "topic": topic,
            "data": data,
            "agent": agent,
            "timestamp": datetime.now().strftime('%H:%M:%S')
        }
        
        with self._lock:
            self.message_history.append(message)
            self.agent_stats[agent]["published"] += 1
        
        # 调用订阅者
        with self._lock:
            callbacks = list(self.subscribers.get(topic, []))
        
        for callback in callbacks:
            try:
                callback(message)
                with self._lock:
                    self.agent_stats[agent]["received"] += 1
            except Exception as e:
                print(f"  ⚠️ 回调错误: {e}")
        
        # 保持历史简洁
        with self._lock:
            if len(self.message_history) > 100:
                self.message_history = self.message_history[-50:]
    
    async def publish_async(self, topic: str, data: Any, agent: str = "system"):
        """异步发布消息"""
        message = {
            "topic": topic,
            "data": data,
            "agent": agent,
            "timestamp": datetime.now().strftime('%H:%M:%S')
        }
        
        with self._lock:
            self.message_history.append(message)
            self.agent_stats[agent]["published"] += 1
        
        # 并行调用订阅者
        with self._lock:
            callbacks = list(self.subscribers.get(topic, []))
        
        tasks = []
        for callback in callbacks:
            if asyncio.iscoroutinefunction(callback):
                tasks.append(asyncio.create_task(self._safe_callback(callback, message, agent)))
            else:
                tasks.append(asyncio.create_task(self._safe_callback_sync(callback, message, agent)))
        
        if tasks:
            await asyncio.gather(*tasks)
        
        with self._lock:
            if len(self.message_history) > 100:
                self.message_history = self.message_history[-50:]
    
    async def _safe_callback(self, callback: Callable, message: Dict, agent: str):
        """安全执行异步回调"""
        try:
            await callback(message)
            with self._lock:
                self.agent_stats[agent]["received"] += 1
        except Exception as e:
            print(f"  ⚠️ 异步回调错误: {e}")
    
    async def _safe_callback_sync(self, callback: Callable, message: Dict, agent: str):
        """安全执行同步回调"""
        try:
            callback(message)
            with self._lock:
                self.agent_stats[agent]["received"] += 1
        except Exception as e:
            print(f"  ⚠️ 回调错误: {e}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return {
                "topics": list(self.subscribers.keys()),
                "agents": dict(self.agent_stats),
                "recent_messages": self.message_history[-5:]
            }


class AsyncCoordinator:
    """异步协调器 - 支持并行任务"""
    
    def __init__(self, message_bus: AsyncMessageBus = None):
        self.bus = message_bus or AsyncMessageBus()
        self.workflows: Dict[str, List[Dict]] = {}
    
    def register_workflow(self, name: str, steps: List[Dict]):
        """注册工作流"""
        self.workflows[name] = steps
        print(f"  ✅ 注册工作流: {name} ({len(steps)}步)")
    
    async def execute_workflow_async(self, name: str, initial_data: Any = None) -> Dict:
        """异步执行工作流"""
        if name not in self.workflows:
            return {"error": f"未找到工作流: {name}"}
        
        print(f"\n🚀 异步执行工作流: {name}")
        print("=" * 50)
        
        results = {}
        current_data = initial_data
        
        # 分析哪些步骤可以并行
        parallel_groups = self._group_parallel_steps(self.workflows[name])
        
        for i, group in enumerate(parallel_groups, 1):
            print(f"\n📍 阶段 {i}/{len(parallel_groups)}: ", end="")
            
            if len(group) == 1:
                # 单步骤
                step = group[0]
                print(f"{step.get('name', step['agent'])}")
                
                result = await self._execute_step(step, current_data)
                results[step['agent']] = result
                
                if 'publish' in step:
                    await self.bus.publish_async(step['publish'], result, step['agent'])
                
                if result:
                    current_data = result
            else:
                # 并行步骤
                agent_names = [s.get('name', s['agent']) for s in group]
                print(f"并行: {', '.join(agent_names)}")
                
                # 并行执行
                tasks = [self._execute_step(step, current_data) for step in group]
                group_results = await asyncio.gather(*tasks)
                
                for step, result in zip(group, group_results):
                    results[step['agent']] = result
                    
                    if 'publish' in step:
                        await self.bus.publish_async(step['publish'], result, step['agent'])
                
                # 使用最后一个结果
                if group_results and group_results[-1]:
                    current_data = group_results[-1]
        
        print("\n" + "=" * 50)
        print(f"✅ 工作流完成: {name}")
        
        return results
    
    def _group_parallel_steps(self, steps: List[Dict]) -> List[List[Dict]]:
        """将步骤分组为串行和并行"""
        # 简单策略：根据 publish/subscribe 关系分组
        # 如果一个步骤订阅了另一个步骤的发布，则必须串行
        groups = []
        current_group = []
        
        for step in steps:
            # 检查是否有依赖
            if 'subscribe' in step:
                # 有依赖，必须在前一个完成后执行
                if current_group:
                    groups.append(current_group)
                    current_group = []
                current_group.append(step)
            else:
                current_group.append(step)
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    async def _execute_step(self, step: Dict, data: Any) -> Any:
        """执行单个步骤"""
        agent_name = step['agent']
        agent = self._get_agent(agent_name)
        
        if agent is None:
            print(f"  ❌ Agent不存在: {agent_name}")
            return None
        
        try:
            action = step.get('action', 'run')
            action_func = getattr(agent, action, None)
            
            if action_func is None:
                action_func = getattr(agent, 'run', None)
                if action_func is None:
                    return None
            
            if asyncio.iscoroutinefunction(action_func):
                return await action_func(data)
            else:
                # 同步函数，在线程池中执行
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: action_func(data))
        except Exception as e:
            print(f"  ❌ 执行错误: {e}")
            return {"error": str(e)}
    
    def _get_agent(self, name: str):
        """获取agent实例"""
        from agents import (
            AShareAgent, FundamentalAgent, TechnicalAgent,
            OptionAgent, PortfolioAgent
        )
        
        agents = {
            'a_stock': AShareAgent,
            'fundamental': FundamentalAgent,
            'technical': TechnicalAgent,
            'option': OptionAgent,
            'portfolio': PortfolioAgent,
        }
        
        agent_class = agents.get(name)
        return agent_class() if agent_class else None


# 便捷函数
def run_async_workflow(workflow_name: str, symbol: str = None):
    """运行异步工作流"""
    async def _run():
        bus = AsyncMessageBus()
        coordinator = AsyncCoordinator(bus)
        
        # 注册工作流
        from agents import register_stock_workflows_async
        register_stock_workflows_async(coordinator)
        
        if workflow_name == "a_stock_full":
            # A股完整分析 - 并行获取技术和基本面
            print(f"\n🚀 启动异步工作流: {workflow_name}")
            print("=" * 50)
            
            # 并行获取技术和基本面
            print("\n📍 阶段1: 并行数据获取")
            
            bus.subscribe("tech_done", lambda m: None)
            bus.subscribe("fundamental_done", lambda m: None)
            
            # 并行执行
            tasks = []
            if symbol:
                from agents import AShareAgent, FundamentalAgent
                
                async def get_tech():
                    agent = AShareAgent()
                    result = agent.run(symbol)
                    await bus.publish_async("tech_done", result, "a_stock")
                    return result
                
                async def get_fundamental():
                    agent = FundamentalAgent()
                    result = agent.run(symbol)
                    await bus.publish_async("fundamental_done", result, "fundamental")
                    return result
                
                tasks = [get_tech(), get_fundamental()]
            
            results = await asyncio.gather(*tasks) if tasks else []
            
            print(f"\n✅ 并行获取完成")
            print(f"   技术分析: {'成功' if results[0] else '失败'}")
            print(f"   基本面分析: {'成功' if results[1] else '失败'}")
            
            return results
        
        elif workflow_name == "us_stock_full":
            print(f"\n🚀 启动异步工作流: {workflow_name}")
            return await coordinator.execute_workflow_async("us_stock_full", symbol)
        
        elif workflow_name == "portfolio_analysis":
            print(f"\n🚀 启动异步工作流: {workflow_name}")
            return await coordinator.execute_workflow_async("portfolio_analysis")
        
        return None
    
    return asyncio.run(_run())


def register_stock_workflows_async(coordinator: AsyncCoordinator):
    """注册异步工作流"""
    
    # A股完整分析
    coordinator.register_workflow("a_stock_full", [
        {"agent": "a_stock", "name": "技术分析", "publish": "tech_done"},
        {"agent": "fundamental", "name": "基本面分析", "subscribe": "tech_done", "publish": "fundamental_done"},
    ])
    
    # 美股完整分析
    coordinator.register_workflow("us_stock_full", [
        {"agent": "technical", "name": "技术分析", "publish": "tech_done"},
        {"agent": "option", "name": "期权分析", "subscribe": "tech_done", "publish": "option_done"},
    ])
    
    # 持仓分析
    coordinator.register_workflow("portfolio_analysis", [
        {"agent": "portfolio", "name": "持仓分析", "publish": "portfolio_done"},
    ])
