#!/usr/bin/env python3
"""
胜率预测表 + 简单机器学习模型
基于282笔真实+回测数据
"""
import os
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'

import pandas as pd
import numpy as np
import json
import pickle
import re
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_score

DATA_DIR = '/root/.openclaw/workspace/quant/QuantML/data'
os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# Step 1: 加载数据
# ============================================================
print("[1/4] 加载市场数据...")
market = pd.read_pickle(f'{DATA_DIR}/market_full.pkl')
market.index = pd.to_datetime(market.index)
tsla_mkt = market[['Close','RSI','VIX','SMA20']].copy()
tsla_mkt.columns = ['price','rsi','vix','sma20']
tsla_mkt['rsi'] = tsla_mkt['rsi'].ffill().bfill()
tsla_mkt['vix'] = tsla_mkt['vix'].ffill().bfill()
tsla_mkt['trend'] = np.where(tsla_mkt['price'] > tsla_mkt['sma20'], '上涨', '下跌')

print(f"  TSLA市场: {len(tsla_mkt)} 行")

# ============================================================
# Step 2: 解析真实交易
# ============================================================
print("[2/4] 解析真实交易记录...")

real_df = pd.read_excel('/root/.openclaw/workspace/quant/期权记录.xlsx', sheet_name='Sheet1')
real_df = real_df.dropna(subset=['Date','Asset','Profit'])
real_df['Date'] = pd.to_datetime(real_df['Date'])
real_df['Profit'] = pd.to_numeric(real_df['Profit'], errors='coerce')

def parse_op(op):
    if pd.isna(op): return None, None, None
    op = str(op).replace('\n',' ')
    m = re.findall(r'(Sell|Buy)\s+\d+\s+([\d.]+)\s+(PUT|CALL)', op)
    if len(m) >= 2:
        return float(m[0][1]), float(m[1][1]), m[0][2].lower()
    m2 = re.findall(r'Buy\s+\d+\s+([\d.]+)\s+(PUT|CALL)', op)
    if m2: return None, float(m2[0][0]), m2[0][1].lower()
    return None, None, None

real_df['short_strike'], real_df['long_strike'], real_df['opt_type'] = \
    zip(*real_df['Specific Operation'].apply(parse_op))

# 过滤 TSLA PUT (Bull Put Spread / Short Put)
tsla_put = real_df[
    (real_df['Asset']=='TSLA') &
    (real_df['opt_type']=='put') &
    (real_df['short_strike'].notna())
].copy()

# enrichment: 从市场数据获取 rsi/vix/trend
def enrich(row):
    date = row['Date']
    if date not in tsla_mkt.index:
        idx = tsla_mkt.index.get_indexer([date], method='nearest')[0]
        date = tsla_mkt.index[max(0, idx)]
    p = tsla_mkt.loc[date, 'price']
    r = tsla_mkt.loc[date, 'rsi']
    v = tsla_mkt.loc[date, 'vix']
    tr = tsla_mkt.loc[date, 'trend']
    ss = row['short_strike']
    otm = (ss - p) / p * 100 if ss and p else None
    days = row.get('Holding Period (Days)', 14) if 'Holding Period (Days)' in row.index else 14
    return pd.Series({
        'entry_price': p, 'entry_rsi': r, 'entry_vix': v,
        'entry_trend': tr, 'otm_pct': otm, 'holding_days': int(days) if pd.notna(days) else 14
    })

enr = tsla_put.apply(enrich, axis=1)
for col in enr.columns:
    tsla_put[col] = enr[col].values
tsla_put['is_win'] = tsla_put['Profit'] > 0
tsla_put['is_simulated'] = False
print(f"  真实 TSLA PUT: {len(tsla_put)} 笔")

# ============================================================
# Step 3: 生成回测交易
# ============================================================
print("[3/4] 生成历史回测交易...")

bt_rows = []
seen = set()
for i in range(20, len(tsla_mkt) - 15):
    date = tsla_mkt.index[i]
    if date.weekday() != 4: continue
    dk = date.date()
    if dk in seen: continue
    seen.add(dk)

    rsi = tsla_mkt.loc[date, 'rsi']
    vix = tsla_mkt.loc[date, 'vix']
    price = tsla_mkt.loc[date, 'price']
    trend = tsla_mkt.loc[date, 'trend']
    if pd.isna(rsi) or pd.isna(vix) or pd.isna(price): continue

    short_strike = round(price * 0.95, 0)
    otm_pct = (short_strike - price) / price * 100

    future = tsla_mkt['price'].iloc[i+1:i+15].values
    if len(future) < 5: continue

    premium = price * (vix / 100) * np.sqrt(14/365)
    end_price = future[-1]
    pnl = premium * 100 - max(0, short_strike - end_price) * 100

    bt_rows.append({
        'Date': date, 'price': price, 'entry_rsi': rsi, 'entry_vix': vix,
        'entry_trend': trend, 'otm_pct': otm_pct, 'is_win': pnl > 0,
        'profit': pnl, 'holding_days': 14,
        'strategy_type': 'ShortPut', 'is_simulated': True
    })

