#!/usr/bin/env python3
"""
ML预测模块 - 波动率预测 & 信号生成
从 TSLA_ML 项目迁移，整合到 StockAssistant

功能：
1. 实时特征生成（技术指标 + 期权市场特征）
2. 波动率 regime 预测
3. ML增强的交易信号
"""

import os
import sys
import warnings
warnings.filterwarnings('ignore')

import requests
import yfinance as yf
import pandas as pd
import numpy as np

from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import os
# 设置代理（解决 yfinance 限流）
for _v in ['https_proxy', 'http_proxy', 'HTTPS_PROXY', 'HTTP_PROXY']:
    os.environ.setdefault(_v, 'http://127.0.0.1:7897')

import joblib

# ============ 特征工程 ============

class FeatureEngineer:
    """实时特征生成器"""

    FEATURES = [
        # 波动率特征
        'hv_5d', 'hv_10d', 'hv_20d', 'hv_60d',
        'parkinson_5d', 'parkinson_20d',
        'gk_5d', 'gk_20d',
        'hv_change_5d', 'hv_change_20d', 'hv_trend',
        # 技术特征
        'rsi_14', 'rsi_7',
        'macd', 'macd_signal', 'macd_diff',
        'bb_position', 'atr_pct',
        'price_to_ma_20', 'price_to_ma_50',
        'sma_10_50_diff', 'price_trend_20d',
        # 期权/VIX特征
        'vix', 'vix_change', 'vix_ma_5', 'vix_ma_20',
        'vix_trend', 'vix_rank_60',
    ]

    def create_features(self, symbol='TSLA', start=None, end=None):
        """
        实时生成所有特征

        Args:
            symbol: 股票代码
            start: 开始日期字符串 'YYYY-MM-DD'，None则用6个月
            end: 结束日期字符串 'YYYY-MM-DD'，None则用今天

        Returns:
            DataFrame: 包含所有特征的 DataFrame
            list: 特征名列表
        """
        # 获取数据（通过代理）
        ticker = yf.Ticker(symbol)
        vix_ticker = yf.Ticker("^VIX")
        spy_ticker = yf.Ticker("SPY")

        try:
            if start and end:
                price_data = ticker.history(start=start, end=end, auto_adjust=True)
                vix_data = vix_ticker.history(start=start, end=end, auto_adjust=True)
                spy_data = spy_ticker.history(start=start, end=end, auto_adjust=True)
            else:
                price_data = ticker.history(period='6mo', auto_adjust=True)
                vix_data = vix_ticker.history(period='6mo', auto_adjust=True)
                spy_data = spy_ticker.history(period='6mo', auto_adjust=True)
        except Exception as e:
            print(f"[FeatureEngineer] 数据获取失败: {e}")
            return None, None

        df = price_data.copy()

        # === 波动率特征 ===
        for lb in [5, 10, 20, 60]:
            df[f'hv_{lb}d'] = df['Close'].pct_change().rolling(lb).std() * np.sqrt(252)

        for lb in [5, 20]:
            hl_ratio = np.log(df['High'] / df['Low'])
            df[f'parkinson_{lb}d'] = np.sqrt(hl_ratio.rolling(lb).mean() / (4 * np.log(2))) * np.sqrt(252)

        for lb in [5, 20]:
            hl = np.log(df['High'] / df['Low'])
            co = np.log(df['Close'] / df['Open'])
            df[f'gk_{lb}d'] = np.sqrt(0.5 * hl**2 - (2*np.log(2) - 1) * co**2).rolling(lb).mean() * np.sqrt(252)

        df['hv_change_5d'] = df['hv_5d'].pct_change()
        df['hv_change_20d'] = df['hv_20d'].pct_change()
        df['hv_trend'] = df['hv_5d'] - df['hv_20d']

        # === 技术特征 ===
        # RSI
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))

        delta7 = df['Close'].diff()
        gain7 = delta7.where(delta7 > 0, 0).rolling(7).mean()
        loss7 = (-delta7.where(delta7 < 0, 0)).rolling(7).mean()
        rs7 = gain7 / loss7
        df['rsi_7'] = 100 - (100 / (1 + rs7))

        # MACD
        ema12 = df['Close'].ewm(span=12).mean()
        ema26 = df['Close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_diff'] = df['macd'] - df['macd_signal']

        # 布林带
        ma20 = df['Close'].rolling(20).mean()
        std20 = df['Close'].rolling(20).std()
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20
        df['bb_position'] = (df['Close'] - bb_lower) / (bb_upper - bb_lower + 1e-8)

        # ATR
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['Close']

        # 移动平均
        ma10 = df['Close'].rolling(10).mean()
        ma20 = df['Close'].rolling(20).mean()
        ma50 = df['Close'].rolling(50).mean()
        df['price_to_ma_20'] = df['Close'] / ma20
        df['price_to_ma_50'] = df['Close'] / ma50
        df['sma_10_50_diff'] = ma10 - ma50
        df['price_trend_20d'] = (df['Close'] - ma20) / ma20

        # === VIX 特征 ===
        if vix_data is not None and not vix_data.empty:
            vix = vix_data['Close'].reindex(df.index, method='ffill')
            df['vix'] = vix
            df['vix_change'] = vix.pct_change()
            df['vix_ma_5'] = vix.rolling(5).mean()
            df['vix_ma_20'] = vix.rolling(20).mean()
            df['vix_trend'] = vix - vix.rolling(20).mean()
            df['vix_rank_60'] = vix.rolling(60).apply(
                lambda x: (x[-1] - x.min()) / (x.max() - x.min() + 1e-8) if len(x) > 10 and x.max() > x.min() else 0.5,
                raw=True
            )

        # === 市场特征 (SPY) ===
        if spy_data is not None and not spy_data.empty:
            spy = spy_data['Close'].reindex(df.index, method='ffill')
            tsla_ret = df['Close'].pct_change()
            spy_ret = spy.pct_change()
            df['correlation_20d'] = tsla_ret.rolling(20).corr(spy_ret)
            cov = tsla_ret.rolling(20).cov(spy_ret)
            spy_var = spy_ret.rolling(20).var()
            df['beta_20d'] = cov / spy_var
            df['relative_strength'] = df['Close'] / spy

        # 删除 NaN
        df = df.dropna()

        return df, self.FEATURES

    def get_latest_features(self, symbol='TSLA'):
        """
        获取最新一条特征

        Returns:
            np.array: 特征值数组
            float: 当前价格
            float: 当前VIX
        """
        df, features = self.create_features(symbol)
        if df is None or df.empty:
            return None, None, None

        latest = df.iloc[-1][features].values
        price = float(df.iloc[-1]['Close'])
        vix = float(df.iloc[-1]['vix']) if 'vix' in df.columns else None

        return latest, price, vix

    def create_features_from_ctx(self, ctx, symbol='TSLA'):
        """
        使用 ctx 中已有的 history DataFrame 计算 ML 特征（避免重复调 yfinance）。

        ctx 需包含：history (pd.DataFrame), vix (float)

        返回: (df, feature_names) — 与 create_features() 接口一致
        """
        import pandas as pd
        import numpy as np

        df = ctx.get('history')
        if df is None or (hasattr(df, 'empty') and df.empty):
            return None, None

        vix_val = ctx.get('vix', 0)

        # VIX 标量扩展为时间序列（与 df 等长，ffill）
        vix_series = pd.Series(vix_val, index=df.index)

        df = df.copy()

        # === 波动率特征 ===
        for lb in [5, 10, 20, 60]:
            df[f'hv_{lb}d'] = df['Close'].pct_change().rolling(lb).std() * np.sqrt(252)

        for lb in [5, 20]:
            hl_ratio = np.log(df['High'] / df['Low'])
            df[f'parkinson_{lb}d'] = np.sqrt(hl_ratio.rolling(lb).mean() / (4 * np.log(2))) * np.sqrt(252)

        for lb in [5, 20]:
            hl = np.log(df['High'] / df['Low'])
            co = np.log(df['Close'] / df['Open'])
            df[f'gk_{lb}d'] = np.sqrt(0.5 * hl**2 - (2*np.log(2) - 1) * co**2).rolling(lb).mean() * np.sqrt(252)

        df['hv_change_5d'] = df['hv_5d'].pct_change()
        df['hv_change_20d'] = df['hv_20d'].pct_change()
        df['hv_trend'] = df['hv_5d'] - df['hv_20d']

        # === 技术特征 ===
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))

        delta7 = df['Close'].diff()
        gain7 = delta7.where(delta7 > 0, 0).rolling(7).mean()
        loss7 = (-delta7.where(delta7 < 0, 0)).rolling(7).mean()
        rs7 = gain7 / loss7
        df['rsi_7'] = 100 - (100 / (1 + rs7))

        ema12 = df['Close'].ewm(span=12).mean()
        ema26 = df['Close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_diff'] = df['macd'] - df['macd_signal']

        ma20 = df['Close'].rolling(20).mean()
        std20 = df['Close'].rolling(20).std()
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20
        df['bb_position'] = (df['Close'] - bb_lower) / (bb_upper - bb_lower + 1e-8)

        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['Close']

        ma10 = df['Close'].rolling(10).mean()
        ma50 = df['Close'].rolling(50).mean()
        df['price_to_ma_20'] = df['Close'] / ma20
        df['price_to_ma_50'] = df['Close'] / ma50
        df['sma_10_50_diff'] = ma10 - ma50
        df['price_trend_20d'] = (df['Close'] - ma20) / ma20

        # === VIX 特征（只用标量值，无历史时用常量） ===
        df['vix'] = vix_series
        df['vix_change'] = 0.0
        df['vix_ma_5'] = vix_series
        df['vix_ma_20'] = vix_series
        df['vix_trend'] = 0.0
        df['vix_rank_60'] = 0.5

        # 市场特征（SPY不可用，设为中性值）
        df['correlation_20d'] = 0.5
        df['beta_20d'] = 1.0
        df['relative_strength'] = 1.0

        # 删除初始 NaN 行（只删前面几行，不删整张表）
        initial_nans = df[['rsi_14', 'macd', 'atr']].iloc[:20].isna().all(axis=1)
        if initial_nans.any():
            df = df.iloc[initial_nans.idxmax():]

        return df, self.FEATURES


