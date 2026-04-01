"""
胜率预测模块
加载胜率表 + ML模型，提供 predict_win_rate() 接口
"""
import os
import json
import pickle
import numpy as np

DATA_DIR = '/root/.openclaw/workspace/quant/QuantML/data'
_MODEL_CACHE = None
_TABLE_CACHE = None

def zone_rsi(r):
    if r is None or (isinstance(r, float) and np.isnan(r)): return 'RSI<30'
    if r < 30: return 'RSI<30'
    if r < 40: return 'RSI30-40'
    if r < 60: return 'RSI40-60'
    return 'RSI>60'

def zone_vix(v):
    if v is None or (isinstance(v, float) and np.isnan(v)): return 'VIX15-20'
    if v < 15: return 'VIX<15'
    if v < 20: return 'VIX15-20'
    if v < 25: return 'VIX20-25'
    return 'VIX>25'

def zone_otm(o):
    if o is None or (isinstance(o, float) and np.isnan(o)): return 'OTM5-7'
    if o < -10: return 'OTM>10'
    if o < -7: return 'OTM7-10'
    if o < -5: return 'OTM5-7'
    if o < -3: return 'OTM3-5'
    return 'ITM<3'

def _load():
    global _MODEL_CACHE, _TABLE_CACHE
    if _TABLE_CACHE is None:
        json_path = os.path.join(DATA_DIR, 'win_rate_table.json')
        if os.path.exists(json_path):
            with open(json_path) as f:
                raw = json.load(f)
            _TABLE_CACHE = raw
        else:
            _TABLE_CACHE = {}
    return _TABLE_CACHE

def predict_win_rate(rsi, vix, otm_pct, trend='上涨', strategy_type='ShortPut',
                    holding_days=14, use_model='lr'):
    """
    返回: {win_rate, confidence, n, real_n, table_wr, model_wr, ci_low, ci_high, avg_pnl}
    """
    table = _load()
    rz = zone_rsi(rsi)
    vz = zone_vix(vix)
    oz = zone_otm(otm_pct)
    key = f"{rz}||{vz}||{oz}"
    table_data = table.get(key, {})

    model_wr = None
    if _MODEL_CACHE is not None:
        mdl = _MODEL_CACHE[use_model]
        try:
            rsi_e = mdl['le_rsi'].transform([rz])[0]
            vix_e = mdl['le_vix'].transform([vz])[0]
            otm_e = mdl['le_otm'].transform([oz])[0]
        except Exception:
            rsi_e, vix_e, otm_e = 0, 0, 0
        tc = 1 if trend == '上涨' else 0
        sc = 1 if strategy_type == 'ShortPut' else 0
        X_pred = np.array([[rsi_e, vix_e, otm_e, tc, sc,
                             rsi or 40, vix or 20, otm_pct or -5, holding_days or 14]])
        try:
            model_wr = mdl['model'].predict_proba(X_pred)[0][1]
        except Exception:
            model_wr = None

    table_wr = table_data.get('win_rate')
    n = table_data.get('n', 0)

    # 优先用查表权重（282笔中真实交易34笔，查表更可靠）
    if table_wr is not None:
        if model_wr is not None:
            final_wr = 0.7 * table_wr + 0.3 * model_wr  # 查表权重更高
        else:
            final_wr = table_wr
    elif model_wr is not None:
        final_wr = model_wr
    else:
        final_wr = 0.65  # 默认65%

    if n >= 20: confidence = '高'
    elif n >= 5: confidence = '中'
    else: confidence = '低'

    return {
        'win_rate': round(final_wr, 4),
        'table_wr': table_wr,
        'model_wr': round(model_wr, 4) if model_wr else None,
        'confidence': confidence,
        'n': n,
        'real_n': table_data.get('real_n', 0),
        'ci_low': table_data.get('ci_low'),
        'ci_high': table_data.get('ci_high'),
        'avg_pnl': table_data.get('avg_pnl'),
        'zone_rsi': rz, 'zone_vix': vz, 'zone_otm': oz,
    }


def load_models():
    """延迟加载 ML 模型（可选，模型较弱时跳过）"""
    global _MODEL_CACHE
    pkl_path = os.path.join(DATA_DIR, 'win_rate_models.pkl')
    if os.path.exists(pkl_path) and _MODEL_CACHE is None:
        with open(pkl_path, 'rb') as f:
            _MODEL_CACHE = pickle.load(f)
        print(f"[胜率模型] 已加载 (LR AUC={_MODEL_CACHE['lr_auc']}, RF AUC={_MODEL_CACHE['rf_auc']})")
    return _MODEL_CACHE
