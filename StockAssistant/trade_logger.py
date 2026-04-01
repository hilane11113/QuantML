#!/usr/bin/env python3
"""
TradeLogger - 决策记录 & 反馈闭环
将 demo_multi_agent.py 的每次决策记录到 debate_memory.db
支持用户反馈平仓结果
支持历史相似决策检索
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from rank_bm25 import BM25Okapi
import re

DB_PATH = os.path.join(os.path.dirname(__file__), 'debate_memory.db')


def get_db():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ============ 决策记录 ============

def log_decision(
    symbol: str,
    price: float,
    vix: float,
    vix_signal: str,
    sentiment: str,
    sentiment_score: float,
    situation: str,          # 市场情况描述（用于BM25检索）
    bull_argument: str,       # 多头论点
    bear_argument: str,      # 空头论点
    judge_decision: str,     # 裁判决策
    final_action: str,       # 最终行动
    position: int = 0,       # 建议仓位%
    debate_rounds: int = 2,
    strategy_type: str = None,  # Bull Put Spread 等
    ml_regime: str = None,
    ml_confidence: float = None,
    rsi: float = None,
    notes: str = ''
) -> int:
    """
    记录一次决策到数据库

    Returns:
        int: 记录ID
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO debate_memories (
            timestamp, symbol, price, vix, vix_signal,
            sentiment, sentiment_score, situation,
            bull_argument, bear_argument,
            judge_decision, final_action, position, debate_rounds,
            strategy_type, ml_regime, ml_confidence, rsi,
            outcome, pnl, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
    """, (
        now(), symbol, price, vix, vix_signal,
        sentiment, sentiment_score, situation,
        bull_argument, bear_argument,
        judge_decision, final_action, position, debate_rounds,
        strategy_type, ml_regime, ml_confidence, rsi,
        notes
    ))
    conn.commit()
    decision_id = cur.lastrowid
    conn.close()
    print(f"[TradeLogger] 记录决策 ID={decision_id} | {symbol} | {final_action} | {now()}")
    return decision_id


def update_decision_result(
    decision_id: int,
    outcome: str,      # 'profit' / 'loss' / 'breakeven' / 'pending'
    pnl: float = None, # 盈亏金额（权利金或实际金额）
    notes: str = ''
):
    """更新决策结果（用户反馈平仓后调用）"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE debate_memories
        SET outcome = ?, pnl = ?, notes = ?
        WHERE id = ?
    """, (outcome, pnl, notes, decision_id))
    conn.commit()
    rows = cur.rowcount
    conn.close()
    if rows > 0:
        print(f"[TradeLogger] 更新结果 ID={decision_id} | outcome={outcome} | pnl={pnl}")
    else:
        print(f"[TradeLogger] 未找到 ID={decision_id} 的记录")
    return rows > 0


def get_decision(decision_id: int) -> Optional[Dict]:
    """获取单条决策详情"""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM debate_memories WHERE id = ?", (decision_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_decisions(symbol: str = None, limit: int = 10) -> List[Dict]:
    """获取最近的决策"""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if symbol:
        cur.execute(
            "SELECT * FROM debate_memories WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, limit)
        )
    else:
        cur.execute(
            "SELECT * FROM debate_memories ORDER BY id DESC LIMIT ?",
            (limit,)
        )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_decisions(symbol: str = None) -> List[Dict]:
    """获取还未平仓的决策（outcome=NULL）"""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if symbol:
        cur.execute(
            "SELECT * FROM debate_memories WHERE symbol=? AND outcome IS NULL ORDER BY id DESC",
            (symbol,)
        )
    else:
        cur.execute(
            "SELECT * FROM debate_memories WHERE outcome IS NULL ORDER BY id DESC"
        )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============ 统计 & 分析 ============

def get_statistics(symbol: str = None) -> Dict:
    """获取历史决策统计"""
    conn = get_db()
    cur = conn.cursor()
    where = f"WHERE symbol='{symbol}'" if symbol else ""
    cur.execute(f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outcome='profit' THEN 1 ELSE 0 END) as profits,
            SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN outcome='breakeven' THEN 1 ELSE 0 END) as breakevens,
            AVG(pnl) as avg_pnl,
            SUM(pnl) as total_pnl
        FROM debate_memories
        {where}
        AND outcome IS NOT NULL
    """)
    row = cur.fetchone()
    conn.close()
    return {'total': row[0], 'profits': row[1] or 0, 'losses': row[2] or 0,
            'breakevens': row[3] or 0, 'avg_pnl': row[4], 'total_pnl': row[5]} if row else {}


