#!/usr/bin/env python3
"""
OptionAgent - 期权分析代理
支持多种期权策略 + 多维度评分 + ML波动率预测
"""

import os
import sys
import subprocess
import tempfile
import warnings
warnings.filterwarnings('ignore')
import json
from datetime import datetime, timedelta

# strategy_engine 在 TSLA期权策略 目录，加入 path
_STRATEGY_ENGINE_DIR = '/root/.openclaw/workspace/quant/TSLA期权策略'
if _STRATEGY_ENGINE_DIR not in sys.path:
    sys.path.insert(0, _STRATEGY_ENGINE_DIR)

# 清除代理环境变量，让 yfinance 自己处理
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(var, None)

import yfinance as yf
import numpy as np
from scipy.stats import norm
import requests

# ============ 辅助函数 ============

def get_vix():
    """获取VIX指数"""
    try:
        vix = yf.Ticker("^VIX")
        vix_data = vix.history(period='1d')
        if not vix_data.empty:
            return float(vix_data['Close'].iloc[-1])
    except:
        pass
    return None

def get_stock_sentiment(symbol):
    """获取股票情绪"""
    try:
        url = "https://finnhub.io/api/v1/stock/social-sentiment"
        params = {'symbol': symbol, 'token': 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            reddit = data.get('reddit', {})
            score = reddit.get('avgSentiment', 0)
            if score > 0.2:
                return 'bullish'
            elif score < -0.2:
                return 'bearish'
    except:
        pass
    return 'neutral'

def calculate_greeks(S, K, T, r=0.05, iv=0.3, option_type='put'):
    """计算希腊字母"""
    if T <= 0:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}
    d1 = (np.log(S / K) + (iv ** 2 / 2) * T) / (iv * np.sqrt(T))
    d2 = d1 - iv * np.sqrt(T)
    if option_type == 'call':
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1
    gamma = norm.pdf(d1) / (S * iv * np.sqrt(T))
    theta = (-S * norm.pdf(d1) * iv / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100
    return {'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega}

def calculate_liquidity(options_df, strike, option_type='put'):
    """计算流动性分数 (0-10)"""
    try:
        opt = options_df[options_df['strike'] == strike]
        if not opt.empty:
            bid = opt['bid'].iloc[0]
            ask = opt['ask'].iloc[0]
            if bid > 0 and ask > 0:
                spread = (ask - bid) / ((ask + bid) / 2)
                if spread < 0.01:
                    return 10
                elif spread < 0.02:
                    return 8
                elif spread < 0.05:
                    return 6
                else:
                    return 4
    except:
        pass
    return 5

def calculate_safety_distance(price, strike, premium, direction='put'):
    """计算安全距离"""
    if direction == 'put':
        return (price - strike) / price * 100
    else:
        return (strike - price) / price * 100

def get_stock_price(symbol):
    """获取股票价格"""
    stock = yf.Ticker(symbol)
    try:
        return float(stock.history(period='1d')['Close'].iloc[-1])
    except:
        return None

def get_option_chain(symbol):
    """获取期权链"""
    stock = yf.Ticker(symbol)
    try:
        expirations = stock.options
        if not expirations:
            return None, None, None
        opt = stock.option_chain(expirations[0])
        return opt.calls, opt.puts, expirations[0]
    except:
        return None, None, None

def score_strategies(price, calls, puts, symbol, expiry='TSLA', vix_override=None, sentiment_override=None):
    """
    评分多种期权策略 - 多维度

    Args:
        vix_override: 如果传入，则跳过 get_vix() 调用（用于统一数据层）
        sentiment_override: 如果传入，则跳过 get_stock_sentiment() 调用
    """
    strategies = []
    if calls is None or puts is None:
        return strategies

    vix = vix_override if vix_override is not None else get_vix()
    sentiment = sentiment_override if sentiment_override is not None else get_stock_sentiment(symbol)

    vix_signal = 'GREEN'
    if vix:
        if vix > 0.25:
            vix_signal = 'RED'
        elif vix < 0.15:
            vix_signal = 'YELLOW'

    otm_puts = puts[puts['strike'] < price].sort_values('strike', ascending=False)
    otm_calls = calls[calls['strike'] > price].sort_values('strike')

    # 1. Bull Put Spread
    for i in range(min(5, len(otm_puts) - 1)):
        short = otm_puts.iloc[i]
        long = otm_puts.iloc[i + 1]
        credit = (short.get('bid', 0) - long.get('ask', 0)) * 100
        width = short['strike'] - long['strike']
        max_loss = (width * 100) - credit
        if credit > 0 and max_loss > 0:
            rr = credit / max_loss
            liquidity = (calculate_liquidity(puts, short['strike'], 'put') + calculate_liquidity(puts, long['strike'], 'put')) / 2
            safety = calculate_safety_distance(price, short['strike'], credit, 'put')
            sentiment_boost = 1.2 if sentiment == 'bullish' else 0.9 if sentiment == 'bearish' else 1.0
            vix_boost = 1.3 if vix_signal == 'GREEN' else 1.0
            score = (rr * 80 + liquidity * 2 + safety * 0.5) * sentiment_boost * vix_boost
            if rr > 0.1:
                strategies.append({
                    'type': 'Bull Put Spread',
                    'short_strike': short['strike'],
                    'long_strike': long['strike'],
                    'expiry': expiry,
                    'credit': round(credit, 2),
                    'max_loss': round(max_loss, 2),
                    'rr_ratio': round(rr, 2),
                    'liquidity': liquidity,
                    'safety': round(safety, 1),
                    'score': round(score, 1)
                })

    # 2. Bull Call Spread
    itm_calls = calls[calls['strike'] <= price].sort_values('strike', ascending=False)
    for i in range(min(3, len(itm_calls))):
        for j in range(min(3, len(otm_calls))):
            long_call = itm_calls.iloc[i]
            short_call = otm_calls.iloc[j]
            if long_call['strike'] < short_call['strike']:
                debit = (long_call.get('ask', 0) - short_call.get('bid', 0)) * 100
                width = short_call['strike'] - long_call['strike']
                max_profit = (width * 100) - debit
                if debit > 0 and max_profit > 0:
                    rr = max_profit / debit
                    liquidity = (calculate_liquidity(calls, long_call['strike'], 'call') + calculate_liquidity(calls, short_call['strike'], 'call')) / 2
                    safety = calculate_safety_distance(price, long_call['strike'], debit, 'call')
                    sentiment_boost = 1.2 if sentiment == 'bullish' else 0.9 if sentiment == 'bearish' else 1.0
                    vix_boost = 1.3 if vix_signal == 'GREEN' else 1.0
                    score = (rr * 100 + liquidity * 2 + safety * 0.5) * sentiment_boost * vix_boost
                    if rr > 0.1:
                        strategies.append({
                            'type': 'Bull Call Spread',
                            'long_strike': long_call['strike'],
                            'short_strike': short_call['strike'],
                            'expiry': expiry,
                            'debit': round(debit, 2),
                            'max_profit': round(max_profit, 2),
                            'rr_ratio': round(rr, 2),
                            'liquidity': liquidity,
                            'safety': round(safety, 1),
                            'score': round(score, 1)
                        })

    # 3. Short Put
    for i in range(min(5, len(otm_puts))):
        put = otm_puts.iloc[i]
        premium = put.get('bid', 0) * 100
        if premium > 10:
            width = put['strike'] - (premium / 100)
            max_loss = width * 100
            if max_loss > 0:
                rr = premium / max_loss
                liquidity = calculate_liquidity(puts, put['strike'], 'put')
                safety = calculate_safety_distance(price, put['strike'], premium, 'put')
                sentiment_boost = 1.2 if sentiment == 'bullish' else 0.9 if sentiment == 'bearish' else 1.0
                score = (rr * 90 + liquidity * 2 + safety * 0.5) * sentiment_boost
                if rr > 0.1:
                    strategies.append({
                        'type': 'Short Put',
                        'strike': put['strike'],
                        'expiry': expiry,
                        'premium': round(premium, 2),
                        'max_loss': round(max_loss, 2),
                        'rr_ratio': round(rr, 2),
                        'liquidity': liquidity,
                        'safety': round(safety, 1),
                        'score': round(score, 1)
                    })

    # 4. Iron Condor
    for i in range(min(3, len(otm_puts) - 1)):
        for j in range(min(3, len(otm_calls) - 1)):
            sp = otm_puts.iloc[i]
            lp = otm_puts.iloc[i + 1]
            sc = otm_calls.iloc[j]
            lc = otm_calls.iloc[j + 1]
            credit = ((sp.get('bid', 0) - lp.get('ask', 0)) + (sc.get('bid', 0) - lc.get('ask', 0))) * 100
            width = max(sp['strike'] - lp['strike'], lc['strike'] - sc['strike'])
            max_loss = (width * 100) - credit
            if credit > 10 and max_loss > 0:
                rr = credit / max_loss
                liquidity = (calculate_liquidity(puts, sp['strike'], 'put') + calculate_liquidity(calls, sc['strike'], 'call')) / 2
                put_safety = calculate_safety_distance(price, sp['strike'], credit, 'put')
                call_safety = calculate_safety_distance(price, sc['strike'], credit, 'call')
                safety = min(put_safety, call_safety)
                vix_boost = 1.5 if vix_signal == 'GREEN' else 1.0 if vix_signal == 'YELLOW' else 0.8
                score = (rr * 60 + liquidity * 2 + safety * 0.3) * vix_boost
                if rr > 0.1:
                    strategies.append({
                        'type': 'Iron Condor',
                        'short_put': sp['strike'],
                        'long_put': lp['strike'],
                        'short_call': sc['strike'],
                        'long_call': lc['strike'],
                        'expiry': expiry,
                        'credit': round(credit, 2),
                        'max_loss': round(max_loss, 2),
                        'rr_ratio': round(rr, 2),
                        'liquidity': liquidity,
                        'safety': round(safety, 1),
                        'vix': vix,
                        'vix_signal': vix_signal,
                        'sentiment': sentiment,
                        'score': round(score, 1)
                    })

    strategies.sort(key=lambda x: x['score'], reverse=True)
    from collections import defaultdict
    by_type = defaultdict(list)
    for s in strategies:
        by_type[s['type']].append(s)
    result = []
    for stype in by_type:
        if by_type[stype]:
            result.append(by_type[stype][0])
    result.sort(key=lambda x: x['score'], reverse=True)
    return result


# ============ OptionAgent ============

class OptionAgent:
    """期权分析代理（支持 ML 波动率预测）"""

    def __init__(self):
        self.name = "OptionAgent"
        self.v6_script = '/root/.openclaw/workspace/quant/TSLA期权策略/vertical_spread_v6.py'
        self._ml_signal = None  # ML 信号缓存

    def _get_ml_signal(self, symbol='TSLA', ctx=None):
        """
        获取 ML 波动率预测信号（带缓存，避免重复计算）。

        Args:
            symbol: 股票代码
            ctx: 统一数据上下文（可选）。传入则复用已有数据，不再独立拉 yfinance。
        """
        if self._ml_signal is not None:
            return self._ml_signal

        try:
            from ml_predictor import MLSignalGenerator, VolatilityPredictor
            predictor = VolatilityPredictor()
            loaded = predictor.load()
            if loaded:
                gen = MLSignalGenerator(predictor)
                # 优先用 ctx 复用已有数据，避免重复调 yfinance
                self._ml_signal = gen.generate(symbol, ctx=ctx)
                return self._ml_signal
        except Exception as e:
            print(f"[OptionAgent] ML模块加载失败: {e}", flush=True)

        # Fallback: 无 ML 时用 VIX-only 信号
        try:
            from ml_predictor import FeatureEngineer
            fe = FeatureEngineer()
            result = fe.get_latest_features(symbol)
            if result is None or len(result) < 3:
                features, price, vix = None, None, None
            else:
                features, price, vix = result[0], result[1], result[2]
            # 安全地计算 vix_signal
            if vix is not None and isinstance(vix, (int, float)):
                if vix > 0.30:
                    vix_signal = 'RED'
                elif vix < 0.18:
                    vix_signal = 'YELLOW'
                else:
                    vix_signal = 'GREEN'
            else:
                vix_signal = 'GREEN'  # VIX 不可用时默认 GREEN
                vix = None
            self._ml_signal = {
                'symbol': symbol,
                'price': price,
                'vix': vix,
                'vix_signal': vix_signal,
                'ml_enabled': False,
                'ml_predicted_vol': None,
                'ml_regime': None,
                'action': 'unknown',
                'reason': 'ML模型未加载，基于VIX判断'
            }
        except Exception as e:
            print(f"[OptionAgent] VIX fallback 获取失败: {e}", flush=True)
            self._ml_signal = {
                'symbol': symbol,
                'price': None,
                'vix': None,
                'vix_signal': 'GREEN',
                'ml_enabled': False,
                'ml_predicted_vol': None,
                'ml_regime': None,
                'action': 'unknown',
                'reason': f'VIX数据获取异常: {str(e)[:50]}'
            }

        return self._ml_signal

    def _get_strategies_from_multi_v2(self, symbol='TSLA', ctx=None):
        """
        直接调用 strategy_engine 计算策略（不走网络请求）。
        ctx 来自 UnifiedDataFetcher，包含 price/iv/vix/option_chains。
        返回: list[dict] 与 score_strategies 输出格式兼容
        """
        try:
            from strategy_engine import calculate_strategies_from_ctx

            if ctx is None:
                return []

            # 构建 engine 需要的 ctx 格式
            vix_val = ctx.get('vix')
            vix_signal = self._vix_to_signal(vix_val)
            price = ctx.get('price')
            iv = ctx.get('iv', 35)

            engine_ctx = {
                'price': price,
                'iv': iv,
                'vix': vix_val,
                'vix_signal': vix_signal,
                'vix_ma10': ctx.get('vix_ma10', vix_val),
                'sentiment': 'neutral',
                'option_chains': ctx.get('option_chains', [])
            }

            all_results = calculate_strategies_from_ctx(symbol, engine_ctx)

            strategies = []
            TYPE_MAP = {
                'Iron_Condor': 'Iron Condor',
                'Bull_Put': 'Bull Put Spread',
                'Bull_Call': 'Bull Call Spread',
                'Short_Put': 'Short Put',
            }
            for stype_name, stype_list in all_results.items():
                for s in stype_list[:3]:
                    if stype_name == 'Iron_Condor':
                        s_out = {
                            'type': 'Iron Condor',
                            'score': s.get('score', 0),
                            'rr_ratio': s.get('rr_ratio', 0),
                            'short_strike': s.get('put_short_strike'),
                            'long_strike': s.get('put_long_strike'),
                            'short_put': s.get('put_short_strike'),
                            'long_put': s.get('put_long_strike'),
                            'short_call': s.get('call_short_strike'),
                            'long_call': s.get('call_long_strike'),
                            'credit': s.get('premium'),
                            'max_loss': s.get('max_loss'),
                            'max_profit': s.get('max_profit'),
                            'theta': s.get('theta'),
                            'days_to_expiry': s.get('days'),
                            'actual_expiry_date': s.get('expiry'),
                            'decision': s.get('decision', ''),
                        }
                    else:
                        s_out = {
                            'type': TYPE_MAP.get(stype_name, stype_name),
                            'score': s.get('score', 0),
                            'rr_ratio': s.get('rr_ratio', 0),
                            'short_strike': s.get('short_strike') or s.get('strike'),
                            'long_strike': s.get('long_strike') or s.get('strike'),
                            'credit': s.get('premium'),
                            'max_loss': s.get('max_loss'),
                            'max_profit': s.get('max_profit'),
                            'theta': s.get('theta'),
                            'days_to_expiry': s.get('days'),
                            'actual_expiry_date': s.get('expiry'),
                            'decision': s.get('decision', ''),
                        }
                    strategies.append(s_out)
            return strategies

        except Exception as e:
            print(f"[OptionAgent] strategy_engine 调用失败: {e}", flush=True)
            return []

    def run(self, symbol='TSLA'):
        """标准分析（轻量级）"""
        price = get_stock_price(symbol)
        if not price:
            return {'error': f'无法获取 {symbol} 价格'}

        calls, puts, expiry = get_option_chain(symbol)
        result = {
            'symbol': symbol,
            'price': price,
            'expiry': expiry,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'strategies': []
        }

        if calls is not None and puts is not None:
            result['strategies'] = score_strategies(price, calls, puts, symbol, expiry)

        result['sentiment'] = 'neutral'
        return result

    def run_advanced_with_context(self, symbol='TSLA', ctx=None):
        """
        使用统一数据上下文的生产级期权分析。
        不启动子进程，直接从 ctx['option_chains'] 计算策略。
        数据只通过 UnifiedDataFetcher 访问一次 yfinance。
        """
        # 从 ctx 获取核心数据
        price = ctx.get('price') if ctx else None
        iv = ctx.get('iv') if ctx else None
        vix_val = ctx.get('vix') if ctx else None
        option_chains = ctx.get('option_chains', []) if ctx else []

        # ML 信号（复用 ctx 数据，不再独立调 yfinance）
        ml_signal = self._get_ml_signal(symbol, ctx=ctx)

        if not option_chains:
            return {
                'symbol': symbol,
                'price': price,
                'iv': iv,
                'vix': vix_val,
                'vix_signal': self._vix_to_signal(vix_val),
                'sentiment': 'neutral',
                'sentiment_label': 'neutral',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'strategies': [],
                'source': 'unified_context',
                'ml_signal': self._ml_format(ml_signal),
                'error': '无期权链数据'
            }

        # VIX 信号
        vix_signal = self._vix_to_signal(vix_val)

        # 从 strategy_engine 获取策略（含安全距离过滤的 strike 选择）
        # strategy_engine 已包含完整的评分和决策，无需重复计算
        all_strategies = self._get_strategies_from_multi_v2(symbol, ctx)

        # VIX 动态阈值（与多策略保持一致）
        from strategy_engine import get_dynamic_threshold
        threshold = get_dynamic_threshold(vix_signal, iv)

        # 取每个策略类型的最高分
        from collections import defaultdict
        by_type = defaultdict(list)
        for s in all_strategies:
            by_type[s['type']].append(s)
        best_by_type = [sorted(v, key=lambda x: x['score'], reverse=True)[0]
                        for v in by_type.values()]
        best_by_type.sort(key=lambda x: x['score'], reverse=True)

        # 转换为 run_advanced 兼容格式（直接使用 strategy_engine 的 decision/score，不重复计算）
        strategies_out = []
        for s in best_by_type[:5]:
            # 直接使用 strategy_engine 的决策结果（已在 calculate_strategies_from_ctx 中计算）
            score = s.get('score', 0)
            decision = s.get('decision', '🔴禁止')
            # 仓位：开仓用 score*0.6，试探用 score*0.5，与多策略阈值对齐
            if '✅开仓' in decision:
                position = int(score * 0.6)
            elif '🟡试探' in decision:
                position = int(score * 0.5)
            else:
                position = 0

            # rr_ratio 计算
            if s.get('type') == 'Bull Put Spread':
                rr_ratio = s.get('rr_ratio', 0)
                max_loss = s.get('max_loss', 1)
                width = s.get('short_strike', 0) - s.get('long_strike', 0)
                premium = s.get('credit', 0)
                theta = premium / max(s.get('days_to_expiry', 1), 1)
                capital_efficiency = premium / width * 100 if width > 0 else 0
            elif s.get('type') == 'Iron Condor':
                rr_ratio = s.get('rr_ratio', 0)
                width = max(
                    s.get('short_put', 0) - s.get('long_put', 0),
                    s.get('long_call', 0) - s.get('short_call', 0)
                )
                premium = s.get('credit', 0)
                theta = premium / max(s.get('days_to_expiry', 1), 1)
                capital_efficiency = premium / width * 100 if width > 0 else 0
            else:
                rr_ratio = s.get('rr_ratio', 0)
                width = premium = theta = capital_efficiency = 0

            strategies_out.append({
                'type': s.get('type', ''),
                'strategy_desc': s.get('type', ''),
                'short_strike': s.get('short_strike') or s.get('short_put'),
                'long_strike': s.get('long_strike') or s.get('long_put'),
                'short_call': s.get('short_call'),
                'long_call': s.get('long_call'),
                'width': width,
                'max_profit': s.get('credit', 0),
                'max_loss': s.get('max_loss', 0),
                'premium': s.get('credit', 0),
                'theta': round(theta, 3),
                'days_to_expiry': s.get('days_to_expiry', 0),
                'actual_expiry_date': s.get('actual_expiry_date', ''),
                'iv': iv,
                'price': price,
                'rr_ratio': round(rr_ratio, 2),
                'composite_score': round(score, 1),
                'decision': decision,
                'position': position,
                'capital_efficiency': round(capital_efficiency, 2),
                'threshold_used': threshold,  # 记录本次使用的动态阈值
            })

        result = {
            'symbol': symbol,
            'price': price,
            'iv': iv,
            'vix': vix_val,
            'vix_signal': vix_signal,
            'sentiment': 'neutral',
            'sentiment_label': 'neutral',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'strategies': strategies_out,
            'source': 'unified_context',
            'all_alternatives': all_strategies,
            'ml_signal': self._ml_format(ml_signal),
        }

        # ML 增强覆盖
        if ml_signal.get('ml_enabled'):
            # vix/iv from ctx/mock - do not override from ML cached data
            ml_action = ml_signal.get('action')
            ml_vix_sig = ml_signal.get('vix_signal', 'GREEN')
            if ml_action == 'bull_put_spread' and ml_vix_sig == 'GREEN':
                enhanced = 'bull_put_spread_confirmed'
            elif ml_action == 'wait':
                enhanced = 'wait_confirmed'
            elif ml_action == 'consider':
                enhanced = 'consider_neutral'
            else:
                enhanced = ml_action or 'no_decision'
            result['ml_signal']['enhanced_decision'] = enhanced

        return result

    def run_advanced(self, symbol='TSLA'):
        """生产级分析（vertical_spread_v6 + ML 信号，保留子进程方式）"""
        import subprocess
        import sys

        # 先获取 ML 信号（独立数据源，不依赖 v6）
        ml_signal = self._get_ml_signal(symbol)

        try:
            result_sub = subprocess.run(
                [sys.executable, self.v6_script, '--json'],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )

            for line in result_sub.stdout.splitlines():
                line = line.strip()
                if line.startswith('{'):
                    data = json.loads(line)
                    break
            else:
                raise ValueError('JSON not found in output')

            vix_info = data.get('vix', {})
            all_alts = data.get('alternatives', {})

            sym_data = None
            for k, v in all_alts.items():
                if k.upper() == symbol.upper():
                    sym_data = v
                    break

            if not sym_data:
                raise ValueError(f'{symbol} not in scanned stocks')

            strategies = []
            for r in sym_data:
                sp = r.get('strategy_params', {})
                strategies.append({
                    'type': r.get('strategy_type', '').replace('_', ' ').title(),
                    'strategy_desc': r.get('strategy_desc', ''),
                    'short_strike': sp.get('short_strike'),
                    'long_strike': sp.get('long_strike'),
                    'width': sp.get('width'),
                    'max_profit': sp.get('max_profit_estimate'),
                    'max_loss': sp.get('max_loss_estimate'),
                    'premium': r.get('premium'),
                    'theta': r.get('theta'),
                    'days_to_expiry': r.get('days_to_expiry'),
                    'actual_expiry_date': sp.get('actual_expiry_date'),
                    'iv': r.get('iv'),
                    'price': r.get('price'),
                    'rr_ratio': r.get('strategy_type') == 'Bull_Put_Spread'
                        and (sp.get('max_profit_estimate', 0) / sp.get('max_loss_estimate', 1) if sp.get('max_loss_estimate') else 0)
                        or 0,
                    'composite_score': r.get('composite_score', 0),
                    'decision': r.get('decision', ''),
                    'position': r.get('position', 0),
                    'price_source': sp.get('price_source', ''),
                    'capital_efficiency': r.get('capital_efficiency', 0),
                })

            result = {
                'symbol': symbol,
                'price': sym_data[0].get('price') if sym_data else None,
                'iv': sym_data[0].get('iv') if sym_data else None,
                'vix': vix_info.get('value'),
                'vix_signal': vix_info.get('signal'),
                'sentiment': sym_data[0].get('sentiment') if sym_data else 'neutral',
                'sentiment_label': sym_data[0].get('sentiment', 'neutral'),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'strategies': strategies,
                'source': 'vertical_spread_v6',
                'all_alternatives': sym_data,
                'ml_signal': self._ml_format(ml_signal),
            }

            if ml_signal.get('ml_enabled'):
                # vix/iv from ctx/mock - do not override from ML cached data
                ml_action = ml_signal.get('action')
                vix_sig = ml_signal.get('vix_signal', 'GREEN')
                if ml_action == 'bull_put_spread' and vix_sig == 'GREEN':
                    enhanced_decision = 'bull_put_spread_confirmed'
                elif ml_action == 'wait':
                    enhanced_decision = 'wait_confirmed'
                elif ml_action == 'consider':
                    enhanced_decision = 'consider_neutral'
                else:
                    enhanced_decision = ml_action or 'no_decision'
                result['ml_signal']['enhanced_decision'] = enhanced_decision

            return result

        except subprocess.TimeoutExpired:
            return {'error': '分析超时（>180秒）', 'ml_signal': ml_signal}
        except Exception as e:
            print(f"[OptionAgent] run_advanced failed for {symbol}: {e}, falling back to run()", flush=True)
            result = self.run(symbol)
            result['ml_signal'] = self._ml_format(ml_signal)
            return result

    # ── 内部辅助方法 ──────────────────────────────

    def _vix_to_signal(self, vix, vix_ma=None, deviation=0):
        """使用与 strategy_engine.calculate_vix_signal 一致的逻辑"""
        import pandas as pd
        if vix is None or pd.isna(vix):
            return 'YELLOW'
        # 与 strategy_engine.calculate_vix_signal 保持一致
        if vix > 30:
            return 'RED'
        elif vix < 15:
            return 'GREEN'
        elif vix > 25:
            return 'YELLOW'
        elif vix > 20:
            return 'YELLOW'
        if deviation > 15:
            return 'RED'
        elif deviation < -10:
            return 'GREEN'
        return 'YELLOW'

    def _ml_format(self, ml):
        """统一 ML 信号格式"""
        return {
            'ml_enabled': ml.get('ml_enabled', False),
            'ml_predicted_vol': ml.get('ml_predicted_vol'),
            'ml_vol_adj': ml.get('ml_vol_adj'),
            'ml_regime': ml.get('ml_regime'),
            'ml_action': ml.get('action'),
            'ml_confidence': ml.get('confidence'),
            'ml_reason': ml.get('reason'),
            'ml_vix': ml.get('vix'),
            'ml_vix_signal': ml.get('vix_signal'),
            'ml_price': ml.get('price'),
            # 技术指标（原始字段）
            'rsi_14': ml.get('rsi_14'),
            'rsi_7': ml.get('rsi_7'),
            'macd_signal': ml.get('macd_signal'),
            'macd_diff': ml.get('macd_diff'),
            # 新增独立信号
            'divergence': ml.get('divergence'),
            'mispricing': ml.get('mispricing'),
            # 兼容旧字段
            'ml_rsi_14': ml.get('rsi_14'),
            'ml_macd_signal': ml.get('macd_signal'),
        }


if __name__ == "__main__":
    agent = OptionAgent()
    result = agent.run_advanced('TSLA')
    print(json.dumps(result, indent=2, default=str))
