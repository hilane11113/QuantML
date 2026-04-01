#!/usr/bin/env python3
"""
MarketDataStore - 统一市场数据层
解决重复调用 yfinance 导致限流的问题

数据获取顺序（一次获取，多 Agent 共用）：
1. 进程内缓存（_cache）— 零网络请求
2. 新浪财经直连 → 实时股价
3. FRED 直连 → VIX 指数
4. yfinance 直连 → 技术指标/历史（限流时降级）
5. 磁盘持久化缓存 → 最后保底

关键设计：
- 所有数据一次获取，缓存在单例中供所有 Agent 共用
- 不设置任何代理环境变量，让各数据源自行处理直连
- yfinance 限流时自动降级到新浪 + FRED
- 成功获取后自动写入磁盘（下次限流时可从本地恢复）
"""

import os
import sqlite3
import json
import warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import numpy as np
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ==================== 关键修复 ====================
# 清除所有代理环境变量，避免干扰直连
for _var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(_var, None)

# ─────────────────────────────────────────────────
#  持久化缓存（yfinance 限流时的最后保底）
# ─────────────────────────────────────────────────
CACHE_FILE = Path('/root/.openclaw/workspace/quant/StockAssistant/data/market_cache.json')


def _load_persistent_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_persistent_cache(data):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            'timestamp': data.get('date', datetime.now().isoformat()),
            'symbol': data.get('symbol'),
            'price': data.get('price'),
            'vix': data.get('vix'),
            'vix_signal': data.get('vix_signal'),
            'iv': data.get('iv'),
            'hv': data.get('hv'),
            'rsi': data.get('rsi'),
            'macd': data.get('macd'),
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(entry, f, ensure_ascii=False)
    except Exception:
        pass


