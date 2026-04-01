#!/usr/bin/env python3
"""
多 Agent 协作分析演示
完整流程: TechAgent → SocialAgent → OptionAgent → ResearcherTeam(多轮辩论) → RiskAgent

数据架构：
  UnifiedDataFetcher 一次调完 yfinance + VIX，数据存入 data_context
  → 传给所有 Agent，不重复访问网络

输出格式：agent_格式四.md
"""

import os
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(var, None)

import json
import trade_logger as tl
from unified_fetcher import UnifiedDataFetcher, fetch_unified
import re


def _bold_points(text, max_pts=5, max_len=40):
    """提取 **加粗** 核心观点，提取失败则用普通行"""
    points = re.findall(r'\*\*(.+?)\*\*', text)
    if points:
        return [f"    • {p[:max_len]}" for p in points[:max_pts]]
    lines = [l.strip().lstrip('-•*').strip() for l in text.split('\n')]
    lines = [l for l in lines if l and len(l) > 5]
    return [f"    • {l[:max_len]}" for l in lines[:max_pts]]


def _vix_emoji(sig):
    return "🟢" if sig == "GREEN" else "🔴" if sig == "RED" else "🟡"


def _sentiment_emoji(label):
    label = label or ""
    if "多" in label or "bullish" in label.lower() or "买入" in label:
        return "🟢"
    if "空" in label or "bearish" in label.lower() or "卖出" in label:
        return "🔴"
    return "🟡"


def _decision_emoji(decision):
    decision = decision or ""
    if "开仓" in decision or "买入" in decision or "做多" in decision:
        return "✅"
    if "试探" in decision or "观望" in decision:
        return "🟡"
    return "🔴"


def _regime_emoji(regime):
    regime = regime or ""
    if regime == "low":
        return "🟢"
    if regime == "high":
        return "🔴"
    return "🟡"


def _fmt(val, fmt, fallback="N/A"):
    """安全格式化，支持 None"""
    if val is None:
        return fallback
    if isinstance(val, (int, float)):
        return format(val, fmt)
    return str(val)


