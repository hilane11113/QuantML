#!/usr/bin/env python3
"""
MemoryAgent - 辩论记忆系统
存储和检索历史辩论经验，避免重复犯错
"""

import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
import os

DB_PATH = '/root/.openclaw/workspace/quant/StockAssistant/debate_memory.db'

def get_db_path():
    """获取数据库路径"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return DB_PATH

def init_db():
    """初始化辩论记忆数据库"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debate_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL,
            vix REAL,
            vix_signal TEXT,
            sentiment TEXT,
            sentiment_score REAL,
            situation TEXT,
            bull_argument TEXT,
            bear_argument TEXT,
            judge_decision TEXT,
            final_action TEXT,
            position INTEGER,
            debate_rounds INTEGER,
            lessons_learned TEXT,
            outcome TEXT,
            pnl REAL,
            notes TEXT
        )
    ''')
    
    conn.commit()
    return conn

def save_debate_memory(
    symbol, price, vix, vix_signal, sentiment, sentiment_score,
    situation, bull_argument, bear_argument, judge_decision,
    final_action, position, debate_rounds,
    lessons_learned='', outcome='', pnl=None, notes=''
):
    """保存辩论记忆"""
    conn = init_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO debate_memories 
        (timestamp, symbol, price, vix, vix_signal, sentiment, sentiment_score,
         situation, bull_argument, bear_argument, judge_decision,
         final_action, position, debate_rounds, lessons_learned, outcome, pnl, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        symbol, price, vix, vix_signal, sentiment, sentiment_score,
        situation, bull_argument, bear_argument, judge_decision,
        final_action, position, debate_rounds,
        lessons_learned, outcome, pnl, notes
    ))
    
    conn.commit()
    conn.close()

def get_memories(situation, symbol=None, n_matches=3):
    """检索相似记忆（关键词匹配）"""
    conn = init_db()
    cursor = conn.cursor()
    
    if symbol:
        cursor.execute('''
            SELECT * FROM debate_memories 
            WHERE symbol = ? AND outcome != ''
            ORDER BY timestamp DESC LIMIT 50
        ''', (symbol,))
    else:
        cursor.execute('''
            SELECT * FROM debate_memories 
            WHERE outcome != ''
            ORDER BY timestamp DESC LIMIT 100
        ''')
    
    results = cursor.fetchall()
    conn.close()
    
    # 提取关键词
    def extract_keywords(text):
        if not text:
            return set()
        words = re.findall(r'[\w]+', str(text).lower())
        # 过滤停用词
        stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '他', '她', '它', '为', '但', '而', '且', '以', '或', '与', '及', '等', '做', '可', '被', '将', '对', '于', '用', '从', '把', '让', '给', '向', '如', '跟', '为', '所以', '因为', '如果', '虽然', '只是', '还是', '或者', '以及', '对于', '通过', '根据', '基于', '采用', '利用', '使用', '关于', '此外', '另外', '其中', '包括', '及其', '及其', '目前', '现在', '今天', '近期', '短期', '长期', '中期', '市场', '建议', '认为', '可能', '应该', '需要', '可以', '能够', '已经', '正在', '将要', '仍然', '依然', '继续', '保持', '维持', '呈现', '显示', '表明', '显示', '预示', '预示', '支撑', '阻力', '压力', '突破', '回落', '反弹', '下跌', '上涨', '上行', '下行', '震荡', '波动'}
        return set(w for w in words if len(w) > 1 and w not in stopwords)
    
    def score_similarity(sit1, sit2):
        k1 = extract_keywords(sit1)
        k2 = extract_keywords(sit2)
        if not k1 or not k2:
            return 0
        intersection = len(k1 & k2)
        union = len(k1 | k2)
        return intersection / union if union > 0 else 0
    
    scored = []
    for r in results:
        mem_situation = r[8]  # situation字段
        score = score_similarity(situation, mem_situation)
        scored.append((score, r))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:n_matches]
    
    memories = []
    for score, r in top:
        if score > 0:
            memories.append({
                'id': r[0],
                'timestamp': r[1],
                'symbol': r[2],
                'price': r[3],
                'vix': r[4],
                'vix_signal': r[5],
                'sentiment': r[6],
                'bull_argument': r[9],
                'bear_argument': r[10],
                'judge_decision': r[11],
                'final_action': r[12],
                'position': r[13],
                'outcome': r[15],
                'pnl': r[16],
                'similarity': round(score, 3)
            })
    
    return memories

def update_outcome(debate_id, outcome, pnl=None, lessons=''):
    """更新辩论结果"""
    conn = init_db()
    cursor = conn.cursor()
    if pnl is not None:
        cursor.execute('''
            UPDATE debate_memories 
            SET outcome = ?, pnl = ?, lessons_learned = ?
            WHERE id = ?
        ''', (outcome, pnl, lessons, debate_id))
    else:
        cursor.execute('''
            UPDATE debate_memories 
            SET outcome = ?, lessons_learned = ?
            WHERE id = ?
        ''', (outcome, lessons, debate_id))
    conn.commit()
    conn.close()

def get_reflections(symbol=None, limit=10):
    """获取历史反思"""
    conn = init_db()
    cursor = conn.cursor()
    
    if symbol:
        cursor.execute('''
            SELECT timestamp, symbol, final_action, outcome, pnl, lessons_learned
            FROM debate_memories
            WHERE symbol = ? AND lessons_learned != ''
            ORDER BY timestamp DESC LIMIT ?
        ''', (symbol, limit))
    else:
        cursor.execute('''
            SELECT timestamp, symbol, final_action, outcome, pnl, lessons_learned
            FROM debate_memories
            WHERE lessons_learned != ''
            ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
    
    results = cursor.fetchall()
    conn.close()
    return results