def get_strategy_stats(symbol: str = None) -> List[Dict]:
    """按决策类型统计胜率"""
    conn = get_db()
    cur = conn.cursor()
    where = f"WHERE symbol='{symbol}' AND " if symbol else "WHERE "
    cur.execute(f"""
        SELECT
            judge_decision,
            COUNT(*) as count,
            AVG(pnl) as avg_pnl,
            SUM(CASE WHEN outcome='profit' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate
        FROM debate_memories
        {where} outcome IS NOT NULL
        GROUP BY judge_decision
        ORDER BY count DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [{'decision': r[0], 'count': r[1],
             'avg_pnl': r[2], 'win_rate': r[3]} for r in rows]


# ============ BM25 相似决策检索 ============

def _tokenize(text: str) -> List[str]:
    """简单分词"""
    tokens = re.findall(r'\b\w+\b', text.lower())
    return [t for t in tokens if len(t) > 1]


def build_situation_text(row: Dict) -> str:
    """把数据库行拼成一段可检索的文本"""
    parts = []
    parts.append(f"股票 {row.get('symbol')} 价格 {row.get('price')} VIX {row.get('vix')} 信号 {row.get('vix_signal')}")
    parts.append(f"情绪 {row.get('sentiment')} 评分 {row.get('sentiment_score')}")
    if row.get('rsi'):
        parts.append(f"RSI {row.get('rsi')}")
    if row.get('ml_regime'):
        parts.append(f"ML波动率regime {row.get('ml_regime')}")
    parts.append(f"情况 {row.get('situation', '')}")
    parts.append(f"决策 {row.get('judge_decision')} 行动 {row.get('final_action')}")
    parts.append(f"结果 {row.get('outcome')} 盈亏 {row.get('pnl')}")
    return ' | '.join(parts)


def find_similar_decisions(
    symbol: str,
    rsi: float = None,
    vix: float = None,
    vix_signal: str = None,
    sentiment: str = None,
    ml_regime: str = None,
    situation_hint: str = '',
    limit: int = 5
) -> List[Dict]:
    """
    用 BM25 检索相似历史决策

    基于当前市场情况，查找历史上类似的决策和结果
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 取出所有有结果的决策
    cur.execute("""
        SELECT * FROM debate_memories
        WHERE symbol=? AND outcome IS NOT NULL
        ORDER BY id DESC
    """, (symbol,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    # 构建 BM25 索引
    all_texts = [build_situation_text(dict(r)) for r in rows]
    tokenized = [_tokenize(t) for t in all_texts]
    bm25 = BM25Okapi(tokenized)

    # 构建查询文本
    query_parts = [situation_hint]
    if rsi:
        query_parts.append(f"RSI {rsi}")
    if vix:
        query_parts.append(f"VIX {vix}")
    if vix_signal:
        query_parts.append(f"信号 {vix_signal}")
    if sentiment:
        query_parts.append(f"情绪 {sentiment}")
    if ml_regime:
        query_parts.append(f"ML {ml_regime}")
    query_text = ' '.join(query_parts)
    query_tokens = _tokenize(query_text)

    # BM25 评分
    scores = bm25.get_scores(query_tokens)

    # 排序取 top
    indexed = [(i, scores[i], rows[i]) for i in range(len(rows))]
    indexed.sort(key=lambda x: x[1], reverse=True)

    results = []
    for i, score, row in indexed[:limit]:
        d = dict(row)
        d['bm25_score'] = round(score, 3)
        results.append(d)

    return results


# ============ 决策摘要报告 ============

def print_statistics(symbol: str = 'TSLA'):
    """打印统计报告"""
    stats = get_statistics(symbol)
    strat_stats = get_strategy_stats(symbol)
    recent = get_recent_decisions(symbol, limit=5)
    pending = get_pending_decisions(symbol)

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 决策统计报告  {symbol}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  总决策数: {stats['total']}
  ✅ 盈利: {stats['profits']}  ❌ 亏损: {stats['losses']}  ⚪ 保本: {stats['breakevens']}
  平均盈亏: ${stats['avg_pnl'] or 0:.2f}  累计: ${stats['total_pnl'] or 0:.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📋 待平仓决策 ({len(pending)}条)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
    for p in pending:
        print(f"  ID={p['id']} | {p['timestamp'][:10]} | {p['final_action']} | {p['strategy_type']} | 仓位:{p['position']}%")

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📈 决策胜率统计
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
    for s in strat_stats:
        wr = (s['win_rate'] or 0) * 100
        print(f"  {s['decision']} | 次数:{s['count']} | 胜率:{wr:.0f}% | 均盈:${s['avg_pnl'] or 0:.2f}")

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📝 最近5条决策
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
    for r in recent:
        outcome_icon = '✅' if r['outcome'] == 'profit' else '❌' if r['outcome'] == 'loss' else '⚪' if r['outcome'] == 'breakeven' else '⏳'
        print(f"  {outcome_icon} ID={r['id']} | {r['timestamp'][:10]} | {r['final_action']} | pnl:${r['pnl'] or 0}")


# ============ 用户反馈接口 ============

def feedback(decision_id: int, outcome: str, pnl: float = None, notes: str = ''):
    """
    用户反馈平仓结果

    用法示例:
        feedback(1, 'profit', 180, '如期到期，权利金入袋')
        feedback(2, 'loss', -120, '被打穿止损')
        feedback(3, 'breakeven', 0, '提前平仓')
    """
    valid_outcomes = ['profit', 'loss', 'breakeven', 'pending']
    if outcome not in valid_outcomes:
        print(f"[TradeLogger] outcome 必须是: {valid_outcomes}")
        return False

    decision = get_decision(decision_id)
    if not decision:
        print(f"[TradeLogger] 未找到 ID={decision_id}")
        return False

    update_decision_result(decision_id, outcome, pnl, notes)
    print(f"[TradeLogger] ✅ 已更新 ID={decision_id} | {decision['symbol']} | {decision['strategy_type']}")
    return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 1:
        print_statistics('TSLA')
    elif sys.argv[1] == 'feedback' and len(sys.argv) >= 4:
        feedback(int(sys.argv[2]), sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else None, sys.argv[5] if len(sys.argv) > 5 else '')
    elif sys.argv[1] == 'pending':
        for p in get_pending_decisions('TSLA'):
            print(p)
    elif sys.argv[1] == 'recent':
        for r in get_recent_decisions('TSLA', 10):
            print(r['id'], r['timestamp'], r['final_action'], r['outcome'], r['pnl'])
    else:
        print("用法:")
        print("  python3 trade_logger.py                    # 打印统计")
        print("  python3 trade_logger.py pending            # 待平仓决策")
        print("  python3 trade_logger.py recent             # 最近决策")
        print("  python3 trade_logger.py feedback ID outcome [pnl] [notes]")
        print("  # 示例:")
        print("  python3 trade_logger.py feedback 1 profit 180 如期到期")
        print("  python3 trade_logger.py feedback 2 loss -120 被打穿止损")
