#!/usr/bin/env python3
"""
垂直价差单策略分析 (简洁版)

用法:
    python3 vertical_spread_simple.py TSLA --ctx-file=/tmp/tsla_ctx.json

所有数据走 UnifiedDataFetcher 统一接口，不发网络请求。
"""

import sys
import os
import json
import argparse
from pathlib import Path

# ── strategy_engine 路径 ────────────────────────────────────
_engine_path = Path('/root/.openclaw/workspace/quant/StockAssistant')
if str(_engine_path) not in sys.path:
    sys.path.insert(0, str(_engine_path))

from strategy_engine import calculate_strategies_from_ctx

PROXY = 'http://127.0.0.1:7897'
os.environ.setdefault('https_proxy', PROXY)
os.environ.setdefault('http_proxy', PROXY)


def load_ctx(symbol, ctx_file):
    """从 ctx 文件加载数据，支持 {symbol: ctx} 或直接 ctx 格式"""
    with open(ctx_file, encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict) and 'price' not in raw:
        # 嵌套格式 {symbol: ctx}
        if symbol in raw:
            return raw[symbol]
        # 取第一个
        for v in raw.values():
            if isinstance(v, dict):
                return v
    return raw


def analyze(symbol, ctx_file):
    ctx = load_ctx(symbol, ctx_file)

    price = ctx.get('price', 0)
    iv_raw = ctx.get('iv', 35)
    iv = round(iv_raw * 100, 1) if isinstance(iv_raw, float) and 0 < iv_raw < 1 else float(iv_raw)
    vix = ctx.get('vix', 20)
    vix_ma = ctx.get('vix_ma10', vix)

    # VIX 信号（与 strategy_engine 保持一致）
    if vix > 30:
        vix_signal = 'RED'
    elif vix < 15:
        vix_signal = 'GREEN'
    elif vix > 25:
        vix_signal = 'YELLOW'
    elif vix > 20:
        vix_signal = 'YELLOW'
    else:
        vix_signal = 'YELLOW'

    # 计算偏离度
    deviation = ((vix - vix_ma) / vix_ma * 100) if vix_ma and vix_ma > 0 else 0

    # 动态阈值
    base = {'GREEN': 35, 'YELLOW': 50, 'RED': 60}.get(vix_signal, 50)
    if iv > 60: base += 5
    if iv < 20: base -= 5
    threshold = base
    threshold_open = threshold + 15

    # 舆情
    sentiment = ctx.get('sentiment', 'neutral')
    sentiment_map = {'bullish': 80, 'neutral': 50, 'bearish': 20}
    sentiment_score = sentiment_map.get(sentiment, 50)

    # 复合评分（VIX + 舆情）
    if vix_signal == 'RED':
        composite = int(sentiment_score * 0.4)
    elif vix_signal == 'GREEN':
        composite = int(sentiment_score * 1.2)
    else:
        composite = int(sentiment_score * 0.7)

    engine_ctx = {
        'price': price,
        'iv': iv,
        'vix': vix,
        'vix_signal': vix_signal,
        'vix_ma10': vix_ma,
        'sentiment': sentiment,
        'option_chains': ctx.get('option_chains', []),
    }

    results = calculate_strategies_from_ctx(symbol, engine_ctx)

    # ── 输出格式一 ──────────────────────────────────────────
    print("=" * 60)
    print(f"  📋 TSLA 策略推荐详情")
    print("=" * 60)
    print(f"  📈 {symbol} - {'⏸️ 观望' if vix_signal == 'RED' else '📊 推荐'}")
    print()
    print(f"  📊 市场概况")
    print(f"  ─────────────")
    sig_emoji = {'GREEN': '🟢', 'YELLOW': '🟡', 'RED': '🔴'}.get(vix_signal, '🟡')
    print(f"  VIX        {sig_emoji} {vix:.2f} (信号: {vix_signal}, 偏离: {deviation:+.1f}%)")
    print(f"  股价             ${price:.2f}")
    print(f"  IV         {iv:.1f}%")
    print(f"  舆情       {sentiment}")
    print(f"  综合评分   {composite}/100 {'🟡' if composite < 70 else '🟢'}")
    print()
    print(f"  📊 动态阈值  {threshold} (≥{threshold_open}开仓)")
    print()

    # 取最优 Bull Put Spread
    bull_puts = results.get('Bull_Put', [])
    bull_calls = results.get('Bull_Call', [])
    iron_condors = results.get('Iron_Condor', [])
    short_puts = results.get('Short_Put', [])

    # 选最优 Bull Put 作为主推荐
    if bull_puts:
        best = bull_puts[0]
        decision = "✅开仓" if best['score'] >= threshold_open else ("🟡试探" if best['score'] >= threshold else "🔴禁止")
        print(f"  📌 推荐策略: Bull Put Spread  ({decision})")
        print(f"  ──────────────────────────────────────────────")
        print(f"  Short Strike (卖)    ${best.get('short_strike', 'N/A')}")
        print(f"  Long Strike  (买)   ${best.get('long_strike', 'N/A')}")
        print(f"  价差宽度             ${best.get('width', 0):.2f}")
        print(f"  权利金              ${best.get('premium', 0):.2f}")
        print(f"  最大盈利            ${best.get('max_profit', 0):.2f}")
        print(f"  最大亏损            ${best.get('max_loss', 0):.2f}")
        rr = best.get('rr_ratio', 0)
        print(f"  风险回报比          {rr:.2f}")
        theta = best.get('theta', 0)
        print(f"  Theta(每日)         ${theta:.3f}/天")
        days = best.get('days', 0)
        expiry = best.get('expiry', 'N/A')
        print(f"  到期日              {expiry} (剩余{days}天)")
        print(f"  评分                {best.get('score', 0):.0f} {'✅' if best['score'] >= threshold_open else '🟡' if best['score'] >= threshold else '🔴'}")
        position = int(best.get('score', 0) * 0.6) if best['score'] >= threshold else 0
        print(f"  建议仓位            {position}%")
        print()
    else:
        print(f"  ⚠️ 无符合条件的 Bull Put Spread 策略")
        print()

    # 附加：其他策略最优
    others = []
    if iron_condors: others.append(('Iron Condor', iron_condors[0]))
    if bull_calls: others.append(('Bull Call Spread', bull_calls[0]))
    if short_puts: others.append(('Short Put', short_puts[0]))

    if others:
        print(f"  📋 其他策略参考")
        print(f"  ──────────────────────────────────────────────")
        for name, s in others:
            d = "✅" if s['score'] >= threshold_open else ("🟡" if s['score'] >= threshold else "🔴")
            strike_info = s.get('strike_str', f"${s.get('short_strike','')}")
            print(f"  {d} {name:22s} {strike_info:25s} 评分{s['score']:.0f}")

    print()
    print("=" * 60)
    print(f"  💡 备注: 数据来自统一数据口 | VIX信号: {vix_signal} | 综合评分: {composite}/100")
    print("=" * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='垂直价差单策略分析')
    parser.add_argument('symbol', help='股票代码，如 TSLA')
    parser.add_argument('--ctx-file', required=True, help='UnifiedDataFetcher ctx JSON 文件路径')
    args = parser.parse_args()

    print(f"[INFO] 加载数据: {args.ctx_file}")
    analyze(args.symbol, args.ctx_file)