# ─────────────────────────────────────────────────
#  数据源 1: 新浪财经 (直连，不要代理)
# ─────────────────────────────────────────────────
def fetch_sina_realtime(symbol):
    """
    新浪财经美股实时行情
    返回: {'price', 'change', 'change_pct', 'date', 'open', 'high', 'low', 'volume'} 或 None
    """
    sina_code = f'gb_{symbol.lower()}'
    try:
        url = f'https://hq.sinajs.cn/list={sina_code}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('gbk').strip()
        if '="";' in data or 'var hq_str' not in data:
            return None
        content = data.split('"')[1]
        parts = content.split(',')
        if len(parts) < 10:
            return None
        return {
            'price': float(parts[1]),
            'change': float(parts[2]),
            'date': parts[3],
            'open': float(parts[4]),
            'high': float(parts[5]),
            'low': float(parts[6]),
            'volume': int(parts[7]) if parts[7].isdigit() else 0,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────
#  数据源 2: FRED (直连，不要代理)
# ─────────────────────────────────────────────────
def fetch_fred_vix():
    """
    FRED VIXCLS 数据（完全免费，无 API key）
    返回: {'date', 'vix'} 或 None
    """
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS'
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            lines = resp.read().decode().strip().split('\n')
        if len(lines) < 2:
            return None
        last = lines[-1].strip()
        date_str, vix_str = last.split(',')
        return {'date': date_str, 'vix': float(vix_str)}
    except Exception:
        return None


# ─────────────────────────────────────────────────
#  数据源 3: yfinance (走 mihomo 代理，避免直连限流)
# ─────────────────────────────────────────────────
def fetch_yfinance_history(symbol, period='30d'):
    """获取历史数据，走 mihomo 代理，返回 DataFrame 或 None"""
    # 保存原代理环境变量（如果有的话）
    orig_http = os.environ.pop('HTTP_PROXY', None)
    orig_https = os.environ.pop('HTTPS_PROXY', None)
    orig_http_lower = os.environ.pop('http_proxy', None)
    orig_https_lower = os.environ.pop('https_proxy', None)
    try:
        # 通过 mihomo 代理访问 yfinance（直连可能被限流）
        os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'
        os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
        df = yf.download(symbol, period=period, interval='1d', timeout=10, progress=False)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    finally:
        # 恢复原代理环境变量
        if orig_http:      os.environ['HTTP_PROXY'] = orig_http
        elif 'HTTP_PROXY' in os.environ: os.environ.pop('HTTP_PROXY')
        if orig_https:     os.environ['HTTPS_PROXY'] = orig_https
        elif 'HTTPS_PROXY' in os.environ: os.environ.pop('HTTPS_PROXY')
        if orig_http_lower: os.environ['http_proxy'] = orig_http_lower
        elif 'http_proxy' in os.environ: os.environ.pop('http_proxy')
        if orig_https_lower: os.environ['https_proxy'] = orig_https_lower
        elif 'https_proxy' in os.environ: os.environ.pop('https_proxy')
    return None


# ─────────────────────────────────────────────────
#  主 Store 类
# ─────────────────────────────────────────────────
class MarketDataStore:
    """
    统一市场数据获取单例

    使用方式：
        from market_data import get_market_data
        data = get_market_data('TSLA')   # 首次调用获取+缓存
        # 后续所有 Agent 直接用 data['price'], data['vix'] 等
    """

    _instance = None
    _cache = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def fetch(self, symbol='TSLA', fetch_technicals=True):
        """
        获取市场数据（带缓存，同一进程只调一次 yfinance）

        Returns:
            dict: {
                'symbol', 'price', 'vix', 'vix_signal',
                'iv', 'hv', 'rsi', 'macd',
                'history' (DataFrame),
                'success', 'error', 'source', 'date'
            }
        """
        # ── 1. 进程内缓存（零网络请求）──
        if symbol in self._cache:
            cached = self._cache[symbol].copy()
            cached['source'] = 'cache'
            return cached

        result = {
            'symbol': symbol,
            'price': None, 'vix': None, 'vix_signal': 'UNKNOWN',
            'iv': None, 'hv': None, 'rsi': None, 'macd': None,
            'history': None,
            'success': False, 'error': None,
            'source': None, 'date': datetime.now().strftime('%Y-%m-%d')
        }

        # ── 2. 新浪财经获取实时价格（优先，不走 yfinance）──
        sina_data = fetch_sina_realtime(symbol)
        if sina_data:
            result['price'] = sina_data['price']
            result['source'] = 'sina'
            result['date'] = sina_data['date']

        # ── 3. yfinance 批量获取股价+VIX+历史数据（走代理，一次请求）
        #    优先用 yfinance 的 VIX（最新），FRED 当 fallback
        _orig_http = os.environ.pop('HTTP_PROXY', None)
        _orig_https = os.environ.pop('HTTPS_PROXY', None)
        _orig_http_l = os.environ.pop('http_proxy', None)
        _orig_https_l = os.environ.pop('https_proxy', None)
        try:
            os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'
            os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
            bundle = yf.download(f'{symbol} ^VIX', period='1mo', timeout=15, progress=False)
            if bundle is not None and not bundle.empty:
                closes = bundle['Close']
                if isinstance(closes, pd.DataFrame):
                    sym_close = closes[symbol] if symbol in closes.columns else closes.iloc[:, 0]
                    vix_close = closes['^VIX'] if '^VIX' in closes.columns else None
                else:
                    sym_close = closes
                    vix_close = None
                # 从 yfinance 提取 VIX（优先，不覆盖已有的实时价格）
                if vix_close is not None and len(vix_close.dropna()) > 0:
                    vix_val = float(vix_close.dropna().iloc[-1])
                    result['vix'] = vix_val
                    if vix_val > 30:       result['vix_signal'] = 'RED'
                    elif vix_val < 15:      result['vix_signal'] = 'GREEN'
                    elif vix_val < 25:      result['vix_signal'] = 'YELLOW'
                    else:                   result['vix_signal'] = 'RED'
                # 获取历史数据（用于技术指标）
                if fetch_technicals and symbol in bundle.columns.get_level_values(1):
                    hist_df = bundle.xs(symbol, level=1, axis=1).copy()
                    hist_df.columns = list(hist_df.columns.get_level_values(0))
                    result['history'] = hist_df
        except Exception:
            pass
        finally:
            if _orig_http:      os.environ['HTTP_PROXY'] = _orig_http
            elif 'HTTP_PROXY' in os.environ: os.environ.pop('HTTP_PROXY')
            if _orig_https:    os.environ['HTTPS_PROXY'] = _orig_https
            elif 'HTTPS_PROXY' in os.environ: os.environ.pop('HTTPS_PROXY')
            if _orig_http_l:   os.environ['http_proxy'] = _orig_http_l
            elif 'http_proxy' in os.environ: os.environ.pop('http_proxy')
            if _orig_https_l:  os.environ['https_proxy'] = _orig_https_l
            elif 'https_proxy' in os.environ: os.environ.pop('https_proxy')

        # ── 4. FRED VIX 当 fallback（yfinance 失败时补充 VIX）──
        if not result.get('vix'):
            fred_data = fetch_fred_vix()
            if fred_data:
                result['vix'] = fred_data['vix']
                vix = fred_data['vix']
                if vix > 30:       result['vix_signal'] = 'RED'
                elif vix < 15:     result['vix_signal'] = 'GREEN'
                elif vix < 25:     result['vix_signal'] = 'YELLOW'
                else:              result['vix_signal'] = 'RED'

        # ── 5. 计算技术指标（基于 yfinance 历史数据）──
                closes = df['Close']
                if isinstance(closes, pd.DataFrame):
                    closes = closes.iloc[:, 0]
                if closes is None or len(closes) < 15:
                    raise ValueError(f"历史数据不足({len(closes) if closes is not None else 0}行)")
                try:
                    delta = closes.diff()
                    gain = delta.where(delta > 0, 0).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / (loss + 1e-10)
                    result['rsi'] = float((100 - 100 / (1 + rs)).iloc[-1])

                    ema12 = closes.ewm(span=12).mean()
                    ema26 = closes.ewm(span=26).mean()
                    macd_line = ema12 - ema26
                    macd_signal = macd_line.ewm(span=9).mean()
                    result['macd'] = float((macd_line - macd_signal).iloc[-1])

                    returns = np.log(closes / closes.shift(1)).dropna()
                    result['hv'] = float(returns.tail(20).std() * np.sqrt(252))
                    if result['hv']:
                        result['iv'] = result['hv'] * 1.3
                except Exception:
                    pass

        # ── 5. 判断成功 ──
        if result['price'] or result['vix']:
            result['success'] = True
            if not result['source']:
                result['source'] = 'yfinance_fallback'

        # ── 6. 完全无数据 → sqlite fallback ──
        if not result['price'] and not result['vix']:
            self._fill_from_db(result, symbol)

        # ── 7. 写入磁盘缓存（成功时）──
        if result['success']:
            _save_persistent_cache(result)

        self._cache[symbol] = result.copy()
        return result

    def _fill_from_db(self, result, symbol):
        """从 stock_data.db 读取缓存数据"""
        db_path = '/root/.openclaw/workspace/quant/TSLA期权策略/stock_data.db'
        if not os.path.exists(db_path):
            return
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT date, close FROM stock_daily WHERE symbol=? ORDER BY date DESC LIMIT 1",
                (symbol,)
            ).fetchone()
            if row:
                result['price'] = float(row[1])
                result['source'] = 'db'
            vix_row = conn.execute(
                "SELECT date, close FROM vix_daily ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if vix_row:
                result['vix'] = float(vix_row[1])
                result['vix_signal'] = 'UNKNOWN'
            conn.close()
        except Exception:
            pass

    def get_cached(self, symbol='TSLA'):
        return self._cache.get(symbol)

    def clear_cache(self):
        self._cache.clear()


# ─────────────────────────────────────────────────
#  统一访问入口
# ─────────────────────────────────────────────────
_store = None


def get_market_data(symbol='TSLA', fetch_technicals=True):
    """
    统一入口：获取市场数据（同进程内只 fetch 一次）

    数据获取顺序：
    1. 进程内缓存（完全零网络）
    2. 新浪 + FRED + yfinance
    3. 磁盘持久化缓存（yfinance 限流时最后保底）
    """
    global _store
    if _store is None:
        _store = MarketDataStore()

    result = _store.fetch(symbol, fetch_technicals=fetch_technicals)

    # 全部失败时，从磁盘缓存读取最后保底
    if not result.get('success') or (not result.get('price') and not result.get('vix')):
        disk = _load_persistent_cache()
        if disk and disk.get('symbol') == symbol:
            disk['source'] = 'disk_cache'
            disk['success'] = True
            disk['history'] = None
            _store._cache[symbol] = disk
            return disk

    return result


def clear_market_cache():
    global _store
    if _store:
        _store.clear_cache()
    _store = None


def get_cached_market_data(symbol='TSLA'):
    """直接从磁盘缓存读取（不触发任何网络请求）"""
    return _load_persistent_cache()


# ─────────────────────────────────────────────────
#  快速测试
# ─────────────────────────────────────────────────
if __name__ == '__main__':
    print("=== MarketDataStore 统一数据层测试 ===\n")
    data = get_market_data('TSLA')
    print(f"股票:    {data['symbol']}")
    print(f"价格:    ${data['price']}")
    print(f"VIX:     {data['vix']} ({data['vix_signal']})")
    print(f"RSI:     {data['rsi']:.1f}" if data['rsi'] else "RSI:     N/A")
    print(f"HV:      {data['hv']:.1%}" if data['hv'] else "HV:      N/A")
    print(f"IV(估):  {data['iv']:.1%}" if data['iv'] else "IV(估):  N/A")
    print(f"数据源:  {data['source']}")
    print(f"成功:    {data['success']}")
    if data.get('error'):
        print(f"错误:    {data['error']}")

    print("\n--- 第二次调用（走缓存）---")
    data2 = get_market_data('TSLA')
    print(f"来源: {data2['source']} ✓")