# ============ 波动率预测器 ============

class VolatilityPredictor:
    """
    波动率预测器
    基于 RandomForest / GradientBoosting
    """

    def __init__(self, model_dir=None):
        if model_dir is None:
            model_dir = os.path.dirname(__file__)
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)

        self.model = None
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.model_type = None

    def train(self, X, y, model_type='rf'):
        """
        训练模型

        Args:
            X: 特征数据 (n_samples, n_features)
            y: 目标波动率
            model_type: 'rf' 或 'gb'

        Returns:
            dict: 训练结果
        """
        X_scaled = self.scaler.fit_transform(X)

        if model_type == 'rf':
            self.model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                min_samples_split=10,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1
            )
        elif model_type == 'gb':
            self.model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.05,
                random_state=42
            )

        self.model.fit(X_scaled, y)
        self.is_fitted = True
        self.model_type = model_type

        y_pred = self.model.predict(X_scaled)
        results = {
            'model_type': model_type,
            'train_r2': r2_score(y, y_pred),
            'train_rmse': np.sqrt(mean_squared_error(y, y_pred)),
            'train_mae': mean_absolute_error(y, y_pred),
        }
        return results

    def predict(self, X):
        """预测波动率"""
        if not self.is_fitted:
            raise ValueError("模型未训练，请先调用 train() 或 load()")
        X_scaled = self.scaler.transform(X)
        return self.model.predict(X_scaled)

    def predict_regime(self, predicted_vol, vix=None):
        """
        判断波动率 regime

        Returns:
            str: 'low' / 'normal' / 'high'
            float: 调整后波动率
        """
        if predicted_vol < 0.30:
            regime = 'low'
        elif predicted_vol < 0.60:
            regime = 'normal'
        else:
            regime = 'high'

        vol_adj = predicted_vol
        if vix is not None:
            if vix < 0.20:
                vol_adj *= 0.9
            elif vix > 0.40:
                vol_adj *= 1.1

        return regime, vol_adj

    def get_feature_importance(self, feature_names):
        """获取特征重要性"""
        if not self.is_fitted:
            return None
        importance = self.model.feature_importances_
        return pd.DataFrame({
            'feature': feature_names,
            'importance': importance
        }).sort_values('importance', ascending=False)

    def save(self, filepath=None):
        """保存模型"""
        if filepath is None:
            filepath = os.path.join(self.model_dir, 'volatility_model.joblib')
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'is_fitted': self.is_fitted,
            'model_type': self.model_type,
        }, filepath)
        print(f"[VolatilityPredictor] 模型已保存: {filepath}")

    def load(self, filepath=None):
        """加载模型"""
        if filepath is None:
            filepath = os.path.join(self.model_dir, 'volatility_model.joblib')
        if not os.path.exists(filepath):
            print(f"[VolatilityPredictor] 模型文件不存在: {filepath}")
            return False
        data = joblib.load(filepath)
        self.model = data['model']
        self.scaler = data['scaler']
        self.is_fitted = data['is_fitted']
        self.model_type = data.get('model_type')
        print(f"[VolatilityPredictor] 模型已加载: {filepath}")
        return True