bt = pd.DataFrame(bt_rows)
print(f"  回测交易: {len(bt)} 笔")

# 合并
# 真实交易 enrichment 后加入 strategy_type
tsla_put['strategy_type'] = 'BullPutSpread'
tsla_put['profit'] = tsla_put['Profit']
tsla_put['holding_days'] = tsla_put['Holding Period (Days)'].fillna(14)

all_trades = pd.concat([
    tsla_put[['Date','is_win','entry_price','entry_rsi','entry_vix',
              'entry_trend','otm_pct','profit','holding_days',
              'strategy_type']].assign(sim=False),
    bt.assign(sim=True)
], ignore_index=True)
print(f"  合并: {len(all_trades)} 笔 | 胜率: {all_trades['is_win'].mean()*100:.1f}%")

# ============================================================
# Step 4: 特征工程
# ============================================================
print("[4/4] 训练模型 + 生成胜率表...")

def zone_rsi(r):
    if pd.isna(r): return 'RSI<30'
    if r < 30: return 'RSI<30'
    if r < 40: return 'RSI30-40'
    if r < 60: return 'RSI40-60'
    return 'RSI>60'

def zone_vix(v):
    if pd.isna(v): return 'VIX15-20'
    if v < 15: return 'VIX<15'
    if v < 20: return 'VIX15-20'
    if v < 25: return 'VIX20-25'
    return 'VIX>25'

def zone_otm(o):
    if pd.isna(o): return 'OTM5-7'
    if o < -10: return 'OTM>10'
    if o < -7: return 'OTM7-10'
    if o < -5: return 'OTM5-7'
    if o < -3: return 'OTM3-5'
    return 'ITM<3'

all_trades['zone_rsi'] = all_trades['entry_rsi'].apply(zone_rsi)
all_trades['zone_vix'] = all_trades['entry_vix'].apply(zone_vix)
all_trades['zone_otm'] = all_trades['otm_pct'].apply(zone_otm)

def ci_wilson(n, k, z=1.96):
    if n == 0: return 0.5, 0, 1
    p = k / n
    denom = 1 + z**2/n
    center = (p + z**2/(2*n)) / denom
    margin = z * np.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
    lo, hi = max(0, center-margin), min(1, center+margin)
    return p, lo, hi

# 胜率查表
win_rate_table = {}
for rz in all_trades['zone_rsi'].unique():
    for vz in all_trades['zone_vix'].unique():
        for oz in all_trades['zone_otm'].unique():
            sub = all_trades[(all_trades['zone_rsi']==rz)&(all_trades['zone_vix']==vz)&(all_trades['zone_otm']==oz)]
            if len(sub) < 2: continue
            n, wins = len(sub), sub['is_win'].sum()
            wr, lo, hi = ci_wilson(n, wins)
            real_n = len(sub[~sub['sim']])
            win_rate_table[f"{rz}||{vz}||{oz}"] = {
                'win_rate': round(wr,4), 'n': n, 'real_n': real_n,
                'ci_low': round(lo,4), 'ci_high': round(hi,4),
                'total_pnl': round(sub['profit'].sum(),2),
                'avg_pnl': round(sub['profit'].mean(),2)
            }

print(f"  胜率表: {len(win_rate_table)} 个组合")

with open(f'{DATA_DIR}/win_rate_table.json', 'w') as f:
    # JSON requires string keys
    json_table = {f"{k[0]}||{k[1]}||{k[2]}": v for k, v in win_rate_table.items()}
    json.dump(json_table, f, ensure_ascii=False, indent=2)

# 编码
le_rsi = LabelEncoder(); le_vix = LabelEncoder(); le_otm = LabelEncoder()
all_trades['rsi_enc'] = le_rsi.fit_transform(all_trades['zone_rsi'])
all_trades['vix_enc'] = le_vix.fit_transform(all_trades['zone_vix'])
all_trades['otm_enc'] = le_otm.fit_transform(all_trades['zone_otm'])
all_trades['trend_enc'] = (all_trades['entry_trend'] == '上涨').astype(int)
all_trades['strat_enc'] = (all_trades['strategy_type'] == 'ShortPut').astype(int)