def analyze(symbol='TSLA', debate_rounds=2, use_mock=False):
    """完整多 Agent 协作分析"""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── yfinance 请求计数器（避免限流，不在分析脚本中安装）────
    # 计数器已安装在 fetch_all_data.py，分析脚本不需要

    # ── 统一数据获取（一次请求，所有Agent共用）────────────
    if use_mock:
        from unified_fetcher import get_mock_ctx
        ctx = get_mock_ctx(symbol)
        print(f"[MOCK] 使用模拟数据 price={ctx['price']} iv={ctx['iv']} chains={len(ctx['option_chains'])}")
    else:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fetcher = UnifiedDataFetcher(symbol)
            ctx = fetcher.get_context()
            fetcher.summary()

    # 延迟导入（避免循环依赖）
    from agents.technical_agent import TechnicalAgent
    from agents.social_agent import SocialAgent
    from agents.option_agent import OptionAgent
    from agents.researcher import ResearcherTeam
    from agents.risk_agent import RiskAgent
    from agents.memory_agent import MemoryAgent

    # ══════════════════════════════════════════════════════
    # 报告头部
    # ══════════════════════════════════════════════════════
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  🤖 {symbol} 多 Agent 协作分析报告  📅 {ts}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ══════════════════════════════════════════════════════
    # Agent 1: TechAgent
    # ══════════════════════════════════════════════════════
    tech_agent = TechnicalAgent()
    tech = tech_agent.analyze_with_context(symbol, ctx)

    _price = tech.get('price')
    _rsi = tech.get('rsi')
    _sup = tech.get('support')
    _res = tech.get('resistance')
    _trend = tech.get('trend', 'N/A')

    _price_str = _fmt(_price, '.2f') if _price else "N/A"
    _rsi_str = _fmt(_rsi, '.1f') if _rsi else "N/A"
    _sup_str = _fmt(_sup, '.2f') if _sup else "N/A"
    _res_str = _fmt(_res, '.2f') if _res else "N/A"

    if isinstance(_rsi, (int, float)):
        _rsi_cond = "超卖" if _rsi < 30 else "超买" if _rsi > 70 else "中性"
    else:
        _rsi_cond = "N/A"

    print(f"━━━ Agent 1: TechAgent (技术分析) ━━━━━━━━━━━━━━━━━━━")
    print(f"  📊 价格: ${_price_str}")
    print(f"  📈 趋势: {_trend}")
    print(f"  📉 RSI: {_rsi_str} ({_rsi_cond})")
    print(f"  🛡️ 支撑: ${_sup_str} | 阻力: ${_res_str}")

    # ══════════════════════════════════════════════════════
    # Agent 2: SocialAgent
    # ══════════════════════════════════════════════════════
    social = SocialAgent()
    sentiment = social.run_with_context(symbol, ctx)
    cs = sentiment.get('composite_sentiment', {})

    _kw_label = cs.get('keyword', 'N/A')
    _kw_score = cs.get('keyword_score', cs.get('keyword_sentiment_score', 'N/A'))
    _llm_label = cs.get('llm', cs.get('llm_sentiment', 'N/A'))
    _llm_score = cs.get('llm_score', 'N/A')
    _ape = cs.get('apewisdom', cs.get('apewisdom_sentiment', 'N/A'))
    _ape_mentions = cs.get('mentions', 'N/A')
    _llm_reason = cs.get('llm_reason', cs.get('reason', sentiment.get('llm_reason', 'N/A') or 'N/A'))
    _comp_label = cs.get('composite_label', sentiment.get('sentiment', 'N/A'))
    _comp_score = cs.get('composite_score', sentiment.get('sentiment_score', 'N/A'))

    print(f"━━━ Agent 2: SocialAgent (舆情分析) ━━━━━━━━━━━━━━━━━━━")
    print(f"  {_sentiment_emoji(_kw_label)} 关键词情绪: {_kw_label} ({_kw_score})")
    print(f"  {_sentiment_emoji(_llm_label)} LLM情绪: {_llm_label} (评分: {_llm_score})")
    print(f"  {_sentiment_emoji(_ape)} apewisdom: {_ape} (mentions={_ape_mentions})")
    print(f"  💬 LLM理由: {str(_llm_reason)[:200]}")

    # ══════════════════════════════════════════════════════
    # Agent 3: OptionAgent
    # ══════════════════════════════════════════════════════
    opt = OptionAgent()
    option = opt.run_advanced_with_context(symbol, ctx)
    vix_sig = option.get('vix_signal', 'N/A')
    vix_val = option.get('vix', 0)
    iv_val = option.get('iv', 0)
    strategies = option.get('strategies', []) or []

    print(f"━━━ Agent 3: OptionAgent (期权分析) ━━━━━━━━━━━━━━━━━━━")
    print(f"  📊 VIX: {_vix_emoji(vix_sig)} {vix_sig} ({_fmt(vix_val, '.2f')})")
    print(f"  📉 IV: {_fmt(iv_val, '.1f')}% | 舆情: {_sentiment_emoji(_comp_label)} {_comp_label}")

    if not strategies:
        print("  (期权数据暂不可用)")
    for i, s in enumerate(strategies[:4]):
        score = s.get('composite_score') or s.get('score', 'N/A')
        decision = s.get('decision', s.get('direction', ''))
        position = s.get('position', s.get('position_pct', 0) or 0)
        expiry_days = s.get('days_to_expiry')
        expiry_date = s.get('actual_expiry_date', '')
        expiry_info = f"{expiry_date}({expiry_days}天)" if expiry_days and expiry_date else (f"{expiry_days}天" if expiry_days else "N/A")

        # 预测胜率
        wr = s.get('predicted_win_rate')
        wr_conf = s.get('win_rate_confidence', '')
        wr_n = s.get('win_rate_n', 0)
        if wr is not None:
            wr_str = f"{wr*100:.0f}%"
        else:
            wr_str = "N/A"

        stype = s.get('type', 'N/A')
        credit = s.get('credit', s.get('premium', 0)) or 0
        max_loss = s.get('max_loss') or 0
        max_profit = s.get('max_profit', credit)
        theta = s.get('theta', 0)

        # 策略构成
        if stype == 'Iron Condor':
            sp = s.get('short_put') or s.get('short_strike', '?')
            lp = s.get('long_put') or s.get('long_strike', '?')
            sc = s.get('short_call', '?')
            lc = s.get('long_call', '?')
            structure = f"卖${sp}/买${lp}Put, 卖${sc}/买${lc}Call（4条腿）"
        elif s.get('short_strike') and s.get('long_strike'):
            structure = f"卖${s.get('short_strike')}/买${s.get('long_strike')}"
        elif s.get('strike'):
            structure = f"行权价${s.get('strike')}"
        else:
            structure = "N/A"

        _dec_emoji = _decision_emoji(decision)
        print(f"  {_dec_emoji} {i+1}. {stype} | 评分:{score} | 预测胜率:{wr_str} | {decision} | 仓位:{position}%")
        print(f"      到期:{expiry_info} | {structure}")
        theta_str = f" | Theta:${theta:.3f}/天" if theta else ""
        print(f"      权利金:${credit:.2f} | 最大亏损:${max_loss:.2f} | 最大盈利:${max_profit:.2f}{theta_str}")
        if wr is not None and wr_n > 0:
            print(f"      胜率置信度:{wr_conf} | 历史样本:{wr_n}笔")

    # ══════════════════════════════════════════════════════
    # ML 增强分析
    # ══════════════════════════════════════════════════════
    ml_signal = option.get('ml_signal', {})
    ml_enabled = ml_signal.get('ml_enabled', False)

    print(f"\n━━━ 🤖 ML 增强分析 (VolatilityPredictor) ━━━━━━━━━━━━━━━")

    if not ml_enabled:
        print(f"  ⚠️  ML模型未加载或未训练（跳过高波动率预测）")
    else:
        ml_regime = ml_signal.get('ml_regime', 'N/A')
        ml_pred_vol = ml_signal.get('ml_predicted_vol')
        ml_vol_adj = ml_signal.get('ml_vol_adj')
        ml_action = ml_signal.get('ml_action', 'N/A')
        ml_confidence = ml_signal.get('ml_confidence', 'N/A')
        ml_reason = ml_signal.get('ml_reason', 'N/A')
        ml_rsi = ml_signal.get('rsi_14', 'N/A')
        ml_rsi7 = ml_signal.get('rsi_7', 'N/A')
        ml_macd = ml_signal.get('macd_signal', 'N/A')
        ml_vix = ml_signal.get('vix', vix_val)
        ml_vix_sig = ml_signal.get('vix_signal', vix_sig)
        divergence = ml_signal.get('divergence', {})
        mispricing = ml_signal.get('mispricing', {})
        enhanced_decision = ml_signal.get('enhanced_decision', 'N/A')

        pred_str = f"{ml_pred_vol:.1%}" if isinstance(ml_pred_vol, (int, float)) else str(ml_pred_vol or 'N/A')
        vol_adj_str = f"{ml_vol_adj:.1%}" if isinstance(ml_vol_adj, (int, float)) else str(ml_vol_adj or 'N/A')
        conf_str = f"{ml_confidence:.0%}" if isinstance(ml_confidence, (int, float)) else str(ml_confidence or 'N/A')
        ml_vix_str = f"{ml_vix:.2f}" if isinstance(ml_vix, (int, float)) else str(ml_vix or 'N/A')

        div_type = divergence.get('type', 'none')
        div_emoji = "🟢" if div_type == 'bullish' else "🔴" if div_type == 'bearish' else "⚪"
        div_strength = divergence.get('strength', 0)
        div_desc = divergence.get('description', '无明显背离')

        mis_type = mispricing.get('type', 'none')
        mis_emoji = "🟢" if mis_type == 'premium_selling' else "🔴" if mis_type == 'premium_buying' else "⚪"
        mis_ratio = mispricing.get('ratio', 'N/A')
        mis_desc = mispricing.get('description', 'N/A')

        print(f"  🧠 模型状态: ✅ 已加载")
        print(f"  📈 预测波动率: {pred_str} (调整后: {vol_adj_str})")
        print(f"  🏷️ 波动率 Regime: {_regime_emoji(ml_regime)} {str(ml_regime).upper()}")
        print(f"  📊 VIX: {_vix_emoji(ml_vix_sig)} {ml_vix_sig}({ml_vix_str})")
        print(f"  📉 RSI(14): {ml_rsi} | MACD: {ml_macd}")
        print(f"  🔍 动量背离: {div_emoji} {str(div_type).upper()} (强度:{div_strength}) | {div_desc}")
        print(f"  📐 波动率错配: {mis_emoji} {str(mis_type).upper()} (ratio={mis_ratio}) | {mis_desc}")
        print(f"  🎯 ML信号: {ml_action}")
        print(f"  💬 ML理由: {str(ml_reason)[:300]}")
        print(f"  ✅ 增强决策: {enhanced_decision}")

    # ══════════════════════════════════════════════════════
    # Agent 4: ResearcherTeam
    # ══════════════════════════════════════════════════════
    memory = MemoryAgent()
    news_data = {'topics': {k: v for k, v in sentiment.get('sources', {}).items() if v}}
    team = ResearcherTeam(memory_agent=memory, max_rounds=debate_rounds)

    # 捕获 debate() 的直接打印输出（不在这里重复展示）
    import io, contextlib
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        debate_result = team.debate(news_data, option, tech)

    print(f"\n━━━ Agent 4: ResearcherTeam (多轮辩论 {debate_rounds}轮) ━━━━━━━")

    def extract_blocks(text, tag='BULL'):
        blocks = []
        for m in re.finditer(rf'\[{tag}_ARG\]\s*(.*?)\s*\[/{tag}_ARG\]', text or '', re.DOTALL):
            content = m.group(1).strip()
            if content:
                blocks.append(content)
        return blocks

    bull_blocks = extract_blocks(debate_result.get('bull_args', ''), 'BULL')
    bear_blocks = extract_blocks(debate_result.get('bear_args', ''), 'BEAR')

    # 看多论点汇总
    print(f"\n  🟢 === 看多论点 ===")
    for rnd in range(debate_rounds):
        print(f"\n  ── 第{rnd+1}轮看多 ──")
        if rnd < len(bull_blocks):
            content = bull_blocks[rnd][:800]
            pts = _bold_points(content, max_pts=5)
            for pt in pts:
                print(f"    {pt}")
            print(f"\n  {content[:300]}...")
        else:
            print("    (无看多论点)")

    # 看空论点汇总
    print(f"\n  🔴 === 看空论点 ===")
    for rnd in range(debate_rounds):
        print(f"\n  ── 第{rnd+1}轮看空 ──")
        if rnd < len(bear_blocks):
            content = bear_blocks[rnd][:800]
            pts = _bold_points(content, max_pts=5)
            for pt in pts:
                print(f"    {pt}")
            print(f"\n  {content[:300]}...")
        else:
            print("    (无看空论点)")

    # 综合决策
    dec = debate_result.get('decision', {})
    dec_action = dec.get('decision', 'N/A')
    dec_conf = dec.get('confidence', 'N/A')
    dec_rat = dec.get('rationale', '')
    dec_plan = dec.get('action_plan', '')
    dec_risk = dec.get('risk_note', '')

    dec_e = _decision_emoji(dec_action)
    conf_e = "🟢" if dec_conf == "高" else "🔴" if dec_conf == "低" else "🟡"

    print(f"""
──────────────────────────────────────────────────
  ⚔️  综合决策
──────────────────────────────────────────────────
  {dec_e} 决策: {dec_action}   {conf_e} 信心: {dec_conf}
  📝 理由: {str(dec_rat)[:200] or 'N/A'}
  📋 计划: {str(dec_plan)[:200] or 'N/A'}""" + (f"\n  ⚠️ 风险: {str(dec_risk)[:200]}" if dec_risk else ""))

    # ══════════════════════════════════════════════════════
    # Agent 5: RiskAgent
    # ══════════════════════════════════════════════════════
    risk_agent = RiskAgent()
    risk_action = 'BUY' if ('买' in dec_action or '开仓' in dec_action) else 'HOLD'
    risk = risk_agent.evaluate(news_data, option, {'action': risk_action})
    risk_emoji = "🔴" if risk.get('risk_level') == 'HIGH' else "🟡" if risk.get('risk_level') == 'MEDIUM' else "🟢"

    debate_id = memory.memorize_debate(
        symbol=symbol,
        price=option.get('price', 0),
        vix=option.get('vix', 0),
        vix_signal=option.get('vix_signal', ''),
        sentiment=_comp_label,
        sentiment_score=_comp_score,
        situation=f"{_trend} {str(_llm_reason or '')[:50]}",
        bull_argument=debate_result.get('bull_args', '')[:300],
        bear_argument=debate_result.get('bear_args', '')[:300],
        judge_decision=dec_action,
        final_action=dec_action,
        position=(strategies[0].get('position') if strategies else 0),
        debate_rounds=debate_rounds
    )

    print(f"\n━━━ Agent 5: RiskAgent (风险评估) ━━━━━━━━━━━━━━━━━━━━━")
    print(f"  🛡️ 风险等级: {risk_emoji} {risk.get('risk_level', 'N/A')}")
    print(f"  📊 仓位建议: {risk.get('position_size', 'N/A')}")
    print(f"  🛑 止损位: {risk.get('stop_loss', 'N/A')}")
    print(f"  💡 建议: {str(risk.get('recommendation', 'N/A'))[:200]}")
    print(f"  💾 辩论记忆已保存 (ID={debate_id})")

    # ══════════════════════════════════════════════════════
    # 综合结论
    # ══════════════════════════════════════════════════════
    ml_regime_str = str(ml_signal.get('ml_regime') or '?').upper()
    best_strat = strategies[0].get('type', 'N/A') if strategies else dec_action

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  📋 综合结论")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  📊 市场: ${_fmt(option.get('price'), '.2f')} | VIX {_fmt(vix_val, '.1f')} ({vix_sig})")
    print(f"  💬 舆情: {_comp_label} ({_comp_score}/100)")
    print(f"  📈 策略: {best_strat}")
    print(f"  🧠 ML: {ml_signal.get('ml_action', 'N/A')} ({ml_regime_str}区)")
    print(f"  ⚔️ 辩论: {dec_action} ({dec_conf})")
    print(f"  🛡️ 风控: {risk.get('risk_level', 'N/A')} | {risk.get('position_size', 'N/A')}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  💡 综合建议: {str(dec_plan or dec_rat)[:200] or 'N/A'}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ══════════════════════════════════════════════════════
    # 决策记录 & 相似历史
    # ══════════════════════════════════════════════════════
    situation = f"{_trend}趋势 RSI={_rsi_str} {_comp_label}"
    strategy_type = strategies[0].get('type', dec_action) if strategies else dec_action
    ml_sig = option.get('ml_signal', {})

    decision_id = tl.log_decision(
        symbol=symbol,
        price=option.get('price'),
        vix=option.get('vix'),
        vix_signal=option.get('vix_signal'),
        sentiment=_comp_label,
        sentiment_score=_comp_score,
        situation=situation,
        bull_argument=debate_result.get('bull_args', '')[:300],
        bear_argument=debate_result.get('bear_args', '')[:300],
        judge_decision=dec_action,
        final_action=dec_action,
        position=(strategies[0].get('position') if strategies else risk.get('position_size', 'N/A')),
        debate_rounds=debate_rounds,
        strategy_type=strategy_type,
        ml_regime=ml_sig.get('ml_regime'),
        ml_confidence=ml_sig.get('ml_confidence'),
        rsi=_rsi,
    )

    similar = tl.find_similar_decisions(
        symbol=symbol,
        rsi=_rsi,
        vix=option.get('vix'),
        vix_signal=option.get('vix_signal'),
        sentiment=_comp_label,
        ml_regime=ml_sig.get('ml_regime'),
        situation_hint=situation,
        limit=3
    )

    if similar:
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📜 历史相似决策参考")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for s in similar:
            out_icon = '✅' if s.get('outcome') == 'profit' else '❌' if s.get('outcome') == 'loss' else '⚪' if s.get('outcome') == 'breakeven' else '⏳'
            print(f"  {out_icon} ID={s['id']} | {str(s.get('timestamp',''))[:10]} | {s.get('judge_decision','N/A')} | {s.get('final_action','N/A')}")
            print(f"     RSI={s.get('rsi','?')} VIX={s.get('vix','?')} | pnl=${s.get('pnl') or 0} | {s.get('outcome','pending')}")
            print(f"     BM25相似度: {s.get('bm25_score','?')}")
        print(f"  ⚠️ 历史仅供参考，不构成投资建议")
    else:
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📜 历史记录: 暂无决策历史，这是第一条记录")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    print(f"  📝 记录ID: {decision_id}")
    print()

    return {
        'symbol': symbol,
        'decision_id': decision_id,
        'price': option.get('price'),
        'vix': option.get('vix'),
        'vix_signal': option.get('vix_signal'),
        'iv': option.get('iv'),
        'sentiment': _comp_label,
        'tech': tech,
        'sentiment_detail': sentiment,
        'option': option,
        'debate': debate_result,
        'risk': risk,
        'debate_id': debate_id
    }


if __name__ == "__main__":
    import sys
    use_mock = '--mock' in sys.argv
    symbol = 'TSLA'
    args = [a for a in sys.argv if not a.startswith('--')]
    if len(args) > 1:
        symbol = args[1]
    rounds = 2
    for a in sys.argv:
        if a.isdigit():
            rounds = int(a)
    analyze(symbol, rounds, use_mock=use_mock)
