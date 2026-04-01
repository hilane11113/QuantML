#!/usr/bin/env python3
"""
期权策略计算引擎 (strategy_engine.py)

所有计算函数 + 统一入口 calculate_strategies_from_ctx(symbol, ctx)
不发起任何网络请求，所有数据从 ctx 传入。

ctx 格式:
{
    'price': float,           # 股价
    'iv': float,              # 估算IV
    'vix': float,             # VIX
    'vix_ma10': float,        # VIX MA10
    'vix_signal': str,        # GREEN/YELLOW/RED
    'sentiment': str,         # bullish/neutral/bearish
    'sentiment_score': float,
    'option_chains': [{
        'date': '2026-04-01',
        'days': 3,
        'calls': [{}],         # to_dict('records')
        'puts':  [{}],
    }, ...]
}
"""

import math
import numpy as np
from scipy.stats import norm
from datetime import datetime
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 延迟导入胜率预测（避免循环依赖）
_win_rate_module = None
def _get_win_rate():
    global _win_rate_module
    if _win_rate_module is None:
        try:
            import sys
            sys.path.insert(0, '/root/.openclaw/workspace/quant/QuantML/models')
            import win_rate_predictor as wr
            _win_rate_module = wr
        except Exception:
            pass
    return _win_rate_module

# ==================== 希腊字母库 ====================
try:
    from blackscholes import BlackScholesPut, BlackScholesCall
    GREEKS_AVAILABLE = True
except ImportError:
    GREEKS_AVAILABLE = False


# ==================== 辅助计算函数 ====================

def calculate_delta_gamma(price, strike, iv, days_to_expiry, option_type="put"):
    if days_to_expiry <= 0:
        return 0.0, 0.0
    T = days_to_expiry / 365
    iv_decimal = iv / 100
    if T <= 0 or iv_decimal <= 0 or price <= 0 or strike <= 0:
        return 0.0, 0.0
    try:
        if GREEKS_AVAILABLE:
            if option_type == "put":
                bs = BlackScholesPut(S=price, K=strike, T=T, r=0.05, sigma=iv_decimal)
            else:
                bs = BlackScholesCall(S=price, K=strike, T=T, r=0.05, sigma=iv_decimal)
            return bs.delta(), bs.gamma()
    except Exception:
        pass
    return calculate_delta_gamma_manual(price, strike, iv, days_to_expiry, option_type)