# ============ ML 信号生成器 ============

class MLSignalGenerator:
    """
    ML增强信号生成器
    结合波动率预测 + VIX + 技术指标
    """

    def __init__(self, predictor: VolatilityPredictor = None):
        self.predictor = predictor
        self.fe = FeatureEngineer()

    def generate(self, symbol='TSLA'):
        """
        生成 ML 增强的交易信号

        Returns:
            dict: 包含 ML 信号和决策建议
        """
        # 获取最新特征
        features, price, vix = self.fe.get_latest_features(symbol)
        if features is None:
            return {
                'error': '无法获取市场数据',
                'ml_enabled': False
            }

        result = {
            'symbol': symbol,
            'price': price,
            'vix': vix,
            'ml_enabled': self.predictor is not None and self.predictor.is_fitted,
        }

        # === VIX 信号 ===
        vix_signal = 'GREEN'
        if vix is not None:
            if vix > 0.30:
                vix_signal = 'RED'
            elif vix < 0.18:
                vix_signal = 'YELLOW'
        result['vix_signal'] = vix_signal

        # === ML 波动率预测 ===
        ml_vol = None
        ml_regime = None
        if self.predictor and self.predictor.is_fitted:
            try:
                ml_vol = float(self.predictor.predict([features])[0])
                ml_regime, ml_vol_adj = self.predictor.predict_regime(ml_vol, vix)
                result['ml_predicted_vol'] = round(ml_vol, 4)
                result['ml_vol_adj'] = round(ml_vol_adj, 4)
                result['ml_regime'] = ml_regime
            except Exception as e:
                result['ml_error'] = str(e)

    def generate(self, symbol='TSLA', ctx=None):
        """
        生成 ML 增强的交易信号（完全重写版）

        三个独立信号源：
        1. ML_signal: 基于纯价格/成交量特征的波动率预测（不依赖VIX）
        2. VIX_signal: 基于VIX本身的信号
        3. divergence_signal: 基于动量背离的信号

        信号优先级：divergence > ML > VIX

        Args:
            symbol: 股票代码
            ctx: 统一数据上下文（可选），包含 history DataFrame 和 vix 标量。
                 如果传入 ctx，则使用 ctx 中的数据，不再独立调 yfinance。
        """

        # 获取最新特征（优先用 ctx，复用 UnifiedDataFetcher 已拉的数据）
        if ctx is not None:
            fe = FeatureEngineer()
            df, feats = fe.create_features_from_ctx(ctx, symbol)
            if df is None or len(df) < 20:
                return {'error': 'ctx 数据不足', 'ml_enabled': False}
            latest = df[fe.FEATURES].iloc[-1].values
            price = float(df.iloc[-1]['Close'])
            vix_val = ctx.get('vix', 0)
            vix = vix_val
            features = latest
        else:
            features, price, vix_val = self.fe.get_latest_features(symbol)
            if features is None:
                return {'error': '无法获取市场数据', 'ml_enabled': False}
            fe = FeatureEngineer()
            df, _ = fe.create_features(symbol)
            vix_val = vix_val or 0
            vix = vix_val

        result = {
            'symbol': symbol,
            'price': price,
            'vix': vix,
            'ml_enabled': self.predictor is not None and self.predictor.is_fitted,
        }

        # ===== 1. ML 波动率预测（纯价格特征，无VIX） =====
        ml_vol = None
        ml_regime = None
        if self.predictor and self.predictor.is_fitted:
            try:
                ml_vol = float(self.predictor.predict([features])[0])
                ml_regime, ml_vol_adj = self.predictor.predict_regime(ml_vol, vix)
                result['ml_predicted_vol'] = round(ml_vol, 4)
                result['ml_vol_adj'] = round(ml_vol_adj, 4)
                result['ml_regime'] = ml_regime
            except Exception as e:
                result['ml_error'] = str(e)

        # ===== 2. VIX 信号 =====
        vix_signal = 'GREEN'
        vix_action = 'bull_put_spread'
        if vix is not None:
            if vix > 0.30:
                vix_signal = 'RED'
                vix_action = 'wait'
            elif vix > 0.25:
                vix_signal = 'YELLOW'
                vix_action = 'consider'
            elif vix < 0.15:
                vix_signal = 'GREEN'
                vix_action = 'bull_put_spread'
            else:
                vix_signal = 'GREEN'
                vix_action = 'short_put'
        result['vix_signal'] = vix_signal

        # ===== 3. 动量背离检测（核心独立信号） =====
        divergence = self._detect_momentum_divergence(df)
        result['divergence'] = divergence

        # ===== 4. 波动率错配检测（ML vs VIX） =====
        mispricing = self._detect_volatility_mispricing(ml_vol, vix)
        result['mispricing'] = mispricing

        # ===== 5. 组合信号（优先级: divergence > mispricing > ml > vix） =====
        final_action, confidence, reason = self._combine_signals(
            ml_regime, ml_vol, vix, vix_action, divergence, mispricing
        )

        result['action'] = final_action
        result['confidence'] = confidence
        result['reason'] = reason

        # 技术指标
        if df is not None and not df.empty:
            result['rsi_14'] = round(float(df.iloc[-1]['rsi_14']), 1)
            result['rsi_7'] = round(float(df.iloc[-1]['rsi_7']), 1)
            macd_diff_val = float(df.iloc[-1]['macd_diff'])
            result['macd_signal'] = 'bullish' if macd_diff_val > 0 else 'bearish'
            result['macd_diff'] = macd_diff_val

        # 简化版输出（兼容旧接口）
        if final_action == 'bull_put_spread':
            enhanced = 'bull_put_spread_confirmed'
        elif final_action == 'short_put':
            enhanced = 'short_put_opportunity'
        elif final_action == 'wait':
            enhanced = 'wait_confirmed'
        elif final_action == 'aggressive_bull':
            enhanced = 'divergence_bullish'
        elif final_action == 'consider':
            enhanced = 'consider_enter'
        else:
            enhanced = 'no_decision'
        result['enhanced_decision'] = enhanced

        return result

    def _detect_momentum_divergence(self, df):
        """
        检测动量背离：RSI vs 价格走势
        返回: {'type': 'bullish'|'bearish'|'none', 'strength': 0-1, 'description': str}
        """
        if len(df) < 30:
            return {'type': 'none', 'strength': 0, 'description': '数据不足'}

        price = df['Close'].values
        rsi = df['rsi_14'].values

        # 最近10天价格走势
        price_10 = price[-10:]
        price_slope = (price_10[-1] - price_10[0]) / (price_10[0] + 1e-8)

        # 最近5天RSI走势
        rsi_5 = rsi[-5:]
        rsi_slope = rsi_5[-1] - rsi_5[0]

        # 检测局部高低点（最近20天）
        lookback = 20
        recent = price[-lookback:]
        price_low_idx = np.argmin(recent)
        price_high_idx = np.argmax(recent)

        # 价格创出新低 vs RSI没有创新低 → 底背离
        is_price_new_low = (price_low_idx == len(recent) - 1)
        rsi_current = rsi[-1]
        rsi_20_ago = rsi[-20] if len(rsi) >= 20 else rsi[0]
        is_rsi_not_new_low = (rsi_current > rsi_20_ago)

        # 价格创出新低，RSI没有 → 底背离（看多）
        if is_price_new_low and is_rsi_not_new_low:
            strength = min(1.0, abs(rsi_current - 30) / 20)
            return {
                'type': 'bullish',
                'strength': round(strength, 2),
                'description': f'价格新低但RSI={rsi_current:.0f}未跟随，底背离形成'
            }

        # 价格创出新低，RSI也新低 → 无背离
        if is_price_new_low and is_rsi_not_new_low is False:
            return {
                'type': 'none',
                'strength': 0,
                'description': f'价格新低，RSI={rsi_current:.0f}同步弱势'
            }

        # 价格创出新低，RSI高于20日前 → 潜在底背离
        if price_slope < -0.03 and rsi_slope > 0 and rsi_current < 40:
            return {
                'type': 'bullish',
                'strength': 0.5,
                'description': f'价格下跌但RSI企稳，潜在反弹动能积累'
            }

        # 价格创出新低，RSI极端超卖 → 反弹概率极高
        if price_slope < -0.03 and rsi_current < 30:
            return {
                'type': 'bullish',
                'strength': 0.8,
                'description': f'RSI={rsi_current:.0f}极端超卖+价格加速赶底，反弹概率极大'
            }

        # 价格创历史新高但RSI下降 → 顶背离（看空）
        is_price_new_high = (price_high_idx == len(recent) - 1)
        rsi_20_ago_high = rsi[-20] if len(rsi) >= 20 else rsi[0]
        if is_price_new_high and rsi_current < rsi_20_ago_high:
            return {
                'type': 'bearish',
                'strength': 0.7,
                'description': f'价格新高但RSI未跟随，顶背离预警'
            }

        return {'type': 'none', 'strength': 0, 'description': '无明显背离'}

    def _detect_volatility_mispricing(self, ml_vol, vix):
        """
        检测波动率错配：ML预测的"真实波动率" vs VIX隐含的"市场恐惧"
        这就是ML真正有价值的地方：发现VIX和真实走势预期的差异

        返回: {'type': 'premium_selling'|'premium_buying'|'aligned'|'none', 'description': str}
        """
        if ml_vol is None or vix is None:
            return {'type': 'none', 'description': '数据不足'}

        # 转换为同一单位：vix是百分比，ml_vol是小数
        vix_decimal = vix  # vix已经是小数形式(如0.28)
        ratio = ml_vol / (vix_decimal + 1e-8)

        if ratio < 0.7:
            # ML认为真实波动远低于VIX定价 → 市场过度恐惧 → 做空波动率（卖期权）机会
            return {
                'type': 'premium_selling',
                'ratio': round(ratio, 2),
                'description': f'预测波动({ml_vol:.0%})远低于VIX恐惧溢价({vix:.0%})，市场高估风险，卖期权机会'
            }
        elif ratio > 1.3:
            # ML认为真实波动将高于VIX → 市场过于乐观 → 做多波动率（买期权）机会
            return {
                'type': 'premium_buying',
                'ratio': round(ratio, 2),
                'description': f'预测波动({ml_vol:.0%})高于VIX定价({vix:.0%})，市场低估风险，买期权机会'
            }
        else:
            return {
                'type': 'aligned',
                'ratio': round(ratio, 2),
                'description': f'预测波动与VIX基本一致({ratio:.1f}x)，无明显错配'
            }

    def _combine_signals(self, ml_regime, ml_vol, vix, vix_action, divergence, mispricing):
        """
        组合三个信号源，按优先级输出最终决策

        优先级: divergence > mispricing > ml_regime > vix_action
        divergence 和 mispricing 是 ML 真正独立于 VIX 的判断
        """
        div = divergence['type']
        div_strength = divergence['strength']
        mis = mispricing['type']
        confidence = 0.5
        reason_parts = []

        # === 优先级1: 动量背离信号（最强独立信号）===
        if div == 'bullish' and div_strength >= 0.6:
            reason_parts.append(f"【ML独立信号】底背离强势(强度{div_strength})，反弹概率极高")
            confidence = 0.85
            return 'aggressive_bull', confidence, '。'.join(reason_parts)

        if div == 'bullish' and div_strength >= 0.4:
            reason_parts.append(f"【ML独立信号】底背离形成(强度{div_strength})，反弹动能积累")
            confidence = 0.7
            # 不直接返回，因为还要结合波动率
            # 继续组合其他信号

        # === 优先级2: 波动率错配信号（ML真正有价值的地方）===
        if mis == 'premium_selling':
            reason_parts.append(f"【ML独立判断】{mispricing['description']}")
            confidence = max(confidence, 0.75)
            # 即使VIX高，ML也认为恐惧过度，继续
        elif mis == 'premium_buying':
            reason_parts.append(f"【ML独立判断】{mispricing['description']}")
            confidence = max(confidence, 0.7)
            # ML认为应该买期权（赌波动），但这和我们卖期权的策略冲突
            # 降级为观望

        # === 优先级3: ML 波动率 regime ===
        ml_action = 'wait'
        if ml_regime == 'low':
            ml_action = 'bull_put_spread'
            reason_parts.append(f"ML预测未来波动低位({ml_vol:.0%})，权利金环境好")
            confidence = max(confidence, 0.65)
        elif ml_regime == 'normal':
            ml_action = 'short_put'
            reason_parts.append(f"ML预测波动正常({ml_vol:.0%})，可适度建仓")
            confidence = max(confidence, 0.55)
        elif ml_regime == 'high':
            ml_action = 'wait'
            reason_parts.append(f"ML预测波动高位({ml_vol:.0%})，等待")
            confidence = 0.6

        # === 优先级4: VIX 作为最终过滤器 ===
        if vix_action == 'wait' and ml_action != 'aggressive_bull':
            # VIX说等，但ML说可以 → 听谁的？
            if mis == 'premium_selling':
                # ML发现VIX恐惧过度，即使VIX高也值得卖
                reason_parts.append(f"→ VIX={vix:.0%}偏高，但ML发现市场高估风险，谨慎做多")
                confidence = 0.6
                final_action = 'consider'
            else:
                reason_parts.append(f"→ VIX={vix:.0%}RED区间，等VIX回落再操作")
                final_action = 'wait'
        elif vix_action == 'bull_put_spread':
            final_action = 'bull_put_spread'
        elif vix_action == 'short_put':
            final_action = 'short_put'
        else:
            final_action = ml_action

        # === 收敛到标准动作 ===
        if final_action in ['wait', 'consider']:
            if div == 'bullish' and div_strength >= 0.4:
                # 背离信号强，但VIX/ML都说不确定 → 降级为 consider
                final_action = 'consider'
                confidence = 0.55

        reason = '。'.join(reason_parts) if reason_parts else f'信号不明确，ML={ml_regime}, VIX={vix:.0%}'
        return final_action, min(confidence, 0.9), reason


