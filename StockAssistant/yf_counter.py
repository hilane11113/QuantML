#!/usr/bin/env python3
"""
yfinance 请求计数器 & 限流监控
挂在 curl_cffi Session.get/post 层拦截所有 HTTP 请求，记录到 SQLite 供看板使用

使用方法:
    from yf_counter import YFCounter
    counter = YFCounter()
    counter.install()           # 注入拦截器
    counter.uninstall()        # 卸载（恢复原状）

    # 查询接口
    counter.stats()            # 当前窗口统计
    counter.requests_by_type() # 按 endpoint 类型分
    counter.rate_limit_events()# 429 事件记录
"""

import sqlite3
import os
import time
import threading
import re
from datetime import datetime
from collections import defaultdict


# ============================================================
# 指标存储（SQLite）
# ============================================================

METRIC_DB = os.path.join(os.path.dirname(__file__), "yf_metrics.db")


def get_db():
    conn = sqlite3.connect(METRIC_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS yf_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,
            endpoint    TEXT    NOT NULL,
            ticker      TEXT,
            status      INTEGER,
            is_429      INTEGER DEFAULT 0,
            error       TEXT,
            duration_ms INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS yf_rate_limits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,
            endpoint    TEXT,
            ticker      TEXT,
            retry_after INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_yf_ts ON yf_requests(ts)")
    return conn


# ============================================================
# URL → endpoint 分类
# ============================================================

def classify_url(url: str) -> str:
    if "/v8/finance/chart/" in url:
        return "history"
    elif "/v7/finance/quote" in url:
        return "info"
    elif "/v1/finance/options" in url:
        return "options"
    elif "/ws/fundamentals-timeseries" in url:
        return "fundamentals"
    elif "getcrumb" in url or "/v1/test/getcrumb" in url:
        return "crumb"
    elif "^VIX" in url:
        return "vix"
    elif "SPY" in url:
        return "market"
    elif "/ws/insights" in url:
        return "insights"
    elif "/v8/finance/earnings" in url:
        return "earnings"
    return "other"


def extract_ticker(url: str) -> str:
    for pat in [r'/chart/([A-Z0-9^.-]+)', r'symbol=([A-Z0-9^.-]+)', r'/options/([A-Z0-9^.-]+)']:
        m = re.search(pat, url)
        if m:
            return m.group(1).upper()
    return "UNKNOWN"


# ============================================================
# YFCounter: 拦截 + 统计 + 查询
# ============================================================

class YFCounter:
    """
    yfinance 请求拦截器
    挂在 curl_cffi.requests.Session.get/post 层，记录所有 HTTP 流量
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._installed = False
        self._orig_get  = None
        self._orig_post = None
        self._counter_lock = threading.Lock()
        self._last_cleanup = time.time()
        self._conn = get_db()

    # --------------------------------------------------------
    # 安装 / 卸载
    # --------------------------------------------------------

    def install(self):
        """注入拦截器到 curl_cffi Session 层"""
        if self._installed:
            return

        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            print("[YFCounter] 无法导入 curl_cffi.requests")
            return

        session_cls = curl_requests.Session
        self._orig_get  = session_cls.get
        self._orig_post = session_cls.post

        def counted_get(s_self, url, **kw):
            return self._wrap(s_self, url, 'GET', **kw)

        def counted_post(s_self, url, **kw):
            return self._wrap(s_self, url, 'POST', **kw)

        session_cls.get  = counted_get
        session_cls.post = counted_post

        self._installed = True
        print("[YFCounter] 已安装 ✓")

    def uninstall(self):
        """卸载拦截器，恢复原状"""
        if not self._installed:
            return

        try:
            from curl_cffi import requests as curl_requests
            session_cls = curl_requests.Session
            if self._orig_get:
                session_cls.get = self._orig_get
            if self._orig_post:
                session_cls.post = self._orig_post
        except ImportError:
            pass

        self._installed = False
        print("[YFCounter] 已卸载")

    # --------------------------------------------------------
    # 拦截器实现
    # --------------------------------------------------------

    def _wrap(self, s_self, url, method='GET', **kw):
        start = time.time()
        endpoint = classify_url(url)
        ticker   = extract_ticker(url)
        status   = None
        is_429   = 0
        error_msg = None

        orig = self._orig_get if method == 'GET' else self._orig_post

        try:
            resp = orig(s_self, url, **kw)
            status = getattr(resp, 'status_code', None)
            is_429 = 1 if status == 429 else 0

            if is_429:
                retry_after = resp.headers.get('Retry-After')
                self._record_429(endpoint, ticker, retry_after)

            return resp
        except Exception as e:
            error_msg = str(e)[:200]
            is_429 = 1 if ('rate' in error_msg.lower() or '429' in error_msg) else 0
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            self._record(endpoint, ticker, status, is_429, error_msg, duration_ms)

    # --------------------------------------------------------
    # 记录
    # --------------------------------------------------------

    def _record(self, endpoint, ticker, status, is_429, error_msg, duration_ms):
        ts = time.time()
        try:
            self._conn.execute(
                "INSERT INTO yf_requests (ts, endpoint, ticker, status, is_429, error, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, endpoint, ticker, status, is_429, error_msg, duration_ms)
            )
            self._conn.commit()
        except Exception:
            pass

        self._maybe_cleanup()

    def _record_429(self, endpoint, ticker, retry_after):
        ts = time.time()
        try:
            self._conn.execute(
                "INSERT INTO yf_rate_limits (ts, endpoint, ticker, retry_after) VALUES (?, ?, ?, ?)",
                (ts, endpoint, ticker, int(retry_after) if retry_after else None)
            )
            self._conn.commit()
        except Exception:
            pass

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        # 保留最近 24 小时数据
        cutoff = now - 86400
        try:
            self._conn.execute("DELETE FROM yf_requests WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM yf_rate_limits WHERE ts < ?", (cutoff,))
            self._conn.commit()
        except Exception:
            pass

    # --------------------------------------------------------
    # 查询接口
    # --------------------------------------------------------

    def stats(self, window_seconds=60) -> dict:
        cutoff = time.time() - window_seconds
        cur = self._conn.execute(
            """SELECT endpoint, COUNT(*), SUM(is_429), AVG(duration_ms)
               FROM yf_requests WHERE ts > ? GROUP BY endpoint""",
            (cutoff,)
        )
        rows = cur.fetchall()

        total_req = sum(r[1] for r in rows)
        total_429 = sum(r[2] or 0 for r in rows)
        by_ep = {
            ep: {"requests": cnt, "429": s429 or 0, "avg_ms": round(avg or 0, 1)}
            for ep, cnt, s429, avg in rows
        }

        return {
            "window_seconds": window_seconds,
            "total_requests": total_req,
            "total_429": total_429,
            "rate_per_min": round(total_req / (window_seconds / 60), 2),
            "by_endpoint": by_ep,
        }

    def requests_by_type(self, window_seconds=300) -> dict:
        cutoff = time.time() - window_seconds
        cur = self._conn.execute(
            """SELECT endpoint, COUNT(*), SUM(is_429)
               FROM yf_requests WHERE ts > ? GROUP BY endpoint""",
            (cutoff,)
        )
        return {ep: {"requests": cnt, "429": s429 or 0} for ep, cnt, s429 in cur.fetchall()}

    def rate_limit_events(self, limit=10) -> list:
        cur = self._conn.execute(
            """SELECT ts, endpoint, ticker, retry_after
               FROM yf_rate_limits ORDER BY ts DESC LIMIT ?""",
            (limit,)
        )
        return [
            {
                "ts": ts,
                "datetime": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                "endpoint": ep,
                "ticker": tk,
                "retry_after": ra,
            }
            for ts, ep, tk, ra in cur.fetchall()
        ]

    def recent_requests(self, limit=20) -> list:
        cur = self._conn.execute(
            """SELECT ts, endpoint, ticker, status, is_429, duration_ms
               FROM yf_requests ORDER BY ts DESC LIMIT ?""",
            (limit,)
        )
        return [
            {
                "ts": ts,
                "datetime": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                "endpoint": ep,
                "ticker": tk,
                "status": st,
                "is_429": i429,
                "duration_ms": dm,
            }
            for ts, ep, tk, st, i429, dm in cur.fetchall()
        ]

    def summary(self) -> dict:
        return {
            "last_1m":  self.stats(60),
            "last_5m":  self.stats(300),
            "last_1m_by_type": self.requests_by_type(60),
            "last_5m_by_type": self.requests_by_type(300),
            "recent_429": self.rate_limit_events(5),
            "installed": self._installed,
        }


# ============================================================
# 便捷实例
# ============================================================

_counter_instance = None
_instance_lock = threading.Lock()


def get_counter() -> YFCounter:
    global _counter_instance
    if _counter_instance is None:
        with _instance_lock:
            if _counter_instance is None:
                _counter_instance = YFCounter()
    return _counter_instance


# ============================================================
# 命令行测试
# ============================================================

if __name__ == "__main__":
    import sys
    counter = get_counter()

    if len(sys.argv) > 1 and sys.argv[1] == "install":
        counter.install()
        print("注入成功，运行 yfinance 代码后查 stats() 即可")

    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(counter.summary())

    else:
        print("用法: python yf_counter.py [install|stats]")
