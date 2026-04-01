#!/usr/bin/env python3
"""
期权多策略组合推荐 V2 (优化版)
参考 vertical_spread_v6.py 的评分体系

优化点:
- 真实计算 rr_ratio（风险回报比）
- 真实计算流动性（bid-ask spread + volume + OI）
- Theta 评分加入 Vega 风险调整
- 动态决策阈值
- IV 评分
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import os
import math
from scipy.stats import norm
import json
import sys
import warnings
import io
warnings.filterwarnings('ignore')

PROXY = 'http://127.0.0.1:7897'

# ==================== 日志配置 ====================
from pathlib import Path


LOG_DIR = Path('/root/.openclaw/workspace/quant/TSLA期权策略/logs')
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / 'multi_strategy_updates.log'

def log_update(action: str, details: dict, version: str = "Multi_V2"):
    """记录策略更新日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "version": version,
        "action": action,
        "details": details
    }
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    print(f"[LOG] {action}: {details}")

# ==================== 希腊字母库导入 ====================
try:
    from blackscholes import BlackScholesPut, BlackScholesCall
    GREEKS_AVAILABLE = True
    log_update("init", {"status": "blackscholes loaded", "greeks": "enabled"})
except ImportError:
    GREEKS_AVAILABLE = False
    log_update("init", {"status": "blackscholes not available"})

# ==================== Delta/Gamma 计算函数 ====================
def calculate_delta_gamma(price, strike, iv, days_to_expiry, option_type="put"):
    """计算 Delta 和 Gamma"""
    if days_to_expiry <= 0:
        return 0, 0
    
    T = days_to_expiry / 365
    if T <= 0:
        return 0, 0
    
    iv_decimal = iv / 100
    r = 0.05
    
    try:
        if option_type == "put":
            bs = BlackScholesPut(S=price, K=strike, T=T, r=r, sigma=iv_decimal)
            delta = bs.delta()
        else:
            bs = BlackScholesCall(S=price, K=strike, T=T, r=r, sigma=iv_decimal)
            delta = bs.delta()
        gamma = bs.gamma()
        return delta, gamma
    except:
        return calculate_delta_gamma_manual(price, strike, iv, days_to_expiry, option_type)