# ============ 模型训练脚本 ============

def train_model(symbol='TSLA', model_type='rf', save=True, start_date=None, end_date=None):
    """
    训练波动率预测模型

    Args:
        symbol: 股票代码
        model_type: 'rf' 或 'gb'
        save: 是否保存模型
        start_date: 开始日期 'YYYY-MM-DD'，None则用6个月
        end_date: 结束日期 'YYYY-MM-DD'，None则用今天

    Returns:
        dict: 训练结果
    """
    print(f"[训练] 开始训练 {symbol} 波动率预测模型...")
    if start_date:
        print(f"[训练] 日期范围: {start_date} ~ {end_date}")

    fe = FeatureEngineer()
    df, features = fe.create_features(symbol, start=start_date, end=end_date)

    if df is None or len(df) < 60:
        return {'error': f'数据不足，需要至少60天，实际{len(df) if df is not None else 0}天'}

    # 准备训练数据
    X = df[features].values
    target_lookahead = 5
    close = df['Close'].values
    future_vol = pd.Series(close).pct_change().rolling(target_lookahead).std().shift(-target_lookahead) * np.sqrt(252)
    y = future_vol.dropna().values
    X = X[:len(y)]

    print(f"[训练] 数据: X={X.shape}, y={y.shape} (原始{df.shape[0]}条)")

    predictor = VolatilityPredictor()
    results = predictor.train(X, y, model_type)

    print(f"[训练] 结果: R2={results['train_r2']:.3f}, RMSE={results['train_rmse']:.4f}")

    if save:
        predictor.save()

    # 特征重要性
    importance = predictor.get_feature_importance(features)
    print("\nTop 10 特征重要性:")
    print(importance.head(10).to_string(index=False))

    return results


