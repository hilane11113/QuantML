#!/usr/bin/env python3
"""
消息总线 (messaging.py)

提供 Agent 间的发布/订阅消息传递机制。
"""

from collections import defaultdict
from datetime import datetime


class MessageBus:
    """简单的内存消息总线"""

    def __init__(self):
        self._subscribers = defaultdict(list)
        self._history = []

    def subscribe(self, topic, callback):
        """订阅主题"""
        self._subscribers[topic].append(callback)

    def unsubscribe(self, topic, callback):
        """取消订阅"""
        if topic in self._subscribers:
            self._subscribers[topic].remove(callback)

    def publish(self, topic, data):
        """发布消息"""
        msg = {
            'topic': topic,
            'data': data,
            'timestamp': datetime.now().isoformat(),
        }
        self._history.append(msg)
        for callback in self._subscribers.get(topic, []):
            try:
                callback(msg)
            except Exception as e:
                print(f"[MessageBus] Callback error on topic={topic}: {e}")

    def history(self, topic=None):
        """获取消息历史"""
        if topic:
            return [m for m in self._history if m['topic'] == topic]
        return list(self._history)


# 全局单例
_bus = MessageBus()


def get_bus():
    return _bus