def calculate_delta_gamma_manual(price, strike, iv, days_to_expiry, option_type="put"):
    if days_to_expiry <= 0:
        return 0.0, 0.0
    T = days_to_expiry / 365
    iv_decimal = iv / 100
    if T <= 0 or iv_decimal <= 0 or price <= 0 or strike <= 0:
        return 0.0, 0.0
    d1 = (math.log(price / strike) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
    d2 = d1 - iv_decimal * math.sqrt(T)
    if option_type == "put":
        delta = norm.cdf(d1) - 1
    else:
        delta = norm.cdf(d1)
    gamma = (norm.pdf(d1)) / (price * iv_decimal * math.sqrt(T))
    return delta, gamma


def calculate_delta_score(delta, target_delta_range=(-0.3, -0.2)):
    d = abs(delta - (target_delta_range[0] + target_delta_range[1]) / 2)
    return max(0, 10 - d * 20)


def calculate_gamma_score(gamma, days_to_expiry):
    if days_to_expiry <= 7:
        return 8
    elif days_to_expiry <= 14:
        return 9
    return 10


def calculate_downside_score(price, short_strike, iv=30):
    """基于价格到short_strike距离评分（用于Short Put）"""
    if short_strike >= price:
        return 10
    downside_space = (price - short_strike) / price * 100
    if downside_space >= 10:
        return 10
    elif downside_space >= 5:
        return 8
    elif downside_space >= 3:
        return 6
    return 4


def calculate_vix_signal(vix, vix_ma, deviation):
    if pd.isna(vix) or pd.isna(vix_ma):
        return "YELLOW"
    if vix > 30:
        return "RED"
    elif vix < 15:
        return "GREEN"
    elif vix > 25:
        return "YELLOW"
    elif vix > 20:
        return "YELLOW"
    if deviation > 15:
        return "RED"
    elif deviation < -10:
        return "GREEN"
    return "YELLOW"


def get_dynamic_threshold(vix_signal, iv):
    base = {"GREEN": 35, "YELLOW": 50, "RED": 60}.get(vix_signal, 50)
    if iv > 60:
        return base + 5
    if iv < 20:
        return base - 5
    return base


def get_iv_score(iv):
    if 30 <= iv <= 50:
        return 10
    elif 20 <= iv < 30 or 50 < iv <= 60:
        return 7
    elif iv < 20:
        return 5
    return 5


def calculate_real_rr_ratio(max_profit, max_loss):
    if max_loss <= 0:
        return 0
    return max_profit / max_loss


def calculate_liquidity_score_from_options(options_df, strike, option_type):
    if options_df is None or options_df.empty:
        return 3
    row = options_df[options_df.get('strike', pd.Series()) == strike]
    if not row.empty:
        bid = float(row.iloc[0].get('bid', 0))
        ask = float(row.iloc[0].get('ask', 0))
        vol = int(row.iloc[0].get('volume', 0))
        oi = int(row.iloc[0].get('openInterest', 0))
        spread = (ask - bid) / ((ask + bid) / 2 + 0.001)
        vol_score = min(vol / 500, 1) * 5
        oi_score = min(oi / 2000, 1) * 5
        spread_score = max(0, 5 - spread * 50)
        return round(vol_score + oi_score + spread_score)
    return 3


def calculate_safety_distance(price, short_strike, long_strike, premium, strategy_type):
    if strategy_type in ("Bull_Put", "Short_Put"):
        if short_strike >= price:
            return 0
        distance_pct = (price - short_strike) / price * 100
        if strategy_type == "Bull_Put":
            return round(distance_pct, 1)
        else:
            if distance_pct >= 10:
                return 10
            elif distance_pct >= 5:
                return 8
            elif distance_pct >= 3:
                return 6
            return 4
    elif strategy_type in ("Bull_Call",):
        if short_strike <= price:
            return 0
        upside_space = (short_strike - price) / price * 100
        if upside_space >= 10:
            return 10
        elif upside_space >= 5:
            return 8
        elif upside_space >= 3:
            return 6
        return 4
    elif strategy_type == "Iron_Condor":
        put_distance = (price - short_strike) / price * 100
        call_distance = (long_strike - price) / price * 100
        avg_distance = (put_distance + call_distance) / 2
        return round(avg_distance, 1)
    return 5


def calculate_theta(price, strike, iv, days_to_expiry, option_type="put"):
    if days_to_expiry <= 0 or price <= 0 or strike <= 0 or iv <= 0:
        return 0
    T = days_to_expiry / 365
    iv_decimal = iv / 100
    try:
        d1 = (math.log(price / strike) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
        d2 = d1 - iv_decimal * math.sqrt(T)
        if option_type == "put":
            theta = (-price * norm.pdf(d1) * iv_decimal / (2 * math.sqrt(T))
                      - iv_decimal * strike * norm.cdf(-d2) / (2 * math.sqrt(T))) / 365
        else:
            theta = (-price * norm.pdf(d1) * iv_decimal / (2 * math.sqrt(T))
                      + iv_decimal * strike * norm.cdf(d2) / (2 * math.sqrt(T))) / 365
        return theta
    except Exception:
        return 0


def calculate_theta_score(theta, premium, days_to_expiry, iv):
    if premium <= 0 or days_to_expiry <= 0:
        return 0
    theta_efficiency = theta / (premium / days_to_expiry + 0.001)
    premium_efficiency = premium / (days_to_expiry + 1)
    if days_to_expiry < 7:
        theta_efficiency *= 0.7
    if iv > 50:
        theta_efficiency *= 0.8
    return round(theta_efficiency * 400 + premium_efficiency * 1.5)


def calculate_option_price(price, strike, iv, days_to_expiry, option_type="put", r=0.05):
    if days_to_expiry <= 0 or price <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    T = days_to_expiry / 365
    iv_decimal = iv / 100
    try:
        d1 = (math.log(price / strike) + (iv_decimal ** 2 / 2) * T) / (iv_decimal * math.sqrt(T))
        d2 = d1 - iv_decimal * math.sqrt(T)
        if option_type == "put":
            price = strike * math.exp(-r * T) * norm.cdf(-d2) - price * norm.cdf(-d1)
        else:
            price = price * norm.cdf(d1) - strike * math.exp(-r * T) * norm.cdf(d2)
    except Exception:
        pass
    return price


def calculate_composite_score(rr_ratio, liquidity_score, safety_distance, sentiment_score,
                               theta_score=0, iv_score=0, delta_score=0, gamma_score=0, downside_score=0):
    # 子指标合理上限
    liquidity_score = min(liquidity_score, 10)
    theta_score = min(theta_score, 10)
    iv_score = min(iv_score, 10)
    delta_score = min(delta_score, 10)
    gamma_score = min(gamma_score, 10)
    downside_score = min(downside_score, 10)
    sentiment_score = max(0, min(sentiment_score, 100))

    # 各指标最大值（对应各自权重的满分）
    # liquidity_score max=10 → 贡献 30；theta_score max=10 → 贡献 5；sentiment_score max=100 → 贡献 30
    rr_contrib = min(rr_ratio, 0.5) / 0.5 * 25  # rr 0.5 满分25
    liq_contrib = liquidity_score / 10 * 30       # 流动性 10满分30
    safety_contrib = min(safety_distance, 10) / 10 * 10  # 安全边际 10满分10
    sent_contrib = sentiment_score / 100 * 30    # 情绪 100满分30
    theta_contrib = theta_score / 10 * 5          # theta 10满分5
    iv_contrib = iv_score / 10 * 5               # IV 10满分5
    delta_contrib = delta_score / 10 * 3         # delta 10满分3
    gamma_contrib = gamma_score / 10 * 3         # gamma 10满分3
    downside_contrib = downside_score / 10 * 5    # downside 10满分5

    total = (rr_contrib + liq_contrib + safety_contrib + sent_contrib
             + theta_contrib + iv_contrib + delta_contrib + gamma_contrib + downside_contrib)
    return min(100, round(total, 1))


def calculate_full_score(strategy_params, strategy_type, price, days, iv,
                         vix_signal="GREEN", sentiment="neutral"):
    rr_ratio = strategy_params.get('rr_ratio', 0)
    liquidity_score = strategy_params.get('liquidity_score', 3)
    safety = strategy_params.get('safety', 5)
    sentiment_map = {"bullish": 80, "neutral": 50, "bearish": 20}
    sentiment_score = sentiment_map.get(sentiment, 50)
    theta_s = strategy_params.get('theta_score', 0)
    iv_s = get_iv_score(iv)
    delta = strategy_params.get('delta', 0)
    gamma = strategy_params.get('gamma', 0)
    delta_s = calculate_delta_score(delta)
    gamma_s = calculate_gamma_score(gamma, days)
    downside_s = strategy_params.get('downside_score', 5)
    score = calculate_composite_score(
        rr_ratio, liquidity_score, safety, sentiment_score,
        theta_s, iv_s, delta_s, gamma_s, downside_s
    )
    # VIX 信号调整
    if vix_signal == "RED":
        score *= 0.7
    elif vix_signal == "GREEN":
        score *= 1.1
    return (min(100, score), rr_ratio, liquidity_score, safety, theta_s, iv_s,
            delta, gamma, delta_s, gamma_s, downside_s)


# ==================== VIX 信号差异化的 Strike 参数 ====================
# RED: 高波动 → short strike 远离现价（更安全），spread 更窄
# GREEN: 低波动 → short strike 贴近现价（收集更多权利金），spread 更宽
# YELLOW: 中等波动 → 中间位置
# ============================================================
# VIX 信号 → strike 参数（基于282笔历史数据分析优化）
# GREEN: VIX<15，低波动 → OTM 5%，贴近现价收权利金
# YELLOW: 15≤VIX<25，中波动 → OTM 7%（最佳历史胜率区间）
# RED: VIX≥25，高波动 → OTM 10%，尾部风险大需更价外
# ============================================================
VIX_STRIKE_PARAMS = {
    "GREEN": {
        "Bull_Put":    {"short_ratio": 0.95, "spread_width": 25},  # OTM 5%
        "Bull_Call":   {"short_ratio": 1.05, "spread_width": 25},
        "Short_Put":   {"short_ratio": 0.95, "spread_width": 0},   # OTM 5%
        "Iron_Condor": {"put_short_ratio": 0.95, "call_short_ratio": 1.05, "spread_width": 20},
    },
    "YELLOW": {
        "Bull_Put":    {"short_ratio": 0.93, "spread_width": 20},  # OTM 7%
        "Bull_Call":   {"short_ratio": 1.07, "spread_width": 20},
        "Short_Put":   {"short_ratio": 0.93, "spread_width": 0},   # OTM 7%
        "Iron_Condor": {"put_short_ratio": 0.93, "call_short_ratio": 1.07, "spread_width": 18},
    },
    "RED": {
        "Bull_Put":    {"short_ratio": 0.90, "spread_width": 15},  # OTM 10%
        "Bull_Call":   {"short_ratio": 1.10, "spread_width": 15},
        "Short_Put":   {"short_ratio": 0.90, "spread_width": 0},   # OTM 10%
        "Iron_Condor": {"put_short_ratio": 0.90, "call_short_ratio": 1.10, "spread_width": 15},
    },
}

# ============================================================
# 入场过滤器：基于282笔数据分析
# 胜率 < 65% 或 RSI/VIX 组合高风险 → 降低评分或拒绝
# ============================================================
def check_entry_filter(rsi, vix, otm_pct):
    """
    返回: (can_enter, filter_level, reason)
    can_enter: True/False
    filter_level: 'normal' / 'reduced' / 'reject'
    reason: str
    """
    # 硬性拒绝：RSI 极端值
    if rsi is not None:
        if rsi < 25 or rsi > 75:
            return False, 'reject', f'RSI={rsi:.0f} 极端值，拒绝'
        # 高波动 + RSI极端 → 拒绝
        if vix is not None and vix > 30 and (rsi < 30 or rsi > 70):
            return False, 'reject', f'VIX={vix:.0f}+RSI={rsi:.0f} 高风险组合，拒绝'
        # VIX > 30 尾部风险太大 → 拒绝
        if vix > 30:
            return False, 'reject', f'VIX={vix:.0f}>30 尾部风险太大，拒绝'

    # OTM 不足 5% → 降低评分（历史上胜率仅33%）
    if otm_pct is not None and -5 < otm_pct < 0:
        return True, 'reduced', f'OTM={abs(otm_pct):.1f}% 过低(建议>5%)，降低评分'

    # 警告组合：RSI 30-40 + VIX>25（历史上胜率57%）
    if rsi is not None and vix is not None:
        if 25 <= rsi < 40 and vix > 25:
            return True, 'reduced', f'RSI={rsi:.0f}+VIX={vix:.0f} 高波动组合，降低仓位'

    return True, 'normal', '通过'


# OTM 最小阈值（%），低于此值直接跳过
MIN_OTM_PCT = 5.0  # 历史上 OTM<5% 胜率仅33%，强制要求 ≥5%


# ==================== 策略计算函数 ====================

def calculate_bull_put_spread(price, iv, short_strike, long_strike, days,
                               ticker=None, options_data=None):
    """Bull Put Spread: 卖高行权价 Put，买低行权价 Put（看不跌）"""
    premium = 0
    if options_data and 'puts' in options_data:
        puts_df = pd.DataFrame(options_data['puts'])
        short_row = puts_df[puts_df['strike'] == short_strike]
        long_row = puts_df[puts_df['strike'] == long_strike]
        if not short_row.empty and not long_row.empty:
            s_bid = float(short_row.iloc[0]['bid']); s_ask = float(short_row.iloc[0]['ask'])
            l_bid = float(long_row.iloc[0]['bid']); l_ask = float(long_row.iloc[0]['ask'])
            s_last = float(short_row.iloc[0].get('lastPrice', 0))
            l_last = float(long_row.iloc[0].get('lastPrice', 0))
            if s_bid > 0 and s_ask > 0 and l_bid > 0 and l_ask > 0:
                short_prem = (s_bid + s_ask) / 2
                long_prem = (l_bid + l_ask) / 2
            elif s_last > 0 and l_last > 0:
                short_prem = s_last; long_prem = l_last
            else:
                short_prem = long_prem = 0
            premium = (short_prem - long_prem) * 100
    if premium <= 0:
        iv_adj = iv / 100
        T = max(days / 365, 1 / 365)
        from_black = False
        if GREEKS_AVAILABLE:
            try:
                sp = BlackScholesPut(S=price, K=short_strike, T=T, r=0.05, sigma=iv_adj)
                lp = BlackScholesPut(S=price, K=long_strike, T=T, r=0.05, sigma=iv_adj)
                premium = (sp.price - lp.price) * 100
                from_black = True
            except Exception:
                pass
        if not from_black:
            sp = calculate_option_price(price, short_strike, iv, days, 'put')
            lp = calculate_option_price(price, long_strike, iv, days, 'put')
            premium = (sp - lp) * 100
    width = short_strike - long_strike
    max_loss = (width * 100) - premium
    max_profit = premium
    delta, gamma = calculate_delta_gamma(price, short_strike, iv, days, 'put')
    liq_score = calculate_liquidity_score_from_options(
        pd.DataFrame(options_data['puts']) if options_data and 'puts' in options_data else None,
        short_strike, 'put')
    safety = calculate_safety_distance(price, short_strike, long_strike, premium, 'Bull_Put')
    theta = calculate_theta(price, short_strike, iv, days, 'put')
    theta_score = calculate_theta_score(theta, premium, days, iv)
    rr = calculate_real_rr_ratio(max_profit, max_loss)
    return {
        'type': 'Bull_Put',
        'short_strike': short_strike,
        'long_strike': long_strike,
        'premium': premium,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'width': width,
        'rr_ratio': rr,
        'liquidity_score': liq_score,
        'safety': safety,
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'theta_score': theta_score,
    }


def calculate_bull_call_spread(price, iv, long_strike, short_strike, days,
                                  ticker=None, options_data=None):
    """Bull Call Spread: 买低行权价 Call，卖高行权价 Call（看不涨太快）"""
    premium = 0
    if options_data and 'calls' in options_data:
        calls_df = pd.DataFrame(options_data['calls'])
        long_row = calls_df[calls_df['strike'] == long_strike]
        short_row = calls_df[calls_df['strike'] == short_strike]
        if not long_row.empty and not short_row.empty:
            lc_bid = float(long_row.iloc[0]['bid']); lc_ask = float(long_row.iloc[0]['ask'])
            sc_bid = float(short_row.iloc[0]['bid']); sc_ask = float(short_row.iloc[0]['ask'])
            lc_last = float(long_row.iloc[0].get('lastPrice', 0))
            sc_last = float(short_row.iloc[0].get('lastPrice', 0))
            if lc_bid > 0 and lc_ask > 0 and sc_bid > 0 and sc_ask > 0:
                long_prem = (lc_bid + lc_ask) / 2
                short_prem = (sc_bid + sc_ask) / 2
            elif lc_last > 0 and sc_last > 0:
                long_prem = lc_last; short_prem = sc_last
            else:
                long_prem = short_prem = 0
            premium = (short_prem - long_prem) * 100
    if premium <= 0:
        iv_adj = iv / 100
        T = max(days / 365, 1 / 365)
        from_black = False
        if GREEKS_AVAILABLE:
            try:
                lc = BlackScholesCall(S=price, K=long_strike, T=T, r=0.05, sigma=iv_adj)
                sc = BlackScholesCall(S=price, K=short_strike, T=T, r=0.05, sigma=iv_adj)
                premium = (sc.price - lc.price) * 100
                from_black = True
            except Exception:
                pass
        if not from_black:
            lc = calculate_option_price(price, long_strike, iv, days, 'call')
            sc = calculate_option_price(price, short_strike, iv, days, 'call')
            premium = (sc - lc) * 100
    width = short_strike - long_strike
    max_profit = (width * 100) - abs(premium)
    max_loss = abs(premium)
    delta, gamma = calculate_delta_gamma(price, long_strike, iv, days, 'call')
    liq_score = calculate_liquidity_score_from_options(
        pd.DataFrame(options_data['calls']) if options_data and 'calls' in options_data else None,
        short_strike, 'call')
    safety = calculate_safety_distance(price, short_strike, long_strike, premium, 'Bull_Call')
    theta = calculate_theta(price, short_strike, iv, days, 'call')
    theta_score = calculate_theta_score(theta, abs(premium), days, iv)
    rr = calculate_real_rr_ratio(max_profit, max_loss)
    return {
        'type': 'Bull_Call',
        'long_strike': long_strike,
        'short_strike': short_strike,
        'premium': premium,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'width': width,
        'rr_ratio': rr,
        'liquidity_score': liq_score,
        'safety': safety,
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'theta_score': theta_score,
    }


def calculate_short_put(price, iv, strike, days, ticker=None, options_data=None):
    """裸卖 Put（高风险）"""
    premium = 0
    if options_data and 'puts' in options_data:
        puts_df = pd.DataFrame(options_data['puts'])
        row = puts_df[puts_df['strike'] == strike]
        if not row.empty:
            bid = float(row.iloc[0]['bid'])
            ask = float(row.iloc[0]['ask'])
            last = float(row.iloc[0].get('lastPrice', 0))
            # bid/ask 为 0 时 fallback 到 lastPrice
            if bid > 0 and ask > 0:
                premium = (bid + ask) / 2 * 100
            elif last > 0:
                premium = last * 100
    if premium <= 0:
        iv_adj = iv / 100
        T = max(days / 365, 1 / 365)
        if GREEKS_AVAILABLE:
            try:
                p = BlackScholesPut(S=price, K=strike, T=T, r=0.05, sigma=iv_adj)
                premium = p.price * 100
            except Exception:
                premium = calculate_option_price(price, strike, iv, days, 'put') * 100
        else:
            premium = calculate_option_price(price, strike, iv, days, 'put') * 100
    max_profit = premium
    max_loss = (strike - price + premium / 100) * 100 if price < strike else premium
    if max_loss < 0:
        max_loss = abs((price - strike) * 100) + premium
    width = strike
    delta, gamma = calculate_delta_gamma(price, strike, iv, days, 'put')
    liq_score = calculate_liquidity_score_from_options(
        pd.DataFrame(options_data['puts']) if options_data and 'puts' in options_data else None,
        strike, 'put')
    safety = calculate_safety_distance(price, strike, 0, premium, 'Short_Put')
    theta = calculate_theta(price, strike, iv, days, 'put')
    theta_score = calculate_theta_score(theta, premium, days, iv)
    rr = calculate_real_rr_ratio(max_profit, max_loss)
    downside_s = calculate_downside_score(price, strike, iv)
    return {
        'type': 'Short_Put',
        'strike': strike,
        'premium': premium,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'width': width,
        'rr_ratio': rr,
        'liquidity_score': liq_score,
        'safety': safety,
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'theta_score': theta_score,
        'downside_score': downside_s,
    }


def calculate_iron_condor(price, iv, put_short_strike, put_long_strike,
                            call_short_strike, call_long_strike, days,
                            ticker=None, options_data=None):
    """Iron Condor: 卖 Put + 买 Put + 卖 Call + 买 Call"""
    put_side = calculate_bull_put_spread(
        price, iv, put_short_strike, put_long_strike, days, ticker, options_data)
    call_side = calculate_bull_call_spread(
        price, iv, call_short_strike - (call_long_strike - call_short_strike),
        call_long_strike, days, ticker, options_data)
    # Merge call side into put side
    result = put_side.copy()
    result['type'] = 'Iron_Condor'
    result['put_short_strike'] = put_short_strike   # 存储原始参数
    result['put_long_strike'] = put_long_strike
    result['short_put'] = put_short_strike
    result['long_put'] = put_long_strike
    result['call_short_strike'] = call_short_strike
    result['call_long_strike'] = call_long_strike
    result['call_short_delta'] = call_side.get('delta', 0)
    result['call_gamma'] = call_side.get('gamma', 0)
    return result


# ==================== 主入口 ====================

def calculate_strategies_from_ctx(symbol, ctx):
    """
    统一策略计算入口。接收 ctx 数据，返回结构化策略列表。

    ctx 格式:
    {
        'price': float,
        'iv': float,
        'vix': float,
        'vix_signal': str,
        'sentiment': str,
        'option_chains': [{'date': str, 'days': int, 'calls': [], 'puts': []}, ...]
    }
    返回:
    {
        'Bull_Put': [...],   # 最多5条
        'Bull_Call': [...],
        'Short_Put': [...],
        'Iron_Condor': [...]
    }
    """
    price = ctx.get('price')
    iv = ctx.get('iv', 35)
    vix = ctx.get('vix', 20)
    vix_signal = ctx.get('vix_signal', 'YELLOW')
    vix_ma = ctx.get('vix_ma10', vix)
    sentiment = ctx.get('sentiment', 'neutral')
    option_chains = ctx.get('option_chains', [])

    threshold = get_dynamic_threshold(vix_signal, iv)
    sentiment_map = {"bullish": 80, "neutral": 50, "bearish": 20}
    sentiment_score = sentiment_map.get(sentiment, 50)

    all_results = {
        'Bull_Put': [],
        'Bull_Call': [],
        'Short_Put': [],
        'Iron_Condor': []
    }

    for chain in option_chains:
        days = chain.get('days', 0)
        if days <= 0 or days > 7:
            continue
        expiry_short = chain.get('date', '')[5:] if chain.get('date') else ''
        options_data = {'calls': chain.get('calls', []), 'puts': chain.get('puts', [])}

        # === Bull Put Spread (VIX 信号差异化) ===
        p = VIX_STRIKE_PARAMS[vix_signal]["Bull_Put"]
        short_ratio = p["short_ratio"]
        spread_w = p["spread_width"]
        # 固定 short_ratio 生成基准，再微调生成多条
        for delta_pct in [-0.04, -0.02, 0, 0.02, 0.04]:
            sp_ratio = short_ratio + delta_pct
            lp_ratio = sp_ratio - spread_w / price
            sp = round(price * sp_ratio / 2.5) * 2.5
            lp = round(price * lp_ratio / 2.5) * 2.5
            if lp <= 0 or lp >= sp:
                continue
            bp = calculate_bull_put_spread(price, iv, sp, lp, days, None, options_data)
            bp['days'] = days
            bp['expiry'] = expiry_short
            bp['strike_str'] = f"卖${sp:.0f}/买${lp:.0f}"
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = \
                calculate_full_score(bp, 'Bull_Put', price, days, iv, vix_signal, sentiment)
            bp['score'] = score
            bp['rr_ratio'] = rr
            bp['liquidity'] = liq
            bp['safety'] = safety
            bp['theta_score'] = theta_s
            bp['iv_score'] = iv_s
            bp['delta_score'] = delta_s
            bp['gamma_score'] = gamma_s
            bp['downside_score'] = downside_s
            safety_dist = calculate_safety_distance(price, sp, lp, bp['premium'], 'Bull_Put')
            bp['safety_distance'] = safety_dist
            bp['decision'] = ("✅开仓" if score >= threshold + 15
                              else "🟡试探" if score >= threshold
                              else "🔴禁止")
            all_results['Bull_Put'].append(bp)

        # === Bull Call Spread (VIX 信号差异化) ===
        c = VIX_STRIKE_PARAMS[vix_signal]["Bull_Call"]
        short_ratio_c = c["short_ratio"]
        spread_w_c = c["spread_width"]
        for delta_pct in [-0.04, -0.02, 0, 0.02, 0.04]:
            sc_ratio = short_ratio_c + delta_pct
            lc_ratio = sc_ratio - spread_w_c / price
            lc = round(price * lc_ratio / 2.5) * 2.5
            sc = round(price * sc_ratio / 2.5) * 2.5
            if lc <= 0 or lc <= sc:
                continue
            bc = calculate_bull_call_spread(price, iv, lc, sc, days, None, options_data)
            bc['days'] = days
            bc['expiry'] = expiry_short
            bc['strike_str'] = f"买${lc:.0f}/卖${sc:.0f}"
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = \
                calculate_full_score(bc, 'Bull_Call', price, days, iv, vix_signal, sentiment)
            bc['score'] = score
            bc['rr_ratio'] = rr
            bc['liquidity'] = liq
            bc['safety'] = safety
            bc['theta_score'] = theta_s
            bc['iv_score'] = iv_s
            bc['delta_score'] = delta_s
            bc['gamma_score'] = gamma_s
            bc['downside_score'] = downside_s
            safety_dist = calculate_safety_distance(price, sc, lc, bc['premium'], 'Bull_Call')
            bc['safety_distance'] = safety_dist
            bc['decision'] = ("✅开仓" if score >= threshold + 15
                              else "🟡试探" if score >= threshold
                              else "🔴禁止")
            all_results['Bull_Call'].append(bc)

        # === Short Put (VIX 信号差异化) ===
        sp_params = VIX_STRIKE_PARAMS[vix_signal]["Short_Put"]
        sp_base_ratio = sp_params["short_ratio"]
        for delta_pct in [-0.06, -0.04, -0.02, 0, 0.02, 0.04]:
            sp_ratio = sp_base_ratio + delta_pct
            sp_strike = round(price * sp_ratio / 2.5) * 2.5
            if sp_strike >= price:
                continue
            sp_ = calculate_short_put(price, iv, sp_strike, days, None, options_data)
            sp_['days'] = days
            sp_['expiry'] = expiry_short
            sp_['strike_str'] = f"卖${sp_strike:.0f}"
            score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = \
                calculate_full_score(sp_, 'Short_Put', price, days, iv, vix_signal, sentiment)
            sp_['score'] = score
            sp_['rr_ratio'] = rr
            sp_['liquidity'] = liq
            sp_['safety'] = safety
            sp_['theta_score'] = theta_s
            sp_['iv_score'] = iv_s
            sp_['delta_score'] = delta_s
            sp_['gamma_score'] = gamma_s
            sp_['downside_score'] = downside_s
            safety_dist = calculate_safety_distance(price, sp_strike, 0, sp_['premium'], 'Short_Put')
            sp_['safety_distance'] = safety_dist
            sp_['decision'] = ("✅开仓" if score >= threshold + 15
                              else "🟡试探" if score >= threshold
                              else "🔴禁止")
            all_results['Short_Put'].append(sp_)

        # === Iron Condor (VIX 信号差异化) ===
        ic_params = VIX_STRIKE_PARAMS[vix_signal]["Iron_Condor"]
        ic_put_r = ic_params["put_short_ratio"]
        ic_call_r = ic_params["call_short_ratio"]
        ic_w = ic_params["spread_width"]
        ic_sp = round(price * ic_put_r / 2.5) * 2.5
        ic_lp = round(price * (ic_put_r - ic_w / price) / 2.5) * 2.5
        ic_sc = round(price * ic_call_r / 2.5) * 2.5
        ic_lc = round(price * (ic_call_r + ic_w / price) / 2.5) * 2.5
        ic = calculate_iron_condor(price, iv, ic_sp, ic_lp, ic_sc, ic_lc, days, None, options_data)
        ic['days'] = days
        ic['expiry'] = expiry_short
        ic['strike_str'] = f"卖PUT{ic_sp:.0f}/买PUT{ic_lp:.0f}|卖CALL{ic_sc:.0f}/买CALL{ic_lc:.0f}"
        score, rr, liq, safety, theta_s, iv_s, delta, gamma, delta_s, gamma_s, downside_s = \
            calculate_full_score(ic, 'Iron_Condor', price, days, iv, vix_signal, sentiment)
        ic['score'] = score
        ic['rr_ratio'] = rr
        ic['liquidity'] = liq
        ic['safety'] = safety
        ic['theta_score'] = theta_s
        ic['iv_score'] = iv_s
        ic['delta_score'] = delta_s
        ic['gamma_score'] = gamma_s
        ic['downside_score'] = downside_s
        safety_dist = calculate_safety_distance(price, ic_sp, ic_lp, ic['premium'], 'Iron_Condor')
        ic['safety_distance'] = safety_dist
        ic['decision'] = ("✅开仓" if score >= threshold + 15
                          else "🟡试探" if score >= threshold
                          else "🔴禁止")
        all_results['Iron_Condor'].append(ic)

    # 优先 3 天滚动窗口（3天、6天），其次 7 天内其他
    # 同一类型策略：优先 preferred_days，其次按分数
    preferred_days_set = {3, 6, 7}

    def sort_key(s):
        days = s.get('days', 0)
        premium = s.get('premium', 0)
        # 权利金不在 100-200 区间的降低优先级
        in_premium_range = 100 <= premium <= 200
        is_preferred_day = days in preferred_days_set
        score = s.get('score', 0)
        #  return (not is_preferred_day, -score if not in_premium_range else score)
        # 优先：preferred_day + in_range > preferred_day + out_range > non-preferred
        return (
            0 if is_preferred_day else 1,           # preferred 先
            0 if in_premium_range else 1,           # 权利金区间内优先
            -s.get('score', 0)                      # 分数高的排前
        )

    for stype in all_results:
        all_results[stype].sort(key=sort_key)
        # 取前5，但保留所有 preferred_day 的策略
        preferred = [s for s in all_results[stype] if s.get('days') in preferred_days_set]
        non_preferred = [s for s in all_results[stype] if s.get('days') not in preferred_days_set]
        # 权利金过滤：preferred 保留全部，non_preferred 只保留 100-200
        filtered = preferred + [s for s in non_preferred if 100 <= s.get('premium', 0) <= 200]
        all_results[stype] = filtered[:5]


    # ============================================================
    # 胜率预测（查表 + ML 模型）
    # ============================================================
    wr_mod = _get_win_rate()
    if wr_mod:
        try:
            wr_mod.load_models()
        except Exception:
            pass
    else:

    rsi = ctx.get('rsi')

    for stype, strategies in all_results.items():
        filtered_strategies = []
        for s in strategies:
            short_strike = s.get('short_strike') or s.get('strike', price)
            otm_pct = (short_strike - price) / price * 100 if price else None
            can_enter, level, reason = check_entry_filter(rsi, vix, otm_pct)

            if level == 'reject':
                s['decision'] = '🔴禁止'
                s['filter_reason'] = reason
                s['score'] = 0
                filtered_strategies.append(s)
                continue

            if level == 'reduced':
                # 评分降低 30%
                original_score = s.get('score', 0)
                reduced_score = original_score * 0.7
                s['score'] = reduced_score
                s['filter_reason'] = reason
                # 重新计算 decision
                if reduced_score >= threshold + 15:
                    s['decision'] = '🟡试探（减仓）'
                elif reduced_score >= threshold:
                    s['decision'] = '🟡试探（减仓）'
                else:
                    s['decision'] = '🔴禁止'
                filtered_strategies.append(s)
                continue

            # normal
            s['filter_reason'] = '通过'
            filtered_strategies.append(s)

        # 给每个策略加上胜率预测
        if wr_mod:
            for s in filtered_strategies:
                ss = s.get('short_strike') or s.get('strike', price)
                otm = (ss - price) / price * 100 if price else -5
                trend = ctx.get('trend', '下跌')
                stype_name = s.get('type', stype)
                # 映射 strategy type
                if 'Put' in stype_name or 'put' in stype_name:
                    strat_name = 'ShortPut' if stype_name == 'Short_Put' else 'BullPutSpread'
                else:
                    strat_name = 'ShortPut'
                wr = wr_mod.predict_win_rate(
                    rsi=rsi, vix=vix, otm_pct=otm,
                    trend=trend, strategy_type=strat_name,
                    holding_days=s.get('days', 14)
                )
                s['predicted_win_rate'] = wr['win_rate']
                s['win_rate_confidence'] = wr['confidence']
                s['win_rate_n'] = wr['n']
                s['win_rate_ci'] = (wr['ci_low'], wr['ci_high']) if wr['ci_low'] else None
                s['win_rate_avg_pnl'] = wr['avg_pnl']

        all_results[stype] = filtered_strategies

    return all_results
