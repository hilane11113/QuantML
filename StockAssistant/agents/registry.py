#!/usr/bin/env python3
"""
Agent 注册表 (registry.py)

提供 Agent 的注册与发现机制。
"""

from typing import Dict, Type, Callable, Any


class AgentRegistry:
    """
    Agent 注册表，维护 agent_name -> agent_class 的映射。
    """

    def __init__(self):
        self._registry: Dict[str, Type] = {}

    def register(self, name: str, agent_class: Type):
        """注册一个 Agent 类"""
        self._registry[name] = agent_class

    def get(self, name: str) -> Type:
        """根据名称获取 Agent 类"""
        return self._registry.get(name)

    def list_agents(self):
        """列出所有已注册的 Agent"""
        return list(self._registry.keys())

    def create(self, name: str, *args, **kwargs) -> Any:
        """根据名称创建 Agent 实例"""
        cls = self.get(name)
        if cls is None:
            raise ValueError(f"Agent '{name}' not found in registry")
        return cls(*args, **kwargs)


# 全局注册表实例
_global_registry = AgentRegistry()


def register_agent(name: str):
    """装饰器：注册 Agent"""
    def decorator(cls):
        _global_registry.register(name, cls)
        return cls
    return decorator


def get_agent(name: str) -> Type:
    """获取 Agent 类"""
    return _global_registry.get(name)


def list_agents():
    """列出所有 Agent"""
    return _global_registry.list_agents()


def create_agent(name: str, *args, **kwargs):
    """创建 Agent 实例"""
    return _global_registry.create(name, *args, **kwargs)