class MemoryAgent:
    """辩论记忆代理"""
    
    def __init__(self):
        self.name = "MemoryAgent"
    
    def memorize_debate(
        self, symbol, price, vix, vix_signal, sentiment, sentiment_score,
        situation, bull_argument, bear_argument, judge_decision,
        final_action, position, debate_rounds
    ):
        """记住一次辩论"""
        save_debate_memory(
            symbol, price, vix, vix_signal, sentiment, sentiment_score,
            situation, bull_argument, bear_argument, judge_decision,
            final_action, position, debate_rounds
        )
        # 返回新记录ID
        conn = init_db()
        cursor = conn.cursor()
        cursor.execute('SELECT last_insert_rowid()')
        last_id = cursor.fetchone()[0]
        conn.close()
        return last_id
    
    def retrieve_similar(self, situation, symbol=None, n_matches=3):
        """检索相似记忆"""
        return get_memories(situation, symbol, n_matches)
    
    def reflect(self, debate_id, outcome, pnl=None, lessons=''):
        """事后反思更新"""
        update_outcome(debate_id, outcome, pnl, lessons)
    
    def get_past_reflections(self, symbol=None, limit=5):
        """获取历史反思用于决策参考"""
        results = get_reflections(symbol, limit)
        if not results:
            return []
        
        reflections = []
        for r in results:
            pnl_info = f"盈利${pnl:.2f}" if r[4] else "进行中"
            reflections.append({
                'timestamp': r[0],
                'symbol': r[1],
                'action': r[2],
                'outcome': r[3],
                'pnl_info': pnl_info,
                'lessons': r[5]
            })
        return reflections
    
    def format_memories_for_prompt(self, memories):
        """把记忆格式化成prompt字符串"""
        if not memories:
            return "无相似历史记忆。"
        
        lines = []
        for m in memories:
            lines.append(
                f"[相似情景 {m.get('timestamp','')} {m.get('symbol','')} ${m.get('price',0):.2f}]\n"
                f"  多头: {m.get('bull_argument','')}\n"
                f"  空头: {m.get('bear_argument','')}\n"
                f"  决策: {m.get('judge_decision','')} → {m.get('final_action','')} {m.get('position',0)}%\n"
                f"  结果: {m.get('outcome','')} | PnL: {m.get('pnl','N/A')}"
            )
        return '\n'.join(lines)
    
    def run(self, symbol='TSLA', situation=''):
        """执行记忆查询"""
        memories = self.retrieve_similar(situation, symbol) if situation else []
        reflections = self.get_past_reflections(symbol)
        return {
            'similar_memories': memories,
            'past_reflections': reflections
        }

if __name__ == "__main__":
    agent = MemoryAgent()
    
    # 测试存储
    debate_id = agent.memorize_debate(
        symbol='TSLA', price=390.0, vix=25.0, vix_signal='GREEN',
        sentiment='neutral', sentiment_score=50,
        situation='下跌趋势 RSI45 VIX25 GREEN 市场neutral',
        bull_argument='RSI偏低支撑位可博反弹',
        bear_argument='趋势下跌策略不符应观望',
        judge_decision='谨慎看多逢低布局轻仓',
        final_action='观望', position=0, debate_rounds=2
    )
    print(f"保存辩论, ID={debate_id}")
    
    # 测试检索
    memories = agent.retrieve_similar('TSLA 下跌趋势 RSI42 VIX26')
    print(f"检索到 {len(memories)} 条相似记忆")
    for m in memories:
        print(f"  相似度:{m.get('similarity')} | {m.get('symbol')} {m.get('final_action')}")