def calculate_delta_gamma_manual(price, strike, iv, days_to_expiry, option_type="put"):
    """手动计算 Delta 和 Gamma"""
    if days_to_expiry <= 0:
        return 0, 0
    
    T = days_to_expiry / 365
    if T <= 0:
        return 0, 0
    
    iv_decimal = iv / 100
    d1 = (math.log(price / strike) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
    
    gamma = (norm.pdf(d1)) / (price * iv_decimal * math.sqrt(T))
    
    if option_type == "put":
        delta = norm.cdf(d1) - 1
    else:
        delta = norm.cdf(d1)
    
    return delta, gamma

def calculate_delta_score(delta, target_delta_range=(-0.3, -0.2)):
    """Delta 中性评分"""
    if delta is None or delta == 0:
        return 0
    
    abs_delta = abs(delta)
    
    if 0.15 <= abs_delta <= 0.35:
        return 10
    elif 0.1 <= abs_delta < 0.15:
        return 7
    elif 0.35 < abs_delta <= 0.5:
        return 7
    elif abs_delta < 0.1:
        return 4
    else:
        return 3

def calculate_gamma_score(gamma, days_to_expiry):
    """Gamma 评分"""
    if gamma is None or gamma == 0:
        return 0
    
    if days_to_expiry < 7:
        if gamma > 0.05:
            return 3
        elif gamma > 0.03:
            return 5
        else:
            return 8
    elif days_to_expiry < 14:
        if gamma > 0.03:
            return 5
        elif gamma > 0.02:
            return 7
        else:
            return 9
    else:
        if gamma > 0.02:
            return 7
        else:
            return 10

def calculate_downside_score(price, short_strike, iv=30):
    """下跌空间评分 - 衡量不容易被击穿的程度（根据IV动态调整）
    
    下跌空间 = (Short Strike - 标的价格) / 标的价格 * 100
    下跌空间越大，越不容易被击穿
    
    阈值根据IV动态调整：
    - 低IV (<25%): 更保守，阈值更高 (>5% 满分)
    - 中等IV (25-40%): 标准阈值 (>4% 满分)
    - 高IV (>40%): 更激进，阈值更低 (>3% 满分)
    """
    if price <= 0 or short_strike <= 0:
        return 0
    
    downside_space = (short_strike - price) / price * 100
    
    # 根据IV动态调整阈值
    if iv < 25:
        threshold_10, threshold_7, threshold_4, threshold_2 = 5.0, 4.0, 3.0, 2.0
    elif iv <= 40:
        threshold_10, threshold_7, threshold_4, threshold_2 = 4.0, 3.0, 2.0, 1.0
    else:
        threshold_10, threshold_7, threshold_4, threshold_2 = 3.0, 2.5, 2.0, 1.0
    
    if downside_space > threshold_10:
        return 10
    elif downside_space > threshold_7:
        return 7
    elif downside_space > threshold_4:
        return 4
    elif downside_space > threshold_2:
        return 2
    else:
        return 1

log_update("greeks_functions", {"status": "added", "functions": ["delta_gamma", "delta_score", "gamma_score", "downside_score"]})

# ── yfinance 请求计数器 ─────────────────────────────────
try:
    sys.path.insert(0, '/root/.openclaw/workspace/quant/StockAssistant')
    from yf_counter import get_counter
    get_counter().install()
except Exception as e:
    pass  # 计数器安装失败不影响主流程

# STOCKS + CTX_FILE 解析（过滤掉 -- 开头的参数）
CTX_FILE = None
_args = []
for arg in sys.argv[1:]:
    if arg.startswith('--ctx-file='):
        CTX_FILE = arg.split('=', 1)[1]
    elif arg.startswith('--'):
        pass  # 忽略其他 flags
    else:
        _args.append(arg)
STOCKS = _args if _args else ['TSLA']
JSON_MODE = '--json' in sys.argv
MOCK_MODE = '--mock' in sys.argv
DB_PATH = '/root/.openclaw/workspace/quant/TSLA期权策略/multi_strategy_v2.db'

# --ctx-file 模式：从统一数据接口读取 ctx，不再发任何网络请求
_ctx_data = {}
if CTX_FILE:
    import json
    with open(CTX_FILE, encoding='utf-8') as f:
        raw = json.load(f)
    # 支持 {symbol: ctx} 嵌套格式，或直接是 ctx dict
    if isinstance(raw, dict):
        if 'price' in raw:
            # 直接是 ctx 格式（单股票）
            _ctx_data[raw.get('symbol', STOCKS[0])] = raw
        else:
            # {symbol: ctx} 嵌套格式
            for sym, ctx in raw.items():
                if isinstance(ctx, dict):
                    _ctx_data[ctx.get('symbol', sym)] = ctx
    print(f"[INFO] 从 ctx 文件加载: {list(_ctx_data.keys())}")

if MOCK_MODE:
    import sys
    sys.path.insert(0, '/root/.openclaw/workspace/quant/StockAssistant')
    from unified_fetcher import get_mock_ctx
    for sym in STOCKS:
        _ctx_data[sym] = get_mock_ctx(sym)
    print(f"[INFO] MOCK 模式：使用模拟数据（不请求 yfinance）")

# JSON 模式：重定向 stdout 吞掉所有 print，最后输出结构化 JSON
_stdout = sys.stdout
_json_buffer = io.StringIO()
if JSON_MODE:
    sys.stdout = _json_buffer

# ==================== VIX 信号 ====================
def get_vix():
    try:
        vix = yf.download("^VIX", period="30d", timeout=10)["Close"]
        if len(vix) < 10:
            return np.nan, np.nan, np.nan
        current = vix.iloc[-1].item()
        ma10 = vix.tail(10).mean().item()
        deviation = (current - ma10) / ma10 * 100
        return current, ma10, deviation
    except:
        return np.nan, np.nan, np.nan

def calculate_vix_signal(vix, vix_ma, deviation):
    """VIX信号计算（用于决策阈值调整）
    
    优化逻辑：同时考虑绝对水平和相对变化
    - VIX绝对值 > 30：直接RED（市场恐慌）
    - VIX绝对值 < 15：直接GREEN（极度平静）
    - VIX 15-30：综合偏离度判断，偏离度门槛收紧
    """
    if pd.isna(vix) or pd.isna(vix_ma):
        return "UNKNOWN", 50
    
    # 绝对水平优先判断
    if vix > 30:
        signal = "RED"
    elif vix < 15:
        signal = "GREEN"
    elif vix > 25:
        # VIX偏高（25+），严格收紧偏离度门槛
        if deviation < 3:
            signal = "GREEN"
        elif deviation < 10:
            signal = "YELLOW"
        else:
            signal = "RED"
    elif vix > 20:
        # VIX中偏高（20-25），收紧门槛
        if deviation < 5:
            signal = "GREEN"
        elif deviation < 15:
            signal = "YELLOW"
        else:
            signal = "RED"
    else:
        # VIX正常范围（15-20）
        if deviation < 20:
            signal = "GREEN"
        elif deviation < 50:
            signal = "YELLOW"
        else:
            signal = "RED"
    
    score = 50 + max(min((20 - deviation) * 2, 25), -25)
    if vix < 15:
        score += 20
    elif vix > 30:
        score -= 20
    elif vix > 20:
        score -= 10
    score = max(0, min(100, score))
    return signal, score

def get_dynamic_threshold(vix_signal, iv):
    """动态决策阈值（稳健型优化）"""
    base_threshold = 40  # 原35 → 提高到40
    
    if vix_signal == "GREEN":
        return base_threshold - 5  # 35
    elif vix_signal == "YELLOW":
        return base_threshold  # 40
    else:
        return base_threshold + 10  # 50

def get_stock_iv_from_hv(ticker, price):
    try:
        hist = ticker.history(period="30d", proxy=PROXY)
        if hist.empty:
            return np.nan, np.nan
        returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        hv_20 = returns.tail(20).std() * np.sqrt(252) * 100
        hv_20 = hv_20.item() if hasattr(hv_20, 'item') else hv_20
        estimated_iv = hv_20 * 1.15
        return estimated_iv, hv_20
    except:
        return np.nan, np.nan

def get_apewisdom_sentiment(symbol):
    """获取 apewisdom Reddit 舆情数据"""
    try:
        import requests
        url = f"https://apewisdom.io/api/v1.0/filter/all-stocks"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        for item in data.get('results', []):
            if item.get('ticker', '').upper() == symbol.upper():
                mentions = int(item.get('mentions', 0))
                upvotes = int(item.get('upvotes', 0))
                rank = int(item.get('rank', 999))
                rank_24h = int(item.get('rank_24h_ago', 999))
                mentions_24h = int(item.get('mentions_24h_ago', 0)) if item.get('mentions_24h_ago') else 0
                
                rank_change = rank_24h - rank
                sentiment_ratio = upvotes / mentions if mentions > 0 else 0
                
                score = {
                    'mentions': mentions,
                    'upvotes': upvotes,
                    'rank': rank,
                    'rank_change': rank_change,
                    'sentiment_ratio': sentiment_ratio
                }
                
                if sentiment_ratio > 10 and rank_change > 0:
                    sentiment = "bullish"
                elif sentiment_ratio < 2 or rank_change < -50:
                    sentiment = "bearish"
                else:
                    sentiment = "neutral"
                
                return sentiment, score
        
        return "neutral", {'mentions': 0, 'upvotes': 0, 'rank': 999, 'sentiment_ratio': 0}
    except Exception as e:
        return "neutral", {'error': str(e)}

def get_sentiment(symbol):
    """获取市场情绪（合并 Finnhub + apewisdom，返回连续评分 + 分类）"""
    import math
    
    # 1. Finnhub 新闻舆情 (0-1, 0.5=中性)
    finnhub_score = 0.5
    try:
        import requests
        from datetime import datetime, timedelta
        FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'
        PROXY = {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&token={FINNHUB_KEY}"
        response = requests.get(url, proxies=PROXY, timeout=15)
        if response.status_code == 200 and response.json():
            news = response.json()
            bull_kw = ['buy', 'upgrade', 'bull', 'growth', 'target', '上涨', '看好', '突破', '上调', '增持', '强劲', '超预期']
            bear_kw = ['sell', 'downgrade', 'bear', 'risk', 'warning', '下跌', '警告', '风险', '下调', '减持', '疲软', '不及预期']
            bull = sum(1 for n in news[:20] if any(k in n.get('headline', '').lower() for k in bull_kw))
            bear = sum(1 for n in news[:20] if any(k in n.get('headline', '').lower() for k in bear_kw))
            total = bull + bear
            if total > 0:
                finnhub_score = bull / total
    except:
        pass
    
    # 2. apewisdom Reddit 舆情
    ape_sentiment_raw, ape_data = get_apewisdom_sentiment(symbol)
    
    # Reddit sentiment_ratio: 2以下→0, 10以上→1
    ratio = ape_data.get('sentiment_ratio', 2)
    rank_change = ape_data.get('rank_change', 0)
    
    if ratio <= 2:
        ape_ratio_score = 0.0
    elif ratio >= 10:
        ape_ratio_score = 1.0
    else:
        ape_ratio_score = (ratio - 2) / 8
    
    if rank_change <= -50:
        ape_rank_score = 0.0
    elif rank_change >= 50:
        ape_rank_score = 1.0
    else:
        ape_rank_score = (rank_change + 50) / 100
    
    ape_score = ape_ratio_score * 0.7 + ape_rank_score * 0.3
    
    # 3. 合并评分 (apewisdom 60% + finnhub 40%)
    combined = ape_score * 0.6 + finnhub_score * 0.4  # 0-1, 0.5中性
    
    # 4. 转换为 0-100 评分
    sentiment_100 = combined * 100
    
    # 5. 分类标签
    if sentiment_100 >= 60:
        label = "偏多"
    elif sentiment_100 <= 40:
        label = "偏空"
    else:
        label = "中性"
    
    return sentiment_100, label, ape_data

def get_iv_score(iv):
    """IV评分：适中IV最好"""
    if iv < 20:
        return 10
    elif iv < 40:
        return 10
    elif iv < 60:
        return 7
    else:
        return 3

# ==================== 核心：真实评分指标 ====================

def calculate_real_rr_ratio(max_profit, max_loss):
    """计算真实风险回报比率"""
    if max_loss <= 0:
        return 0.5
    rr = max_profit / max_loss
    return max(0.2, min(3.0, rr))

def calculate_liquidity_score_from_options(options_df, strike, option_type):
    """根据真实期权数据计算流动性评分"""
    try:
        if option_type == "put":
            df = options_df.puts
        else:
            df = options_df.calls
        
        row = df[df['strike'] == strike]
        if row.empty:
            return 5
        
        row = row.iloc[0]
        bid = row.get('bid', 0)
        ask = row.get('ask', 0)
        vol = row.get('volume', 0)
        open_int = row.get('openInterest', 0)
        
        if bid <= 0 or ask <= 0 or ask - bid > bid * 0.5:
            return 3
        
        spread_pct = (ask - bid) / ((bid + ask) / 2) * 100 if (bid + ask) > 0 else 100
        spread_score = max(0, 10 - spread_pct * 2)
        
        vol_score = min(5, vol / 10000) if vol > 0 else 0
        oi_score = min(5, open_int / 50000) if open_int > 0 else 0
        
        return min(10, spread_score + vol_score + oi_score)
    except:
        return 5

def calculate_safety_distance(price, short_strike, long_strike, premium, strategy_type):
    """计算安全边际评分"""
    if strategy_type in ["Bull_Put", "Short_Put"]:
        width = short_strike - long_strike if long_strike else short_strike * 0.05
        if width <= 0 or premium <= 0:
            return 10
        margin_ratio = premium / width if width > 0 else 0
        score1 = min(10, margin_ratio * 50)
        
        distance_pct = (price - short_strike) / price * 100
        if distance_pct >= 10:
            score2 = 5
        elif distance_pct >= 7:
            score2 = 4
        elif distance_pct >= 5:
            score2 = 3
        elif distance_pct >= 3:
            score2 = 1
        else:
            score2 = 0
        
        return score1 + score2
        
    elif strategy_type == "Bull_Call":
        upside_space = (short_strike - price) / price * 100 if short_strike > price else 0
        if upside_space >= 15:
            score1 = 5
        elif upside_space >= 10:
            score1 = 4
        elif upside_space >= 7:
            score1 = 3
        elif upside_space >= 5:
            score1 = 2
        else:
            score1 = 0
        
        distance_pct = (price - long_strike) / price * 100 if long_strike < price else 0
        if distance_pct >= 10:
            score2 = 5
        elif distance_pct >= 7:
            score2 = 4
        elif distance_pct >= 5:
            score2 = 3
        else:
            score2 = 0
            
        return score1 + score2
    else:
        return 10

def calculate_theta(price, strike, iv, days_to_expiry, option_type="put"):
    """计算Theta（每日时间衰减）"""
    if days_to_expiry <= 0:
        return 0
    T = days_to_expiry / 365
    if T <= 0:
        return 0
    iv_decimal = iv / 100
    S = price
    K = strike
    
    d1 = (math.log(S / K) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
    
    if option_type == "put":
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) - 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(-d1 + iv_decimal * math.sqrt(T)) * 0.01
    else:
        theta = -(S * iv_decimal * norm.pdf(d1)) / (2 * math.sqrt(T)) + 0.0389 * K * math.exp(-0.05 * T) * norm.cdf(d1 - iv_decimal * math.sqrt(T)) * 0.01
    
    return theta / 365

def calculate_theta_score(theta, premium, days_to_expiry, iv):
    """平衡的Theta评分（加入Vega风险调整）"""
    if days_to_expiry <= 0 or premium <= 0 or theta <= 0:
        return 0
    
    theta_efficiency = theta / math.sqrt(days_to_expiry)
    premium_efficiency = theta / premium * 100
    
    # Vega风险因子
    vega_risk = min(1.0, days_to_expiry / 30)
    
    theta_score = theta_efficiency * 400 + premium_efficiency * 1.5
    
    # 短期期权扣分
    if days_to_expiry < 7:
        theta_score *= 0.7
    elif days_to_expiry < 14:
        theta_score *= 0.85
    
    # 高IV环境扣分
    if iv > 50:
        theta_score *= 0.8
    
    return min(theta_score, 20)

def calculate_option_price(price, strike, iv, days_to_expiry, option_type="put", r=0.05):
    """Black-Scholes模型计算期权权利金"""
    if days_to_expiry <= 0:
        return 0
    T = days_to_expiry / 365
    if T <= 0:
        return 0
    
    S = price
    K = strike
    sigma = iv / 100
    r_rate = r
    
    d1 = (math.log(S / K) + (r_rate + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if option_type == "put":
        price = K * math.exp(-r_rate * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    else:
        price = S * norm.cdf(d1) - K * math.exp(-r_rate * T) * norm.cdf(d2)
    
    return price

def get_option_price_from_yfinance(ticker, strike, days_to_expiry, option_type="put"):
    """从yfinance获取真实期权价格"""
    try:
        opts = ticker.option_chain()
        if option_type == "put":
            df = opts.puts
        else:
            df = opts.calls
        
        df = df[df['strike'] == strike]
        if df.empty:
            return None, "未找到期权"
        
        row = df.iloc[0]
        price = row['lastPrice']
        
        if price <= 0.01 and row['bid'] > 0 and row['ask'] > 0:
            price = (row['bid'] + row['ask']) / 2
        
        if price <= 0.01:
            return None, "无有效价格"
        
        return price, "yfinance"
    except Exception as e:
        return None, str(e)[:20]

def calculate_composite_score(rr_ratio, liquidity_score, safety_distance, sentiment_score, theta_score=0, iv_score=0, delta_score=0, gamma_score=0, downside_score=0):
    """综合评分（各指标加权，含下跌空间保护）
    
    权重调整:
    - 下跌空间 (10分): 不容易被击穿
    - 安全边际 (12分): 权利金安全垫
    - 流动性 (12分): 买卖价差+成交量
    - Delta (8分): 市场中立
    - Gamma (6分): Gamma 风险
    """
    # 风险回报比率 (20分)
    rr_score = min(rr_ratio / 2.0, 1.0) * 20
    
    # 流动性 (12分)
    liq_score = min(liquidity_score * 1.2, 12)
    
    # 安全边际 (12分)
    safety_score = min(safety_distance, 12)
    
    # 情绪 (10分) - 0-100评分直接映射
    sent_score = max(0, min(sentiment_score, 100)) / 10  # 0-10
    
    # Theta评分 (10分)
    theta_adj = min(theta_score, 10)
    
    # IV评分 (10分)
    iv_adj = iv_score
    
    # 下跌空间评分 (10分) - 不容易被击穿
    downside_adj = min(downside_score, 10)
    
    # Delta 评分 (8分)
    delta_adj = min(delta_score, 8)
    
    # Gamma 评分 (6分)
    gamma_adj = min(gamma_score, 6)
    
    total = rr_score + liq_score + safety_score + sent_score + theta_adj + iv_adj + downside_adj + delta_adj + gamma_adj
    return min(100, max(0, total))

# ==================== 策略计算 ====================

def get_available_expirations(ticker):
    """获取可用的到期日（直接用 ticker.options，不逐个猜测）"""
    if 'http_proxy' not in os.environ or not os.environ.get('http_proxy'):
        os.environ['http_proxy'] = PROXY
        os.environ['https_proxy'] = PROXY

    expirations = []
    base_date = datetime.now().date()

    # ticker.options 返回字符串日期列表，直接用
    for exp_date_str in ticker.options:
        try:
            exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
            days = (exp_date - base_date).days
            if days < 1 or days > 7:  # 7天内滚动
                continue
            if exp_date.weekday() not in [0, 1, 2, 3, 4]:  # 排除周末
                continue
            opts = ticker.option_chain(exp_date_str)
            if opts.puts is not None and not opts.puts.empty:
                expirations.append({
                    'date': exp_date_str,
                    'days': days,
                    'options': opts
                })
        except Exception:
            pass

    return expirations

def calculate_bull_put_spread(price, iv, short_strike, long_strike, days, ticker=None, options_data=None):
    """计算Bull Put Spread"""
    if options_data is not None:
        puts = options_data.puts
        p_short = puts[puts['strike'] == short_strike]
        p_long = puts[puts['strike'] == long_strike]
        
        liq_short = calculate_liquidity_score_from_options(options_data, short_strike, "put")
        liq_long = calculate_liquidity_score_from_options(options_data, long_strike, "put")
        
        if not p_short.empty and not p_long.empty:
            premium_short = p_short.iloc[0]['lastPrice']
            premium_long = p_long.iloc[0]['lastPrice']
            if premium_short <= 0.01:
                premium_short = calculate_option_price(price, short_strike, iv, days, "put")
            if premium_long <= 0.01:
                premium_long = calculate_option_price(price, long_strike, iv, days, "put")
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days, "put")
            premium_long = calculate_option_price(price, long_strike, iv, days, "put")
    elif ticker:
        premium_short_src, _ = get_option_price_from_yfinance(ticker, short_strike, days, "put")
        premium_long_src, _ = get_option_price_from_yfinance(ticker, long_strike, days, "put")
        
        premium_short = premium_short_src if premium_short_src else calculate_option_price(price, short_strike, iv, days, "put")
        premium_long = premium_long_src if premium_long_src else calculate_option_price(price, long_strike, iv, days, "put")
        liq_short = liq_long = 5
    else:
        premium_short = calculate_option_price(price, short_strike, iv, days, "put")
        premium_long = calculate_option_price(price, long_strike, iv, days, "put")
        liq_short = liq_long = 5
    
    premium = premium_short - premium_long
    width = short_strike - long_strike
    max_profit = premium
    max_loss = width - premium
    
    theta_short = abs(calculate_theta(price, short_strike, iv, days, "put"))
    theta_long = abs(calculate_theta(price, long_strike, iv, days, "put"))
    theta = theta_short - theta_long
    
    # Delta/Gamma 计算
    delta_short, gamma_short = calculate_delta_gamma(price, short_strike, iv, days, "put")
    delta_long, gamma_long = calculate_delta_gamma(price, long_strike, iv, days, "put")
    delta = delta_short - delta_long
    gamma = gamma_short - gamma_long
    
    return {
        'short_strike': short_strike,
        'long_strike': long_strike,
        'premium': premium,
        'max_profit': max_profit * 100,
        'max_loss': max_loss * 100,
        'theta': theta,
        'width': width,
        'liquidity': (liq_short + liq_long) / 2,
        'safety_distance': calculate_safety_distance(price, short_strike, long_strike, premium, "Bull_Put"),
        'delta': delta,
        'gamma': gamma
    }

def calculate_bull_call_spread(price, iv, long_strike, short_strike, days, ticker=None, options_data=None):
    """计算Bull Call Spread"""
    if options_data is not None:
        calls = options_data.calls
        c_short = calls[calls['strike'] == short_strike]
        c_long = calls[calls['strike'] == long_strike]
        
        liq_short = calculate_liquidity_score_from_options(options_data, short_strike, "call")
        liq_long = calculate_liquidity_score_from_options(options_data, long_strike, "call")
        
        if not c_short.empty and not c_long.empty:
            premium_short = c_short.iloc[0]['lastPrice']
            premium_long = c_long.iloc[0]['lastPrice']
            if premium_short <= 0.01:
                premium_short = calculate_option_price(price, short_strike, iv, days, "call")
            if premium_long <= 0.01:
                premium_long = calculate_option_price(price, long_strike, iv, days, "call")
        else:
            premium_short = calculate_option_price(price, short_strike, iv, days, "call")
            premium_long = calculate_option_price(price, long_strike, iv, days, "call")
    elif ticker:
        premium_short_src, _ = get_option_price_from_yfinance(ticker, short_strike, days, "call")
        premium_long_src, _ = get_option_price_from_yfinance(ticker, long_strike, days, "call")
        
        premium_short = premium_short_src if premium_short_src else calculate_option_price(price, short_strike, iv, days, "call")
        premium_long = premium_long_src if premium_long_src else calculate_option_price(price, long_strike, iv, days, "call")
        liq_short = liq_long = 5
    else:
        premium_short = calculate_option_price(price, short_strike, iv, days, "call")
        premium_long = calculate_option_price(price, long_strike, iv, days, "call")
        liq_short = liq_long = 5
    
    premium = premium_short - premium_long
    width = short_strike - long_strike
    max_profit = width - premium
    max_loss = premium
    
    theta_short = abs(calculate_theta(price, short_strike, iv, days, "call"))
    theta_long = abs(calculate_theta(price, long_strike, iv, days, "call"))
    theta = theta_short - theta_long
    
    # Delta/Gamma 计算
    delta_short, gamma_short = calculate_delta_gamma(price, short_strike, iv, days, "call")
    delta_long, gamma_long = calculate_delta_gamma(price, long_strike, iv, days, "call")
    delta = delta_short - delta_long
    gamma = gamma_short - gamma_long
    
    return {
        'long_strike': long_strike,
        'short_strike': short_strike,
        'premium': premium,
        'max_profit': max_profit * 100,
        'max_loss': max_loss * 100,
        'theta': theta,
        'width': width,
        'liquidity': (liq_short + liq_long) / 2,
        'safety_distance': calculate_safety_distance(price, short_strike, long_strike, premium, "Bull_Call"),
        'delta': delta,
        'gamma': gamma
    }

def calculate_short_put(price, iv, strike, days, ticker=None, options_data=None):
    """计算Short Put"""
    if options_data is not None:
        puts = options_data.puts
        p = puts[puts['strike'] == strike]
        
        liq = calculate_liquidity_score_from_options(options_data, strike, "put")
        
        if not p.empty:
            premium = p.iloc[0]['lastPrice']
            if premium <= 0.01:
                premium = calculate_option_price(price, strike, iv, days, "put")
        else:
            premium = calculate_option_price(price, strike, iv, days, "put")
    elif ticker:
        premium_src, _ = get_option_price_from_yfinance(ticker, strike, days, "put")
        premium = premium_src if premium_src else calculate_option_price(price, strike, iv, days, "put")
        liq = 5
    else:
        premium = calculate_option_price(price, strike, iv, days, "put")
        liq = 5
    
    theta = abs(calculate_theta(price, strike, iv, days, "put"))
    
    # Delta/Gamma 计算
    delta, gamma = calculate_delta_gamma(price, strike, iv, days, "put")
    
    return {
        'strike': strike,
        'premium': premium,
        'max_profit': premium * 100,
        'max_loss': (strike - premium) * 100,
        'theta': theta,
        'width': strike * 0.05,
        'liquidity': liq,
        'safety_distance': calculate_safety_distance(price, strike, 0, premium, "Short_Put"),
        'delta': delta,
        'gamma': gamma
    }

def calculate_iron_condor(price, iv, put_short_strike, put_long_strike, call_short_strike, call_long_strike, days, ticker=None, options_data=None):
    """计算 Iron Condor（铁鹰价差）
    
    构成：
    - 卖出的看跌期权（put_short）
    - 买入的看跌期权（put_long）
    - 卖出的看涨期权（call_short）
    - 买入的看涨期权（call_long）
    """
    # 计算各腿的价格
    def get_premium(strike, days, option_type):
        if options_data is not None:
            if option_type == "put":
                opts = options_data.puts
            else:
                opts = options_data.calls
            opt = opts[opts['strike'] == strike]
            if not opt.empty:
                premium = opt.iloc[0]['lastPrice']
                if premium > 0.01:
                    return premium, calculate_liquidity_score_from_options(options_data, strike, option_type)
            # 如果没有真实数据，用模型价格
            premium = calculate_option_price(price, strike, iv, days, option_type)
            return premium, 5
        else:
            premium = calculate_option_price(price, strike, iv, days, option_type)
            return premium, 5
    
    # 获取各腿的权利金和流动性
    put_short_prem, liq_put_short = get_premium(put_short_strike, days, "put")
    put_long_prem, liq_put_long = get_premium(put_long_strike, days, "put")
    call_short_prem, liq_call_short = get_premium(call_short_strike, days, "call")
    call_long_prem, liq_call_long = get_premium(call_long_strike, days, "call")
    
    # 净权利金（卖出收取 - 买入付出）
    premium = put_short_prem + call_short_prem - put_long_prem - call_long_prem
    
    # 宽度
    put_width = put_short_strike - put_long_strike
    call_width = call_long_strike - call_short_strike
    max_width = max(put_width, call_width)
    
    # 最大盈利（两侧都不到期）
    max_profit = premium * 100
    
    # 最大亏损（任一侧被行权）
    max_loss = (max_width - premium) * 100
    
    # Theta 计算
    theta_put_short = abs(calculate_theta(price, put_short_strike, iv, days, "put"))
    theta_put_long = abs(calculate_theta(price, put_long_strike, iv, days, "put"))
    theta_call_short = abs(calculate_theta(price, call_short_strike, iv, days, "call"))
    theta_call_long = abs(calculate_theta(price, call_long_strike, iv, days, "call"))
    theta = theta_put_short + theta_call_short - theta_put_long - theta_call_long
    
    # Delta/Gamma 计算（组合）
    delta_ps, gamma_ps = calculate_delta_gamma(price, put_short_strike, iv, days, "put")
    delta_pl, gamma_pl = calculate_delta_gamma(price, put_long_strike, iv, days, "put")
    delta_cs, gamma_cs = calculate_delta_gamma(price, call_short_strike, iv, days, "call")
    delta_cl, gamma_cl = calculate_delta_gamma(price, call_long_strike, iv, days, "call")
    
    delta = delta_ps + delta_cs - delta_pl - delta_cl
    gamma = gamma_ps + gamma_cs - gamma_pl - gamma_cl
    
    # 流动性（取平均）
    liquidity = (liq_put_short + liq_put_long + liq_call_short + liq_call_long) / 4
    
    # 安全边际（两边距离现价的最小距离）
    put_safety = (put_short_strike - price) / price * 100
    call_safety = (call_short_strike - price) / price * 100
    safety_distance = min(abs(put_safety), abs(call_safety))
    
    return {
        'put_short_strike': put_short_strike,
        'put_long_strike': put_long_strike,
        'call_short_strike': call_short_strike,
        'call_long_strike': call_long_strike,
        'premium': premium,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'theta': theta,
        'width': max_width,
        'liquidity': liquidity,
        'safety_distance': safety_distance,
        'delta': delta,
        'gamma': gamma
    }

def calculate_full_score(strategy_params, strategy_type, price, days, iv, vix_signal="GREEN", sentiment="neutral"):
    """
    综合评分（含下跌空间保护）
    返回: (composite_score, rr_ratio, liquidity, safety, theta_score, iv_score, delta, gamma, delta_score, gamma_score, downside_score)
    """
    # 风险回报比
    max_profit = strategy_params.get('max_profit', 0)
    max_loss = strategy_params.get('max_loss', 0.01)
    rr_ratio = calculate_real_rr_ratio(max_profit, max_loss)
    
    # 流动性
    liquidity = strategy_params.get('liquidity', 5)
    
    # 安全边际
    safety = strategy_params.get('safety_distance', 10)
    
    # Theta评分
    theta = strategy_params.get('theta', 0)
    premium = strategy_params.get('premium', price * 0.02)
    theta_score = calculate_theta_score(theta, premium, days, iv)
    
    # IV评分
    iv_score = get_iv_score(iv)
    
    # Delta/Gamma 评分
    delta = strategy_params.get('delta', 0)
    gamma = strategy_params.get('gamma', 0)
    delta_score = calculate_delta_score(delta) if delta else 0
    gamma_score = calculate_gamma_score(gamma, days) if gamma else 0
    
    # 下跌空间评分（不容易被击穿）
    short_strike = strategy_params.get('short_strike', 0) or strategy_params.get('strike', 0) or strategy_params.get('put_short_strike', 0)
    downside_score = calculate_downside_score(price, short_strike) if short_strike else 0
    
    # 详细日志
    log_update("score_calculated", {
        "strategy": strategy_type,
        "days": days,
        "delta": round(delta, 4) if delta else 0,
        "gamma": round(gamma, 4) if gamma else 0,
        "delta_score": delta_score,
        "gamma_score": gamma_score,
        "downside_score": downside_score
    })
    
    # 综合评分
    composite = calculate_composite_score(rr_ratio, liquidity, safety, sentiment, theta_score, iv_score, delta_score, gamma_score, downside_score)
    
    return composite, rr_ratio, liquidity, safety, theta_score, iv_score, delta, gamma, delta_score, gamma_score, downside_score

# ==================== 格式三输出函数 ====================
def print_format3_output(STOCK, price, iv, vix, vix_signal, all_results, expiry_info='03-27'):
    """手机端优化版输出 - 简洁紧凑，无框线字符"""
    print(f"\n📊 {STOCK} | ${price:.2f} | VIX:{vix:.0f}({vix_signal}) | IV:{iv:.0f}%")
    
    # Bull Put Spread - Top 3
    bp_list = all_results.get('Bull_Put', [])[:3]
    if bp_list:
        print("\n🐂 Bull Put Spread")
        print(f"  到期    | Short  | Long   | 价差    | 权利金    | 最大风险   | RR     | 评分")
        print(f"  {'-'*8:<8} | {'-'*8:<8} | {'-'*8:<8} | {'-'*8:<8} | {'-'*10:<10} | {'-'*10:<10} | {'-'*6:<6} | {'-'*4}")
        for i, bp in enumerate(bp_list, 1):
            strike_short = bp.get('short_strike', 0)
            strike_long = bp.get('long_strike', 0)
            credit = bp.get('premium', 0)
            width = bp.get('width', 15)
            max_risk = width - credit
            rr = bp.get('rr_ratio', 0)
            score = bp.get('score', 0)
            expiry = bp.get('expiry', expiry_info[:5])
            decision = bp.get('decision', '🔴禁止')
            print(f"  {expiry:<8} | {strike_short:<8.0f} | {strike_long:<8.0f} | {width:<8.2f} | {credit:<10.2f} | {max_risk:<10.2f} | {rr:<6.2f} | {score:.0f}{decision}")
    
    # Short Put - Top 3
    sp_list = all_results.get('Short_Put', [])[:3]
    if sp_list:
        print("\n📉 Short Put")
        print(f"  到期    | Strike | 距现价   | 权利金    | 保金(估)   | RR     | 评分")
        print(f"  {'-'*8:<8} | {'-'*8:<8} | {'-'*8:<8} | {'-'*10:<10} | {'-'*10:<10} | {'-'*6:<6} | {'-'*4}")
        for i, sp in enumerate(sp_list, 1):
            strike = sp.get('strike', sp.get('short_strike', 0))
            credit = sp.get('premium', 0)
            dist = (price - strike) / price * 100
            rr = sp.get('rr_ratio', 0)
            score = sp.get('score', 0)
            expiry = sp.get('expiry', expiry_info[:5])
            decision = sp.get('decision', '🔴禁止')
            print(f"  {expiry:<8} | {strike:<8.0f} | {dist:<7.1f}% | {credit:<10.2f} | {'~$9600':<10} | {rr:<6.2f} | {score:.0f}{decision}")
    
    # Iron Condor - Top 3
    ic_list = all_results.get('Iron_Condor', [])[:3]
    if ic_list:
        print("\n🦅 Iron Condor")
        print(f"  到期    | ShortPut | LongPut  | ShortCall| LongCall | 权利金   | 最大风险   | RR     | 评分")
        print(f"  {'-'*8:<8} | {'-'*9:<9} | {'-'*9:<9} | {'-'*9:<9} | {'-'*9:<9} | {'-'*9:<9} | {'-'*9:<9} | {'-'*6:<6} | {'-'*4}")
        for i, ic in enumerate(ic_list, 1):
            ps = ic.get('put_short_strike', 0)
            pl = ic.get('put_long_strike', 0)
            cs = ic.get('call_short_strike', 0)
            cl = ic.get('call_long_strike', 0)
            credit = ic.get('premium', 0)
            max_risk = ic.get('max_loss', 0) / 100
            rr = ic.get('rr_ratio', 0)
            score = ic.get('score', 0)
            expiry = ic.get('expiry', expiry_info[:5])
            decision = ic.get('decision', '🔴禁止')
            print(f"  {expiry:<8} | {ps:<9.0f} | {pl:<9.0f} | {cs:<9.0f} | {cl:<9.0f} | {credit:<9.2f} | {max_risk:<9.2f} | {rr:<6.2f} | {score:.0f}{decision}")
    
    # Bull Call Spread - Top 3
    bc_list = all_results.get('Bull_Call', [])[:3]
    if bc_list:
        print("\n🐂 Bull Call Spread")
        print(f"  到期    | Short  | Long   | 价差    | 权利金    | 最大风险   | RR     | 评分")
        print(f"  {'-'*8:<8} | {'-'*8:<8} | {'-'*8:<8} | {'-'*8:<8} | {'-'*10:<10} | {'-'*10:<10} | {'-'*6:<6} | {'-'*4}")
        for i, bc in enumerate(bc_list, 1):
            short_s = bc.get('short_strike', 0)
            long_s = bc.get('long_strike', 0)
            credit = bc.get('premium', 0)
            width = bc.get('width', 15)
            max_risk = width - credit
            rr = bc.get('rr_ratio', 0)
            score = bc.get('score', 0)
            expiry = bc.get('expiry', expiry_info[:5])
            decision = bc.get('decision', '🔴禁止')
            print(f"  {expiry:<8} | {short_s:<8.0f} | {long_s:<8.0f} | {width:<8.2f} | {credit:<10.2f} | {max_risk:<10.2f} | {rr:<6.2f} | {score:.0f}{decision}")
    
    # 汇总
    bp_s = bp_list[0].get('score', 0) if bp_list else 0
    sp_s = sp_list[0].get('score', 0) if sp_list else 0
    ic_s = ic_list[0].get('score', 0) if ic_list else 0
    bc_s = bc_list[0].get('score', 0) if bc_list else 0
    bp_r = bp_list[0].get('decision', '🔴禁止') if bp_list else '🔴禁止'
    sp_r = sp_list[0].get('decision', '🔴禁止') if sp_list else '🔴禁止'
    ic_r = ic_list[0].get('decision', '🔴禁止') if ic_list else '🔴禁止'
    bc_r = bc_list[0].get('decision', '🔴禁止') if bc_list else '🔴禁止'

# ==================== 主程序 ====================
# 确保代理已设置（yfinance 通过环境变量使用代理）
os.environ.setdefault('http_proxy', PROXY)
os.environ.setdefault('https_proxy', PROXY)

print("="*80)
print("🚀 期权多策略组合推荐 V2 (优化版)")
print("="*80)
print(f"📊 股票: {', '.join(STOCKS)}")

# strategy_engine 路径（与 unified_fetcher 同级目录）
_engine_path = Path('/root/.openclaw/workspace/quant/StockAssistant')
if str(_engine_path) not in sys.path:
    sys.path.insert(0, str(_engine_path))

vix, vix_ma, deviation = get_vix()
vix_signal, vix_score = calculate_vix_signal(vix, vix_ma, deviation)
threshold = get_dynamic_threshold(vix_signal, iv=30)  # 默认IV=30

print(f"\n📊 VIX: {vix:.2f} | MA10: {vix_ma:.2f} | 偏离度: {deviation:.1f}%")
print(f"   信号: {vix_signal} | 评分: {vix_score}/100")
print(f"   动态阈值: {threshold} (≥{threshold}+15开仓)")

_all_stocks_data = {}  # JSON 模式收集器
for STOCK in STOCKS:
    print(f"\n{'='*60}")
    print(f"📈 处理: {STOCK}")
    print("="*60)
    
    # ── CTX-FILE 模式：使用统一数据口，不发网络请求 ──
    if STOCK in _ctx_data:
        ctx = _ctx_data[STOCK]
        price = ctx.get('price')
        iv_raw = ctx.get('iv', 35)
        iv = iv_raw * 100 if isinstance(iv_raw, float) and 0 < iv_raw < 1 else iv_raw
        vix_val = ctx.get('vix')
        vix_ma = ctx.get('vix_ma10', vix_val)
        sentiment_label = ctx.get('sentiment', 'neutral')
        sentiment_score = ctx.get('sentiment_score', 50)
        option_chains = ctx.get('option_chains', [])

        vix_signal, vix_score = calculate_vix_signal(vix_val, vix_ma, 0)
        threshold = get_dynamic_threshold(vix_signal, iv)
        print(f"\n📈 {STOCK} (统一数据口) 价格: ${price:.2f} | IV: {iv:.1f}% | VIX: {vix_val}({vix_signal}) | 舆情: {sentiment_label}")

        # 计算 RSI（用于入场过滤器）
        rsi_val = None
        if len(hist) >= 14:
            close = hist['Close']
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_series = 100 - 100 / (1 + rs)
            rsi_val = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else None

        engine_ctx = {
            'price': price, 'iv': iv, 'vix': vix_val,
            'vix_signal': vix_signal, 'vix_ma10': vix_ma,
            'sentiment': sentiment_label, 'option_chains': option_chains,
            'rsi': rsi_val,
        }
        print(f"   📊 RSI: {rsi_val:.1f}" if rsi_val else "   📊 RSI: N/A")
        from strategy_engine import calculate_strategies_from_ctx
        all_results = calculate_strategies_from_ctx(STOCK, engine_ctx)
        _all_stocks_data[STOCK] = {
            'price': price, 'iv': iv, 'vix': vix_val,
            'vix_signal': vix_signal, 'sentiment': sentiment_label,
            'sentiment_score': sentiment_score, 'strategies': all_results
        }
        print(f"   ✅ strategy_engine 输出 {sum(len(v) for v in all_results.values())} 条策略")
        continue

    # ── 独立请求模式（原逻辑）──
    default_prices = {'TSLA': 400.0, 'NVDA': 180.0, 'AAPL': 250.0, 'MSFT': 400.0, 'GOOGL': 310.0, 'AMZN': 220.0}
    price = default_prices.get(STOCK, 100.0)
    ticker = None
    if not MOCK_MODE:
        try:
            ticker = yf.Ticker(STOCK)
            hist = ticker.history(period="30d")
            if hist.empty:
                print(f"⚠️ {STOCK} 无法获取实时数据，使用默认价格 ${price}")
            else:
                close_price = hist['Close'].iloc[-1]
                close_price = close_price.item() if hasattr(close_price, 'item') else close_price
                if pd.isna(close_price):
                    print(f"⚠️ {STOCK} 获取价格失败，使用默认价格 ${price}")
                else:
                    price = close_price
        except Exception as e:
            print(f"⚠️ {STOCK} 获取数据失败: {e}，使用默认价格 ${price}")

    estimated_iv, hv = get_stock_iv_from_hv(ticker, price)
    iv = estimated_iv if not pd.isna(estimated_iv) else hv
    iv = iv if not pd.isna(iv) else 35

    sentiment_score, sentiment_label, sent_data = get_sentiment(STOCK)
    iv_score = get_iv_score(iv)

    mentions = sent_data.get('mentions', 0)
    upvotes = sent_data.get('upvotes', 0)
    print(f"\n📈 {STOCK} 价格: ${price:.2f} | IV: {iv:.1f}% | 舆情: {sentiment_label} (评分: {sentiment_score:.0f}/100, Reddit {mentions}提及/{upvotes}点赞)")

    expirations = get_available_expirations(ticker)
    if not expirations:
        print(f"⚠️ {STOCK} 无可用期权到期日")
        continue

    expirations = [e for e in expirations if e['days'] <= 7]
    if not expirations:
        print(f"⚠️ {STOCK} 14天内无到期日")
        continue

    print(f"📅 可用到期日(14天内): {[e['date'] for e in expirations[:5]]}")
    
    # 收集所有组合
    all_results = {
        'Bull_Put': [],
        'Bull_Call': [],
        'Short_Put': [],
        'Iron_Condor': []
    }
    
    for exp in expirations:
        days = exp['days']
        exp_date = exp['date']
        expiry_short = exp_date[5:] if exp_date else ""
        options_data = exp['options']
        
        ratios = [
            (0.97, 0.93),
            (0.95, 0.91),
            (0.93, 0.89),
            (0.98, 0.94),
            (0.92, 0.88),
        ]
        
        for short_ratio, long_ratio in ratios:
            short_strike = round(price * short_ratio / 2.5) * 2.5
            long_strike = round(price * long_ratio / 2.5) * 2.5
            
            # Bull Put Spread
            bp = calculate_bull_put_spread(price, iv, short_strike, long_strike, days, ticker, options_data)
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = calculate_full_score(bp, 'Bull_Put', price, days, iv, vix_signal, sentiment_score)
            bp['score'] = score
            bp['rr_ratio'] = rr
            bp['liquidity'] = liq
            bp['safety'] = safety
            bp['theta_score'] = theta_s
            bp['delta'] = delta
            bp['gamma'] = gamma
            bp['delta_score'] = delta_s
            bp['gamma_score'] = gamma_s
            bp['downside_score'] = downside_s
            bp['days'] = days
            bp['expiry'] = expiry_short
            bp['strike_str'] = f"卖${short_strike:.0f}/买${long_strike:.0f}"
            # 稳健型：安全边际<5禁止开仓
            bp['decision'] = "🔴禁止" if safety < 5 else ("✅开仓" if score >= threshold + 15 else ("🟡试探" if score >= threshold else "🔴禁止"))
            all_results['Bull_Put'].append(bp)
            
            # Bull Call Spread
            long_s = round(price * (2 - short_ratio) / 2.5) * 2.5
            short_s = round(price * (2 - long_ratio) / 2.5) * 2.5
            bc = calculate_bull_call_spread(price, iv, long_s, short_s, days, ticker, options_data)
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = calculate_full_score(bc, 'Bull_Call', price, days, iv, vix_signal, sentiment_score)
            bc['score'] = score
            bc['rr_ratio'] = rr
            bc['liquidity'] = liq
            bc['safety'] = safety
            bc['theta_score'] = theta_s
            bc['delta'] = delta
            bc['gamma'] = gamma
            bc['delta_score'] = delta_s
            bc['gamma_score'] = gamma_s
            bc['downside_score'] = downside_s
            bc['days'] = days
            bc['expiry'] = expiry_short
            bc['strike_str'] = f"买${long_s:.0f}/卖${short_s:.0f}"
            # 稳健型：安全边际<5禁止开仓
            bc['decision'] = "🔴禁止" if safety < 5 else ("✅开仓" if score >= threshold + 15 else ("🟡试探" if score >= threshold else "🔴禁止"))
            all_results['Bull_Call'].append(bc)
            
            # Short Put
            sp = calculate_short_put(price, iv, short_strike, days, ticker, options_data)
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = calculate_full_score(sp, 'Short_Put', price, days, iv, vix_signal, sentiment_score)
            sp['score'] = score
            sp['delta'] = delta
            sp['gamma'] = gamma
            sp['delta_score'] = delta_s
            sp['gamma_score'] = gamma_s
            sp['downside_score'] = downside_s
            sp['rr_ratio'] = rr
            sp['liquidity'] = liq
            sp['safety'] = safety
            sp['theta_score'] = theta_s
            sp['delta'] = delta
            sp['gamma'] = gamma
            sp['delta_score'] = delta_s
            sp['gamma_score'] = gamma_s
            sp['days'] = days
            sp['expiry'] = expiry_short
            sp['strike_str'] = f"卖${short_strike:.0f}"
            # 稳健型：安全边际<5禁止开仓
            sp['decision'] = "🔴禁止" if safety < 5 else ("✅开仓" if score >= threshold + 15 else ("🟡试探" if score >= threshold else "🔴禁止"))
            all_results['Short_Put'].append(sp)
            
            # ===== Iron Condor（铁鹰价差）=====
            # 参数：Put边和Call边各两个行权价（收窄版，适合震荡行情）
            put_short_r = 0.95   # 卖Put行权价比例（距现价约5%）
            put_long_r = 0.90    # 买Put行权价比例（距现价约10%）
            call_short_r = 1.05  # 卖Call行权价比例（距现价约5%）
            call_long_r = 1.10   # 买Call行权价比例（距现价约10%）
            
            ic_put_short = round(price * put_short_r / 2.5) * 2.5
            ic_put_long = round(price * put_long_r / 2.5) * 2.5
            ic_call_short = round(price * call_short_r / 2.5) * 2.5
            ic_call_long = round(price * call_long_r / 2.5) * 2.5
            
            ic = calculate_iron_condor(price, iv, ic_put_short, ic_put_long, ic_call_short, ic_call_long, days, ticker, options_data)
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = calculate_full_score(ic, 'Iron_Condor', price, days, iv, vix_signal, sentiment_score)
            ic['score'] = score
            ic['rr_ratio'] = rr
            ic['liquidity'] = liq
            ic['safety'] = safety
            ic['theta_score'] = theta_s
            ic['delta'] = delta
            ic['gamma'] = gamma
            ic['delta_score'] = delta_s
            ic['gamma_score'] = gamma_s
            ic['downside_score'] = downside_s
            ic['days'] = days
            ic['expiry'] = expiry_short
            ic['strike_str'] = f"卖PUT{ic_put_short:.0f}/买PUT{ic_put_long:.0f}|卖CALL{ic_call_short:.0f}/买CALL{ic_call_long:.0f}"
            # Iron Condor 需要更大的安全边际
            ic['decision'] = "🔴禁止" if safety < 8 else ("✅开仓" if score >= threshold + 15 else ("🟡试探" if score >= threshold else "🔴禁止"))
            all_results['Iron_Condor'].append(ic)
    
    # 按评分排序，10天以内优先
    for strategy in all_results:
        # 给10天以内的策略加3分短期偏好
        for s in all_results[strategy]:
            if s.get('days', 30) <= 10:
                s['score'] += 3
        all_results[strategy].sort(key=lambda x: x['score'], reverse=True)
        all_results[strategy] = all_results[strategy][:5]
    
    # 获取各策略最佳（用于到期日判断和格式三输出）
    bp_best = all_results['Bull_Put'][0] if all_results['Bull_Put'] else None
    
    # 添加到期日信息（用单独的变量避免覆盖dict）
    expiry_info = bp_best.get('expiry') if bp_best else '03-27'
    
    # 调用格式三输出
    print_format3_output(STOCK, price, iv, vix, vix_signal, all_results, expiry_info)

    # JSON 模式：收集结构化数据
    _all_stocks_data[STOCK] = {
        'price': price,
        'iv': iv,
        'vix': vix,
        'vix_signal': vix_signal,
        'sentiment': sentiment_label,
        'sentiment_score': sentiment_score,
        'strategies': all_results
    }

    # 额外保留简洁版输出（可选）
    print("\n💡 组合建议：")
    bc_best = all_results['Bull_Call'][0] if all_results['Bull_Call'] else None
    sp_best = all_results['Short_Put'][0] if all_results['Short_Put'] else None
    ic_best = all_results['Iron_Condor'][0] if all_results['Iron_Condor'] else None
    
    open_strategies = []
    if bp_best and bp_best['decision'] == "✅开仓":
        open_strategies.append(f"Bull Put (卖{bp_best['short_strike']:.0f}/买{bp_best['long_strike']:.0f})")
    if bc_best and bc_best['decision'] == "✅开仓":
        open_strategies.append(f"Bull Call (买{bc_best['long_strike']:.0f}/卖{bc_best['short_strike']:.0f})")
    if sp_best and sp_best['decision'] == "✅开仓":
        open_strategies.append(f"Short Put (卖{sp_best.get('strike', sp_best.get('short_strike', 0)):.0f})")
    if ic_best and ic_best['decision'] == "✅开仓":
        open_strategies.append("Iron Condor")
    
    if open_strategies:
        print(f"- 推荐策略: {', '.join(open_strategies)}")
        # 计算建议仓位
        position = len(open_strategies) * 20
        print(f"- 仓位: {position}% (每策略20%)")
        print(f"- 到期日: {bp_best['expiry'] if bp_best else 'N/A'}")
    else:
        print(f"- 推荐策略: 等待更好时机")
    
    # 统计
    total = sum(len(v) for v in all_results.values())
    open_count = sum(1 for v in all_results.values() for x in v if x['decision'] == "✅开仓")
    try_count = sum(1 for v in all_results.values() for x in v if x['decision'] == "🟡试探")
    red_count = total - open_count - try_count
    
    # 展开各策略详情
    from collections import Counter
    open_strats = [k for k, v in all_results.items() for x in v if x['decision'] == "✅开仓"]
    try_strats = [k for k, v in all_results.items() for x in v if x['decision'] == "🟡试探"]
    red_strats = [k for k, v in all_results.items() for x in v if x['decision'] == "🔴禁止"]
    
    print(f"\n📊 统计: ✅{open_count} | 🟡{try_count} | 🔴{red_count}")
    if open_strats:
        open_counts = Counter(open_strats)
        open_labels = [f"{k}×{v}" for k, v in open_counts.items()]
        print(f"   ✅建议开仓: {', '.join(open_labels)}")
    if try_strats:
        try_counts = Counter(try_strats)
        try_labels = [f"{k}×{v}" for k, v in try_counts.items()]
        print(f"   🟡可以试探: {', '.join(try_labels)}")
    if red_strats:
        red_counts = Counter(red_strats)
        red_labels = [f"{k}×{v}" for k, v in red_counts.items()]
        print(f"   🔴禁止开仓: {', '.join(red_labels)}")

if JSON_MODE:
    sys.stdout = _stdout
    print(json.dumps(_all_stocks_data, ensure_ascii=False, default=str))
else:
    print(f"\n✅ 多策略分析完成: {', '.join(STOCKS)}")