X_cols = ['rsi_enc','vix_enc','otm_enc','trend_enc','strat_enc',
          'entry_rsi','entry_vix','otm_pct','holding_days']
X = all_trades[X_cols].fillna(0).values
y = all_trades['is_win'].astype(int).values

# LR
lr = LogisticRegression(C=0.5, max_iter=200, class_weight='balanced')
lr_cv = cross_val_score(lr, X, y, cv=min(5, len(X)), scoring='roc_auc')
lr.fit(X, y)

# RF
rf = RandomForestClassifier(n_estimators=100, max_depth=4, min_samples_leaf=5,
                            class_weight='balanced', random_state=42)
rf_cv = cross_val_score(rf, X, y, cv=min(5, len(X)), scoring='roc_auc')
rf.fit(X, y)

model_data = {
    'lr': lr, 'rf': rf,
    'le_rsi': le_rsi, 'le_vix': le_vix, 'le_otm': le_otm,
    'X_cols': X_cols, 'n_samples': len(X),
    'lr_auc': round(lr_cv.mean(), 3), 'rf_auc': round(rf_cv.mean(), 3)
}
with open(f'{DATA_DIR}/win_rate_models.pkl', 'wb') as f:
    pickle.dump(model_data, f)

print(f"  LR CV-AUC: {lr_cv.mean():.3f} ± {lr_cv.std():.3f}")
print(f"  RF CV-AUC: {rf_cv.mean():.3f} ± {rf_cv.std():.3f}")
print(f"  胜率表 + 模型已保存到 {DATA_DIR}/")

# ============================================================
# 预测函数
# ============================================================
def predict_win_rate(rsi, vix, otm_pct, trend='上涨', strategy_type='ShortPut',
                     holding_days=14, use_model='lr'):
    """返回预测胜率及详情"""
    rz = zone_rsi(rsi); vz = zone_vix(vix); oz = zone_otm(otm_pct)
    table_data = win_rate_table.get(f"{rz}||{vz}||{oz}", {})

    # 编码
    try:
        rsi_e = le_rsi.transform([rz])[0]
        vix_e = le_vix.transform([vz])[0]
        otm_e = le_otm.transform([oz])[0]
    except:
        rsi_e, vix_e, otm_e = 0, 0, 0
    tc = 1 if trend == '上涨' else 0
    sc = 1 if strategy_type == 'ShortPut' else 0

    X_pred = np.array([[rsi_e, vix_e, otm_e, tc, sc,
                         rsi or 40, vix or 20, otm_pct or -5, holding_days or 14]])
    mdl = model_data[use_model]
    model_wr = mdl.predict_proba(X_pred)[0][1]

    table_wr = table_data.get('win_rate')
    if table_wr is not None:
        final_wr = 0.6 * table_wr + 0.4 * model_wr
    else:
        final_wr = model_wr

    n = table_data.get('n', 0)
    confidence = '高' if n >= 20 else '中' if n >= 5 else '低'

    return {
        'win_rate': round(final_wr, 4),
        'table_wr': table_wr,
        'model_wr': round(model_wr, 4),
        'n': n, 'real_n': table_data.get('real_n', 0),
        'confidence': confidence,
        'ci_low': table_data.get('ci_low'),
        'ci_high': table_data.get('ci_high'),
        'zone_rsi': rz, 'zone_vix': vz, 'zone_otm': oz,
        'avg_pnl': table_data.get('avg_pnl'),
    }

# 测试
print("\n=== 预测测试 ===")
tests = [
    (35.1, 28.2, -7.6, '下跌', 'ShortPut', 14),   # 当前 TSLA 类似
    (55,   16.0, -5.0, '上涨', 'BullPutSpread', 7),
    (28.0, 27.0, -4.0, '下跌', 'ShortPut', 14),
    (50,   20.0, -8.0, '下跌', 'ShortPut', 14),
]
for rsi, vix, otm, trend, strat, hold in tests:
    r = predict_win_rate(rsi, vix, otm, trend, strat, hold)
    print(f"  RSI={rsi} VIX={vix} OTM={abs(otm):.1f}% {trend} {strat}")
    print(f"    → 预测胜率: {r['win_rate']*100:.0f}% | "
          f"表:{'N/A' if r['table_wr'] is None else f'{r['table_wr']*100:.0f}%'} | "
          f"模型: {r['model_wr']*100:.0f}% | "
          f"置信度: {r['confidence']} | "
          f"区间: {r['n']}笔 ({r['real_n']}真实)")

print("\nDone.")
