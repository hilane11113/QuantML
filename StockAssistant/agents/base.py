#!/usr/bin/env python3
"""
Agent 基类 (base.py)

所有 Agent 的基类，定义统一接口。
"""


class AgentBase:
    """
    所有 Agent 的抽象基类。
    子类需要实现 run() 或 analyze() 方法。
    """

    def __init__(self, name=None):
        self.name = name or self.__class__.__name__

    def run(self, *args, **kwargs):
        """执行 Agent 主逻辑，子类应覆盖此方法"""
        raise NotImplementedError(f"{self.name} must implement run()")

    def analyze(self, *args, **kwargs):
        """analyze 别名"""
        return self.run(*args, **kwargs)

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name}>"
