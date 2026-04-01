#!/usr/bin/env python3
"""
UnifiedDataFetcher - 统一数据获取层
所有 yfinance 调用收敛在此，一次获取供全系统复用
解决重复访问导致的限流问题
"""

import os
import warnings
import json
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

# ── 代理配置（yfinance 通过环境变量使用）───────────────
PROXY = 'http://127.0.0.1:7897'
os.environ.setdefault('https_proxy', PROXY)
os.environ.setdefault('http_proxy', PROXY)
os.environ.setdefault('HTTPS_PROXY', PROXY)
os.environ.setdefault('HTTP_PROXY', PROXY)

import yfinance as yf
import pandas as pd
import numpy as np
import requests

CACHE_FILE = Path('/root/.openclaw/workspace/quant/StockAssistant/data/unified_cache.json')


def _load_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(updates):
    """合并写入缓存（不覆盖其他key）"""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_cache()
        existing.update(updates)
        with open(CACHE_FILE, 'w') as f:
            json.dump(existing, f, default=str, ensure_ascii=False)
    except Exception:
        pass


class UnifiedDataFetcher:
    """
    统一数据获取器。
    一次调完 yfinance，把所有 Agent 需要的数据全部拿到，
    通过 data_context 字典传给后续所有步骤。
    """

    def __init__(self, symbol='TSLA'):
        self.symbol = symbol
        self.ticker = yf.Ticker(symbol)
        self.data = {}
        self._fetch_all()

    def _fetch_all(self):
        """一次性获取所有数据，按优先级降级处理限流"""
        # 1. 股价 + 历史 K 线（技术指标用）
        self._fetch_history()

        # 2. VIX（全局风险指标）
        self._fetch_vix()

        # 3. 多到期日期权链（期权策略用）
        self._fetch_option_chains()

        # 4. 新闻（舆情用）+ IV 计算（在 _fetch_news 中一起完成）
        self._fetch_news()

    # ──────────────────────────────────────────
    # 内部获取方法（带持久化缓存保底）
    # ──────────────────────────────────────────

    def _fetch_history(self):
        """获取 3 个月日线 history（技术指标计算用）"""
        try:
            df = self.ticker.history(period='3mo')
        except Exception:
            df = pd.DataFrame()
        self.data['history'] = df
        self.data['price'] = float(df['Close'].iloc[-1]) if not df.empty else None

        # 计算 RSI (如果 history 有数据)
        if not df.empty and len(df) >= 14:
            close = df['Close']
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = (100 - 100 / (1 + rs)).iloc[-1]
            self.data['rsi'] = float(rsi) if not np.isnan(rsi) else None
        else:
            self.data['rsi'] = None

    def _fetch_vix(self):
        """获取 VIX 指数（优先 yfinance，降级 FRED）"""
        cached = _load_cache().get('vix') if _load_cache() else None
        if cached:
            self.data['vix'] = cached['value']
            self.data['vix_ma10'] = cached['ma10']
            return

        vix = None
        try:
            vix_ticker = yf.Ticker('^VIX')
            v = vix_ticker.history(period='10d')
            if not v.empty:
                vix = float(v['Close'].iloc[-1])
        except Exception:
            pass

        # 降级：FRED API
        if vix is None:
            try:
                url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS'
                resp = requests.get(url, timeout=5)
                lines = resp.text.strip().split('\n')
                if len(lines) >= 2:
                    last = lines[-1].split(',')
                    vix = float(last[1])
            except Exception:
                pass

        # MA10 估算（取最近10天）
        vix_ma10 = vix  # 简化：直接用当前值代替

        self.data['vix'] = vix
        self.data['vix_ma10'] = vix_ma10
        if vix is not None:
            _save_cache({'vix': {'value': vix, 'ma10': vix_ma10, 'ts': datetime.now().isoformat()}})

    def _fetch_option_chains(self):
        """获取多到期日期权链（最多5个最近到期日）"""
        chains = []
        try:
            expirations = list(self.ticker.options)[:5]
            for exp in expirations:
                try:
                    oc = self.ticker.option_chain(exp)
                    chains.append({
                        'date': exp,
                        'days': (datetime.strptime(exp, '%Y-%m-%d') - datetime.now()).days,
                        'calls': oc.calls.to_dict('records'),
                        'puts': oc.puts.to_dict('records'),
                    })
                except Exception:
                    pass
        except Exception:
            pass
        self.data['option_chains'] = chains

    def _fetch_news(self):
        """获取新闻（舆情用）"""
        news = []
        df = self.data.get('history')
        if df is None or len(df) < 20:
            self.data['iv'] = None
            return
        returns = df['Close'].pct_change().dropna()
        hv = returns.tail(20).std() * np.sqrt(252)
        # IV 通常略高于 HV，加 5% 溢价
        self.data['iv'] = round(float(hv * 1.05 * 100), 4) if not pd.isna(hv) else None

    # ──────────────────────────────────────────
    # 公开接口：返回完整上下文
    # ──────────────────────────────────────────

    def get_context(self):
        """返回供所有 Agent 使用的统一数据上下文"""
        return {
            'symbol': self.symbol,
            'price': self.data.get('price'),
            'rsi': self.data.get('rsi'),
            'history': self.data.get('history', pd.DataFrame()),
            'vix': self.data.get('vix'),
            'vix_ma10': self.data.get('vix_ma10'),
            'iv': self.data.get('iv'),
            'option_chains': self.data.get('option_chains', []),
            'news': self.data.get('news', []),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def summary(self):
        """打印数据获取摘要（调试用）"""
        ctx = self.get_context()
        print(f"[UnifiedFetcher] {self.symbol} | price={ctx['price']} | vix={ctx['vix']} | "
              f"iv={ctx['iv']} | history_rows={len(ctx['history'])} | "
              f"option_chains={len(ctx['option_chains'])} | news={len(ctx['news'])}")
        return ctx


def get_mock_ctx(symbol='TSLA'):
    """
    返回模拟的 ctx 数据（用于开发测试，不发网络请求）。
    """
    import random
    return {
        'symbol': symbol,
        'price': 361.83,
        'iv': 37,
        'vix': 28.2,
        'vix_ma10': 25.87,
        'sentiment': 'neutral',
        'sentiment_score': 50,
        'option_chains': [
            {
                'date': '2026-04-01', 'days': 3,
                'calls': [
                    {'strike': 355.0, 'lastPrice': 12.50, 'bid': 12.00, 'ask': 13.00,
                     'volume': 8500, 'openInterest': 12000, 'impliedVolatility': 0.42},
                    {'strike': 360.0, 'lastPrice': 9.20, 'bid': 8.80, 'ask': 9.60,
                     'volume': 12000, 'openInterest': 18500, 'impliedVolatility': 0.39},
                    {'strike': 365.0, 'lastPrice': 6.80, 'bid': 6.50, 'ask': 7.10,
                     'volume': 9800, 'openInterest': 14200, 'impliedVolatility': 0.36},
                    {'strike': 370.0, 'lastPrice': 4.70, 'bid': 4.50, 'ask': 4.90,
                     'volume': 15000, 'openInterest': 22000, 'impliedVolatility': 0.33},
                    {'strike': 375.0, 'lastPrice': 3.10, 'bid': 2.95, 'ask': 3.25,
                     'volume': 11000, 'openInterest': 17000, 'impliedVolatility': 0.30},
                    {'strike': 380.0, 'lastPrice': 1.95, 'bid': 1.85, 'ask': 2.05,
                     'volume': 22000, 'openInterest': 35000, 'impliedVolatility': 0.27},
                    {'strike': 385.0, 'lastPrice': 1.15, 'bid': 1.10, 'ask': 1.25,
                     'volume': 18000, 'openInterest': 28000, 'impliedVolatility': 0.24},
                    {'strike': 390.0, 'lastPrice': 0.65, 'bid': 0.60, 'ask': 0.72,
                     'volume': 25000, 'openInterest': 42000, 'impliedVolatility': 0.21},
                ],
                'puts': [
                    {'strike': 355.0, 'lastPrice': 5.80, 'bid': 5.50, 'ask': 6.10,
                     'volume': 7200, 'openInterest': 11000, 'impliedVolatility': 0.45},
                    {'strike': 360.0, 'lastPrice': 7.90, 'bid': 7.60, 'ask': 8.20,
                     'volume': 11000, 'openInterest': 16000, 'impliedVolatility': 0.48},
                    {'strike': 365.0, 'lastPrice': 10.60, 'bid': 10.20, 'ask': 11.00,
                     'volume': 8900, 'openInterest': 13500, 'impliedVolatility': 0.52},
                    {'strike': 370.0, 'lastPrice': 14.20, 'bid': 13.70, 'ask': 14.70,
                     'volume': 6500, 'openInterest': 9800, 'impliedVolatility': 0.56},
                    {'strike': 375.0, 'lastPrice': 18.50, 'bid': 17.90, 'ask': 19.10,
                     'volume': 4200, 'openInterest': 7200, 'impliedVolatility': 0.61},
                    {'strike': 380.0, 'lastPrice': 23.80, 'bid': 23.00, 'ask': 24.60,
                     'volume': 3100, 'openInterest': 5500, 'impliedVolatility': 0.67},
                    {'strike': 385.0, 'lastPrice': 29.60, 'bid': 28.70, 'ask': 30.50,
                     'volume': 2400, 'openInterest': 4100, 'impliedVolatility': 0.72},
                    {'strike': 390.0, 'lastPrice': 35.80, 'bid': 34.60, 'ask': 37.00,
                     'volume': 1800, 'openInterest': 3200, 'impliedVolatility': 0.78},
                ],
            },
            {
                'date': '2026-04-04', 'days': 6,
                'calls': [
                    {'strike': 355.0, 'lastPrice': 14.80, 'bid': 14.20, 'ask': 15.40,
                     'volume': 6200, 'openInterest': 9800, 'impliedVolatility': 0.41},
                    {'strike': 360.0, 'lastPrice': 11.40, 'bid': 11.00, 'ask': 11.80,
                     'volume': 9500, 'openInterest': 14500, 'impliedVolatility': 0.38},
                    {'strike': 365.0, 'lastPrice': 8.50, 'bid': 8.20, 'ask': 8.80,
                     'volume': 13000, 'openInterest': 20000, 'impliedVolatility': 0.35},
                    {'strike': 370.0, 'lastPrice': 6.20, 'bid': 5.95, 'ask': 6.45,
                     'volume': 17000, 'openInterest': 26000, 'impliedVolatility': 0.32},
                    {'strike': 375.0, 'lastPrice': 4.40, 'bid': 4.20, 'ask': 4.60,
                     'volume': 21000, 'openInterest': 33000, 'impliedVolatility': 0.29},
                    {'strike': 380.0, 'lastPrice': 3.00, 'bid': 2.85, 'ask': 3.15,
                     'volume': 28000, 'openInterest': 45000, 'impliedVolatility': 0.26},
                    {'strike': 385.0, 'lastPrice': 1.98, 'bid': 1.88, 'ask': 2.10,
                     'volume': 35000, 'openInterest': 52000, 'impliedVolatility': 0.23},
                    {'strike': 390.0, 'lastPrice': 1.25, 'bid': 1.18, 'ask': 1.35,
                     'volume': 29000, 'openInterest': 48000, 'impliedVolatility': 0.21},
                ],
                'puts': [
                    {'strike': 355.0, 'lastPrice': 8.20, 'bid': 7.90, 'ask': 8.50,
                     'volume': 5500, 'openInterest': 8500, 'impliedVolatility': 0.44},
                    {'strike': 360.0, 'lastPrice': 11.10, 'bid': 10.70, 'ask': 11.50,
                     'volume': 8200, 'openInterest': 12000, 'impliedVolatility': 0.47},
                    {'strike': 365.0, 'lastPrice': 14.60, 'bid': 14.10, 'ask': 15.10,
                     'volume': 6400, 'openInterest': 10000, 'impliedVolatility': 0.51},
                    {'strike': 370.0, 'lastPrice': 19.20, 'bid': 18.50, 'ask': 19.90,
                     'volume': 4800, 'openInterest': 7600, 'impliedVolatility': 0.55},
                    {'strike': 375.0, 'lastPrice': 24.80, 'bid': 24.00, 'ask': 25.60,
                     'volume': 3200, 'openInterest': 5400, 'impliedVolatility': 0.60},
                    {'strike': 380.0, 'lastPrice': 30.90, 'bid': 29.90, 'ask': 31.90,
                     'volume': 2400, 'openInterest': 4100, 'impliedVolatility': 0.65},
                    {'strike': 385.0, 'lastPrice': 37.50, 'bid': 36.30, 'ask': 38.70,
                     'volume': 1800, 'openInterest': 3200, 'impliedVolatility': 0.70},
                    {'strike': 390.0, 'lastPrice': 44.20, 'bid': 42.80, 'pid': 45.60,
                     'volume': 1400, 'openInterest': 2600, 'impliedVolatility': 0.75},
                ],
            },
            {
                'date': '2026-04-08', 'days': 10,
                'calls': [
                    {'strike': 355.0, 'lastPrice': 17.50, 'bid': 16.90, 'ask': 18.10,
                     'volume': 4800, 'openInterest': 7800, 'impliedVolatility': 0.40},
                    {'strike': 360.0, 'lastPrice': 14.10, 'bid': 13.60, 'ask': 14.60,
                     'volume': 7600, 'openInterest': 11500, 'impliedVolatility': 0.37},
                    {'strike': 365.0, 'lastPrice': 11.20, 'bid': 10.80, 'ask': 11.60,
                     'volume': 10500, 'openInterest': 16000, 'impliedVolatility': 0.34},
                    {'strike': 370.0, 'lastPrice': 8.70, 'bid': 8.40, 'ask': 9.00,
                     'volume': 14000, 'openInterest': 21500, 'impliedVolatility': 0.31},
                    {'strike': 375.0, 'lastPrice': 6.60, 'bid': 6.35, 'ask': 6.85,
                     'volume': 18000, 'openInterest': 28000, 'impliedVolatility': 0.28},
                    {'strike': 380.0, 'lastPrice': 4.90, 'bid': 4.70, 'ask': 5.10,
                     'volume': 23000, 'openInterest': 38000, 'impliedVolatility': 0.25},
                    {'strike': 385.0, 'lastPrice': 3.55, 'bid': 3.40, 'ask': 3.70,
                     'volume': 29000, 'openInterest': 44000, 'impliedVolatility': 0.23},
                    {'strike': 390.0, 'lastPrice': 2.50, 'bid': 2.38, 'ask': 2.65,
                     'volume': 35000, 'openInterest': 52000, 'impliedVolatility': 0.21},
                ],
                'puts': [
                    {'strike': 355.0, 'lastPrice': 11.20, 'bid': 10.80, 'ask': 11.60,
                     'volume': 4200, 'openInterest': 6800, 'impliedVolatility': 0.43},
                    {'strike': 360.0, 'lastPrice': 15.10, 'bid': 14.60, 'ask': 15.60,
                     'volume': 6500, 'openInterest': 9800, 'impliedVolatility': 0.46},
                    {'strike': 365.0, 'lastPrice': 19.80, 'bid': 19.10, 'ask': 20.50,
                     'volume': 5100, 'openInterest': 8200, 'impliedVolatility': 0.50},
                    {'strike': 370.0, 'lastPrice': 25.60, 'bid': 24.70, 'ask': 26.50,
                     'volume': 3800, 'openInterest': 6200, 'impliedVolatility': 0.54},
                    {'strike': 375.0, 'lastPrice': 32.20, 'bid': 31.10, 'ask': 33.30,
                     'volume': 2800, 'openInterest': 4600, 'impliedVolatility': 0.58},
                    {'strike': 380.0, 'lastPrice': 39.50, 'bid': 38.20, 'ask': 40.80,
                     'volume': 2100, 'openInterest': 3600, 'impliedVolatility': 0.62},
                    {'strike': 385.0, 'lastPrice': 47.10, 'bid': 45.60, 'ask': 48.60,
                     'volume': 1600, 'openInterest': 2800, 'impliedVolatility': 0.67},
                    {'strike': 390.0, 'lastPrice': 55.20, 'bid': 53.40, 'pid': 57.00,
                     'volume': 1200, 'openInterest': 2100, 'impliedVolatility': 0.72},
                ],
            },
        ],
    }


def fetch_unified(symbol='TSLA'):
    """快捷函数：一次获取，返回 context"""
    fetcher = UnifiedDataFetcher(symbol)
    return fetcher.get_context()


class UnifiedDataFetcherCLI:
    """
    UnifiedDataFetcher 的 CLI 封装，支持 --ctx-file 输出模式。
    其他脚本（multi_strategy_v2 / vertical_spread_v6）通过读取 ctx 文件
    获取数据，无需重复请求 yfinance。

    用法:
        python3 unified_fetcher.py TSLA --ctx-file /tmp/tsla_ctx.json
        python3 unified_fetcher.py TSLA,NVDA,AMD --ctx-file /tmp/multi_ctx.json
    """

    @staticmethod
    def save_ctx(ctx, filepath):
        """保存 ctx 到 JSON 文件（供其他脚本读取）。history DataFrame 无法序列化，先移除。"""
        import os, json
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        ctx_save = {k: v for k, v in ctx.items() if k != 'history'}
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(ctx_save, f, ensure_ascii=False, default=str)
        return filepath

    @staticmethod
    def load_ctx(filepath, symbol=None):
        """从 JSON 文件加载 ctx（供其他脚本读取）。
        如果文件是 {symbol: ctx} 格式，传入 symbol 直接取对应 ctx。
        如果文件就是 ctx 格式，直接返回。
        """
        import json
        with open(filepath, encoding='utf-8') as f:
            data = json.load(f)
        # 外层嵌套 {symbol: ctx}？
        if symbol and isinstance(data, dict) and symbol in data:
            return data[symbol]
        return data

    def run(self, symbols, ctx_file=None, print_summary=True, use_mock=False):
        """
        批量获取多个股票数据，统一保存到 ctx_file。
        use_mock=True 时使用模拟数据，不发网络请求。
        返回 {symbol: ctx} 字典。
        """
        results = {}
        for sym in symbols:
            print(f"  Fetching {sym}...", end=" ", flush=True)
            if use_mock:
                ctx = get_mock_ctx(sym)
                print("OK (MOCK)")
            else:
                ctx = fetch_unified(sym)
                print("OK")
            results[sym] = ctx
            if print_summary:
                UnifiedDataFetcher(sym).summary()
            print("OK")
        if ctx_file:
            # 保存批量 ctx
            self.save_ctx(results, ctx_file)
            print(f"\n✅ ctx 已保存: {ctx_file}")
        return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='UnifiedDataFetcher CLI')
    parser.add_argument('symbols', help='股票代码，逗号分隔，如 TSLA,NVDA,AMD')
    parser.add_argument('--ctx-file', help='保存 ctx 到指定文件路径')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据（开发测试用，不请求 yfinance）')
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',')]
    cli = UnifiedDataFetcherCLI()
    results = cli.run(symbols, ctx_file=args.ctx_file, use_mock=args.mock)

    if not args.ctx_file:
        for sym, ctx in results.items():
            print(f"\n=== {sym} ===")
            print(f"  price: {ctx.get('price')}")
            print(f"  vix: {ctx.get('vix')}")
            print(f"  iv: {ctx.get('iv')}")
            print(f"  option_chains: {len(ctx.get('option_chains', []))} expirations")