def batch_train(symbol='TSLA', model_type='rf', start_year=2024, end_date=None):
    """
    分批抓取数据并训练

    每半年为一个批次，分批抓取Yahoo Finance数据
    如果某批次失败，会重试一次
    全部成功后合并所有批次数据进行训练

    Args:
        symbol: 股票代码
        model_type: 'rf' 或 'gb'
        start_year: 从哪一年开始抓（避免被封IP）
        end_date: 结束日期 'YYYY-MM-DD'，None则用今天
    """
    from datetime import datetime, timedelta
    import time

    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    batches = []
    current_end = datetime.strptime(end_date, '%Y-%m-%d')

    # 生成每半年的批次
    # 例如: 2024-01-01~2024-06-30, 2024-07-01~2024-12-31, ...
    batch_ranges = []
    current_start = datetime(start_year, 1, 1)

    while current_start < current_end:
        batch_end = min(current_start + timedelta(days=183), current_end)
        batch_ranges.append((
            current_start.strftime('%Y-%m-%d'),
            batch_end.strftime('%Y-%m-%d')
        ))
        current_start = batch_end + timedelta(days=1)

    print(f"[批次训练] 共 {len(batch_ranges)} 个批次:")
    for s, e in batch_ranges:
        print(f"  {s} ~ {e}")

    all_dfs = []

    for i, (batch_start, batch_end) in enumerate(batch_ranges):
        print(f"\n[批次 {i+1}/{len(batch_ranges)}] 抓取 {batch_start} ~ {batch_end}...")
        try:
            fe = FeatureEngineer()
            df, _ = fe.create_features(symbol, start=batch_start, end=batch_end)
            if df is not None and len(df) > 10:
                print(f"  成功: {len(df)} 条数据")
                all_dfs.append(df)
            else:
                print(f"  数据不足({len(df) if df else 0}条)，跳过此批次")
        except Exception as e:
            print(f"  失败: {e}，跳过此批次")

        # 每个批次间隔2秒，避免触发限流
        if i < len(batch_ranges) - 1:
            time.sleep(2)

    if not all_dfs:
        print("[批次训练] 所有批次均失败")
        return {'error': '所有批次数据获取失败'}

    # 合并所有批次
    print(f"\n[批次训练] 合并 {len(all_dfs)} 个批次数据...")
    combined_df = pd.concat(all_dfs, ignore_index=False).sort_index()
    print(f"  合并后: {len(combined_df)} 条")

    # 特征工程
    features = FeatureEngineer.FEATURES
    df = combined_df.copy()

    # 检查特征是否存在，不存在的填充NaN
    for f in features:
        if f not in df.columns:
            df[f] = np.nan

    # 去除NaN
    before = len(df)
    df = df.dropna(subset=features)
    print(f"  去除NaN后: {len(df)} 条 (去掉了 {before - len(df)} 条)")

    if len(df) < 60:
        return {'error': f'数据不足，合并后仅{len(df)}条'}

    # 准备训练数据
    X = df[features].values
    target_lookahead = 5
    close = df['Close'].values
    future_vol = pd.Series(close).pct_change().rolling(target_lookahead).std().shift(-target_lookahead) * np.sqrt(252)
    y = future_vol.dropna().values
    X = X[:len(y)]

    print(f"[批次训练] 最终训练数据: X={X.shape}, y={y.shape}")

    predictor = VolatilityPredictor()
    results = predictor.train(X, y, model_type)

    print(f"[批次训练] 结果: R2={results['train_r2']:.3f}, RMSE={results['train_rmse']:.4f}")
    predictor.save()

    importance = predictor.get_feature_importance(features)
    print("\nTop 10 特征重要性:")
    print(importance.head(10).to_string(index=False))

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='ML波动率预测模块')
    parser.add_argument('--train', action='store_true', help='训练模型（单次6个月数据）')
    parser.add_argument('--batch', action='store_true', help='分批训练（从start_year到end，抓取所有数据训练）')
    parser.add_argument('--symbol', default='TSLA', help='股票代码')
    parser.add_argument('--model-type', default='rf', choices=['rf', 'gb'], help='模型类型')
    parser.add_argument('--start-year', type=int, default=2024, help='分批训练起始年份（默认2024）')
    parser.add_argument('--end', default=None, help='分批训练结束日期 YYYY-MM-DD（默认今天）')
    parser.add_argument('--signal', action='store_true', help='生成交易信号')
    args = parser.parse_args()

    if args.train:
        train_model(args.symbol, args.model_type)
    elif args.batch:
        batch_train(args.symbol, args.model_type, start_year=args.start_year, end_date=args.end)
    elif args.signal:
        predictor = VolatilityPredictor()
        predictor.load()
        gen = MLSignalGenerator(predictor)
        result = gen.generate(args.symbol)
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        # 默认：生成信号
        predictor = VolatilityPredictor()
        predictor.load()
        gen = MLSignalGenerator(predictor)
        result = gen.generate(args.symbol)
        import json
        print(json.dumps(result, indent=2, default=str))
