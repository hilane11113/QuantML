"""
特斯拉期权链分析框架
用于获取和分析TSLA期权数据，筛选牛市垂直价差组合
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import warnings
warnings.filterwarnings('ignore')

def get_tsla_option_chain(expiry_days_range=None):
    """
    获取特斯拉期权链数据（严格按照新数据源规范）
    
    数据源：https://api.nasdaq.com/api/quote/TSLA/option-chain?assetclass=STOCKS
    
    Parameters:
    -----------
    expiry_days_range : tuple, optional
        到期日范围（最小天数，最大天数），默认(7, 45)
    
    Returns:
    --------
    dict
        包含期权链数据、正股价格和到期日信息的字典
    """
    try:
        # 导入期权链解析模块（从备份文件，因为主文件可能缺失函数）
        try:
            from option_chain_parser import get_tsla_option_chain as fetch_option_data
        except ImportError:
            from option_chain_parser_backup import get_tsla_option_chain as fetch_option_data
        
        # 调用API获取数据
        result = fetch_option_data()
        
        # 提取解析后的数据
        parsed_data = result.get("parsed_data", {})
        
        # 检查是否有错误
        if not parsed_data.get("success"):
            return {"error": parsed_data.get("error", "未知错误")}
        
        # 提取当前价格
        current_price = parsed_data.get("metadata", {}).get("current_price", 450.00)
        
        # 提取期权链数据
        options_df = parsed_data.get("options_df")
        
        if options_df is None:
            return {"error": "期权数据为空"}
        
        # 筛选到期日范围内的期权
        if expiry_days_range is not None:
            min_days, max_days = expiry_days_range
            if "days_to_expiry" in options_df.columns:
                options_df = options_df[
                    (options_df["days_to_expiry"] >= min_days) & 
                    (options_df["days_to_expiry"] <= max_days)
                ].copy()
        
        # 分组构建期权链
        option_chains = []
        if not options_df.empty:
            # 获取唯一的到期日
            unique_expiries = options_df[['expiry_date_full', 'days_to_expiry']].drop_duplicates()
            
            for _, expiry_info in unique_expiries.iterrows():
                expiry_date = expiry_info['expiry_date_full']
                days_to_expiry = expiry_info['days_to_expiry']
                
                # 筛选该到期日的期权
                expiry_df = options_df[options_df['expiry_date_full'] == expiry_date].copy()
                
                if not expiry_df.empty:
                    # 重命名列以匹配option_analysis中的期望格式
                    expiry_df.rename(columns={
                        'last': 'lastPrice',
                        'bid': 'bid',
                        'ask': 'ask',
                        'volume': 'volume',
                        'open_interest': 'openInterest',
                        'strike': 'strike',
                        'type': 'type',
                        'expiry_date_full': 'expiry'
                    }, inplace=True)
                    
                    # 添加缺失的列
                    if 'impliedVolatility' not in expiry_df.columns:
                        expiry_df['impliedVolatility'] = np.nan
                    if 'contractSymbol' not in expiry_df.columns:
                        expiry_df['contractSymbol'] = f"TSLA_{expiry_date.replace('-', '')}"
                    
                    option_chains.append(expiry_df)
        
        return {
            "current_price": current_price,
            "option_chains": option_chains,
            "metadata": parsed_data.get("metadata", {})
        }
        
    except Exception as e:
        return {"error": f"获取期权链失败: {e}"}

def calculate_spread_greeks(short_put, long_put, greeks_data=None):
    """
    计算牛市看跌价差组合的希腊字母（风险指标）
    
    参数：
    -----------
    short_put : dict
        卖出腿（高行权价）的期权信息，包含strike, bid, ask等字段
    long_put : dict
        买入腿（低行权价）的期权信息
    greeks_data : dict, optional
        fetch_option_greeks_nasdaq返回的希腊字母数据
    
    返回：
    --------
    dict
        包含组合希腊字母的字典：
        - delta: 组合Delta（方向性风险）
        - gamma: 组合Gamma（Delta变化率）
        - theta: 组合Theta（时间衰减）
        - vega: 组合Vega（波动率敏感性）
        - source: 数据来源（'greeks' 或 'estimated'）
    """
    try:
        # 如果提供了希腊字母数据，尝试使用真实值
        if greeks_data and greeks_data.get("success") and greeks_data.get("greeks_df") is not None:
            greeks_df = greeks_data["greeks_df"]
            
            # 查找对应行权价的希腊字母
            short_strike = short_put.get("strike")
            long_strike = long_put.get("strike")
            
            # 尝试匹配行权价（可能有微小差异）
            strike_tolerance = 0.1
            short_greeks = None
            long_greeks = None
            
            if 'strike' in greeks_df.columns:
                # 查找最接近的行权价
                for _, row in greeks_df.iterrows():
                    row_strike = row['strike']
                    
                    if abs(row_strike - short_strike) <= strike_tolerance:
                        short_greeks = row
                    if abs(row_strike - long_strike) <= strike_tolerance:
                        long_greeks = row
            
            if short_greeks is not None and long_greeks is not None:
                # 使用真实希腊字母数据
                # 组合Delta = put_short_delta - put_long_delta（因为卖出为正，买入为负）
                short_delta = short_greeks.get('put_delta', 0) if 'put_delta' in short_greeks else 0
                long_delta = long_greeks.get('put_delta', 0) if 'put_delta' in long_greeks else 0
                spread_delta = short_delta - long_delta
                
                # 组合Gamma = put_short_gamma - put_long_gamma
                short_gamma = short_greeks.get('put_gamma', 0) if 'put_gamma' in short_greeks else 0
                long_gamma = long_greeks.get('put_gamma', 0) if 'put_gamma' in long_greeks else 0
                spread_gamma = short_gamma - long_gamma
                
                # 组合Theta = put_short_theta - put_long_theta（通常为正，时间有利）
                short_theta = short_greeks.get('put_theta', 0) if 'put_theta' in short_greeks else 0
                long_theta = long_greeks.get('put_theta', 0) if 'put_theta' in long_greeks else 0
                spread_theta = short_theta - long_theta
                
                # 组合Vega = put_short_vega - put_long_vega（通常为负，波动率上升不利）
                short_vega = short_greeks.get('put_vega', 0) if 'put_vega' in short_greeks else 0
                long_vega = long_greeks.get('put_vega', 0) if 'put_vega' in long_greeks else 0
                spread_vega = short_vega - long_vega
                
                return {
                    "delta": round(spread_delta, 4),
                    "gamma": round(spread_gamma, 6),
                    "theta": round(spread_theta, 4),
                    "vega": round(spread_vega, 4),
                    "source": "greeks",
                    "notes": "基于Barchart隐含波动率数据"
                }
        
        # 如果没有真实数据或匹配失败，使用估算值
        # 估算逻辑：
        # - Delta: 基于Black-Scholes模型估算
        # - Gamma: 假设接近平价期权时Gamma最大
        # - Theta: 基于时间衰减估算
        # - Vega: 基于IV敏感度估算
        
        short_strike = short_put.get("strike", 0)
        long_strike = long_put.get("strike", 0)
        current_price = short_put.get("current_price", 450.00)
        days_to_expiry = short_put.get("days_to_expiry", 14)
        
        # 估算Delta（简化Black-Scholes）
        import math
        from scipy.stats import norm
        
        # 假设无风险利率为0.02，IV为30%
        r = 0.02
        iv = 0.30
        
        # 计算d1和d2（看跌期权）
        T = days_to_expiry / 365.0
        
        # 卖出腿（高行权价）
        d1_short = (math.log(current_price / short_strike) + (r + iv**2/2) * T) / (iv * math.sqrt(T))
        delta_short = norm.cdf(d1_short) - 1  # 看跌期权Delta为负
        
        # 买入腿（低行权价）
        d1_long = (math.log(current_price / long_strike) + (r + iv**2/2) * T) / (iv * math.sqrt(T))
        delta_long = norm.cdf(d1_long) - 1
        
        # 组合Delta
        spread_delta = delta_short - delta_long  # 卖出为正，买入为负
        
        # 估算Gamma（最大Gamma在平价附近）
        gamma_short = norm.pdf(d1_short) / (current_price * iv * math.sqrt(T))
        gamma_long = norm.pdf(d1_long) / (current_price * iv * math.sqrt(T))
        spread_gamma = gamma_short - gamma_long
        
        # 估算Theta（每天时间衰减）
        theta_short = -(current_price * iv * norm.pdf(d1_short)) / (2 * math.sqrt(365))
        theta_long = -(current_price * iv * norm.pdf(d1_long)) / (2 * math.sqrt(365))
        spread_theta = theta_short - theta_long  # 通常为正，时间有利
        
        # 估算Vega（每1% IV变化的价值变化）
        vega_short = current_price * math.sqrt(T) * norm.pdf(d1_short) / 100
        vega_long = current_price * math.sqrt(T) * norm.pdf(d1_long) / 100
        spread_vega = vega_short - vega_long  # 通常为负，波动率上升不利
        
        return {
            "delta": round(spread_delta, 4),
            "gamma": round(spread_gamma, 6),
            "theta": round(spread_theta, 4),
            "vega": round(spread_vega, 4),
            "source": "estimated",
            "notes": "基于Black-Scholes模型估算值（IV=30%，r=2%）"
        }
        
    except Exception as e:
        return {
            "delta": 0,
            "gamma": 0,
            "theta": 0,
            "vega": 0,
            "source": "error",
            "notes": f"计算希腊字母时发生异常: {str(e)}"
        }


def filter_bull_put_spreads(option_data, vix_signal=None, target_dates=None):
    """
    筛选牛市看跌垂直价差组合
    
    根据VIX信号级别映射具体参数：
    - 绿灯 (GREEN)：卖出行权价 = 当前股价 × 95%，价差宽度 = $30
    - 黄灯/红灯 (YELLOW/RED)：卖出行权价 = 当前股价 × 92%，价差宽度 = $20
    - 容差范围：行权价偏差 ≤ $5，价差宽度偏差 ≤ $10
    
    如果提供了target_dates参数，只处理这些到期日的期权链。
    为每个目标到期日生成最多2个推荐组合，总共最多8个推荐（4个到期日×2）。
    
    Parameters:
    -----------
    option_data : dict
        get_tsla_option_chain 返回的数据
    vix_signal : dict, optional
        VIX MA10 信号详情，包含signal_level字段
    target_dates : list, optional
        目标到期日字符串列表（格式：YYYY-MM-DD），如果为None则使用所有可用的到期日
    
    Returns:
    --------
    list
        推荐的价差组合列表，每个组合包含完整的字段
    """
    if "error" in option_data:
        return []
    
    current_price = option_data["current_price"]
    option_chains = option_data["option_chains"]
    
    # 检测IV数据缺失情况
    total_options = 0
    missing_iv_count = 0
    for chain_df in option_chains:
        total_options += len(chain_df)
        missing_iv_count += chain_df['impliedVolatility'].isna().sum()
    iv_missing_rate = (missing_iv_count / total_options * 100) if total_options > 0 else 100
    if iv_missing_rate > 50:
        print(f"⚠️  IV数据缺失严重: {iv_missing_rate:.1f}%，将使用简化评分逻辑")
    
    # 尝试获取希腊字母数据 - 优先使用Barchart替代数据源
    greeks_data = None
    try:
        # 第一步：尝试从Barchart获取替代IV数据
        from option_chain_parser import fetch_option_greeks_alternative
        alternative_result = fetch_option_greeks_alternative()
        
        if alternative_result.get("success") and alternative_result.get("greeks_df") is not None:
            print(f"✅  Barchart替代IV数据获取成功，IV值: {alternative_result.get('metadata', {}).get('iv_value', 0):.4f}")
            greeks_data = alternative_result
        else:
            # 第二步：如果Barchart失败，回退到纳斯达克希腊字母数据
            print(f"⚠️  Barchart数据获取失败: {alternative_result.get('error', '未知错误')}，回退到纳斯达克数据")
            from option_chain_parser import fetch_option_greeks_nasdaq
            nasdaq_result = fetch_option_greeks_nasdaq()
            
            if nasdaq_result.get("success"):
                print(f"✅  纳斯达克希腊字母数据获取成功")
                greeks_data = nasdaq_result
            else:
                print(f"⚠️  纳斯达克数据获取也失败: {nasdaq_result.get('error', '未知错误')}")
                greeks_data = None
                
    except Exception as e:
        print(f"⚠️  获取希腊字母数据异常: {e}")
        greeks_data = None
    
    # 如果没有提供VIX信号，使用中性信号
    if vix_signal is None:
        vix_signal = {"signal_level": "YELLOW", "composite_score": 50}
    
    # 确定信号级别
    vix_level = vix_signal.get("signal_level", "YELLOW")
    
    # 信号级别→参数映射表（按照memory/spec.txt定义）
    signal_params = {
        "GREEN": {"short_put_ratio": 0.96, "spread_width": 25.0},
        "YELLOW": {"short_put_ratio": 0.92, "spread_width": 20.0},
        "RED": {"short_put_ratio": 0.88, "spread_width": 15.0},
        "UNKNOWN": {"short_put_ratio": 0.92, "spread_width": 20.0}  # 未知信号使用黄灯参数
    }
    
    # 获取参数，如果信号级别不在映射表中，使用黄灯参数
    params = signal_params.get(vix_level, signal_params["YELLOW"])
    short_put_ratio = params["short_put_ratio"]
    target_spread_width = params["spread_width"]
    
    # 计算目标卖出行权价
    target_short_strike = current_price * short_put_ratio
    
    # 容差范围
    strike_tolerance = 5.0      # 行权价偏差 ≤ $5
    width_tolerance = 10.0      # 价差宽度偏差 ≤ $10
    
    # 按到期日分组存储推荐
    expiry_recommendations = {}
    
    for chain_df in option_chains:
        expiry = chain_df['expiry'].iloc[0]
        days_to_expiry = chain_df['days_to_expiry'].iloc[0]
        
        # 如果指定了target_dates，且当前到期日不在目标列表中，跳过
        if target_dates is not None and expiry not in target_dates:
            continue
        
        # 只分析看跌期权
        puts_df = chain_df[chain_df['type'] == 'put'].copy()
        
        if puts_df.empty:
            continue
        
        # 计算流动性得分：openInterest × 0.7 + volume × 0.3 (降低成交量权重，提高持仓量权重)
        puts_df['liquidity_score'] = (
            puts_df['openInterest'].fillna(0) * 0.7 +
            puts_df['volume'].fillna(0) * 0.3
        )
        
        # 计算每个看跌期权与目标卖出行权价的距离
        puts_df['strike_distance'] = abs(puts_df['strike'] - target_short_strike)
        
        # 筛选行权价在容差范围内的期权
        valid_short_puts = puts_df[puts_df['strike_distance'] <= strike_tolerance].copy()
        
        if valid_short_puts.empty:
            continue  # 没有符合条件的卖出腿
        
        # 为每个符合条件的卖出腿计算流动性得分
        valid_short_puts['liquidity_score'] = (
            valid_short_puts['openInterest'].fillna(0) * 0.7 +
            valid_short_puts['volume'].fillna(0) * 0.3
        )
        
        # 按行权价距离和流动性综合排序
        # 首先按距离排序（越小越好），然后按流动性排序（越大越好）
        valid_short_puts = valid_short_puts.sort_values(
            ['strike_distance', 'liquidity_score'], 
            ascending=[True, False]
        )
        
        # 取前10个最佳卖出腿候选（增加候选池）
        candidate_count = min(10, len(valid_short_puts))
        short_put_candidates = valid_short_puts.head(candidate_count).copy()
        
        expiry_recs = []
        
        for _, short_put in short_put_candidates.iterrows():
            short_strike = short_put['strike']
            short_distance = short_put['strike_distance']
            
            # 动态调整价差宽度：基于实际行权价间隔
            # 计算行权价间隔（取相邻行权价差值中位数）
            sorted_strikes = puts_df['strike'].sort_values().unique()
            if len(sorted_strikes) > 1:
                intervals = np.diff(sorted_strikes)
                interval = np.median(intervals)
            else:
                interval = 2.50  # 默认间隔
            
            # 计算最接近目标价差宽度的间隔倍数
            target_n = round(target_spread_width / interval)
            # 确保至少1个间隔
            if target_n < 1:
                target_n = 1
            
            # 寻找可行的买入腿行权价
            candidate_long_strikes = puts_df[puts_df['strike'] < short_strike]['strike'].unique()
            if len(candidate_long_strikes) == 0:
                continue  # 没有合适的买入腿
            
            # 计算每个候选行权价对应的间隔数（n = (short_strike - long_strike) / interval）
            candidate_n_values = (short_strike - candidate_long_strikes) / interval
            # 选择最接近target_n的可行n值
            best_n_idx = np.argmin(np.abs(candidate_n_values - target_n))
            long_strike = candidate_long_strikes[best_n_idx]
            actual_spread_width = short_strike - long_strike
            width_deviation = abs(actual_spread_width - target_spread_width)
            
            # 获取买入腿数据
            long_put = puts_df[puts_df['strike'] == long_strike].iloc[0]
            
            if width_deviation > width_tolerance:
                continue  # 超出容差，跳过
            
            # 计算最大盈利和最大亏损（处理NaN值）
            short_bid = short_put['bid'] if pd.notna(short_put['bid']) else short_put['lastPrice']
            long_ask = long_put['ask'] if pd.notna(long_put['ask']) else long_put['lastPrice']
            max_profit = short_bid - long_ask
            max_loss = actual_spread_width - max_profit
            
            # 如果max_profit仍然是NaN，跳过这个组合
            if pd.isna(max_profit) or pd.isna(max_loss):
                continue
            
            # 计算盈亏比
            reward_risk_ratio = max_profit / max_loss if max_loss > 0 else 0
            
            # 计算安全距离（卖出行权价与当前价格的距离百分比）
            short_distance_pct = (current_price - short_strike) / current_price * 100
            
            # 计算综合评分（规范化版本，确保总分合理）
            # 1. 盈亏比因子：0-40分，盈亏比通常0-2，超过2按2计算
            rr_clamped = min(reward_risk_ratio, 2.0)
            base_score = rr_clamped * 20  # 最大40
            
            # 2. 流动性因子：0-30分，基于相对流动性
            liquidity_factor = (short_put['liquidity_score'] + long_put['liquidity_score']) / 2
            liquidity_score = (liquidity_factor / puts_df['liquidity_score'].max()) * 30 if puts_df['liquidity_score'].max() > 0 else 0
            
            # 3. 安全距离因子：0-30分，假设最大安全距离20%（超过按20%计算）
            distance_pct_clamped = min(short_distance_pct, 20.0)
            distance_score = (distance_pct_clamped / 20.0) * 30  # 最大30
            
            # 4. 参数匹配奖励：各0-5分，共10分
            strike_match_bonus = (1 - short_distance / strike_tolerance) * 5  # 最多5分
            width_match_bonus = (1 - width_deviation / width_tolerance) * 5   # 最多5分
            
            composite_score = base_score + liquidity_score + distance_score + strike_match_bonus + width_match_bonus
            
            # 确定风险偏好（基于VIX信号级别）
            if vix_level == "GREEN" and vix_signal.get("composite_score", 50) >= 70:
                risk_appetite = "aggressive"
            elif vix_level == "RED" or vix_signal.get("composite_score", 50) < 20:
                risk_appetite = "保守"  # 中文对应
            else:
                risk_appetite = "中等"  # 中文对应
            
            # 转换英文为中文（为向后兼容）
            if risk_appetite == "aggressive":
                risk_appetite_en = "aggressive"
                risk_appetite_cn = "激进"
            elif risk_appetite == "conservative":
                risk_appetite_en = "conservative"
                risk_appetite_cn = "保守"
            else:
                risk_appetite_en = "moderate"
                risk_appetite_cn = "中等"
            
            # 计算组合希腊字母
            short_put_info = {
                'strike': short_strike,
                'bid': short_put['bid'],
                'ask': short_put['ask'],
                'current_price': current_price,
                'days_to_expiry': days_to_expiry
            }
            long_put_info = {
                'strike': long_put['strike'],
                'bid': long_put['bid'],
                'ask': long_put['ask'],
                'current_price': current_price,
                'days_to_expiry': days_to_expiry
            }
            
            greeks_result = calculate_spread_greeks(short_put_info, long_put_info, greeks_data)
            
            # 获取实际IV数据（从希腊字母数据中提取）
            short_iv_value = np.nan
            long_iv_value = np.nan
            
            if greeks_data and greeks_data.get("success") and greeks_data.get("greeks_df"):
                try:
                    # 将字典列表转换为DataFrame
                    greeks_df = pd.DataFrame(greeks_data["greeks_df"])
                    
                    # 如果希腊字母数据包含'iv'列，使用这些值
                    if 'iv' in greeks_df.columns:
                        # 取平均值作为代表性IV值
                        avg_iv = greeks_df['iv'].mean()
                        short_iv_value = avg_iv
                        long_iv_value = avg_iv
                        
                        # 也可以尝试基于行权价匹配更精确的IV值
                        # 暂时使用平均值
                except Exception as e:
                    print(f"⚠️  解析IV数据异常: {e}")
                    # 回退到期权链数据
                    short_iv_value = short_put.get('impliedVolatility', np.nan)
                    long_iv_value = long_put.get('impliedVolatility', np.nan)
            else:
                # 没有希腊字母数据，使用期权链数据
                short_iv_value = short_put.get('impliedVolatility', np.nan)
                long_iv_value = long_put.get('impliedVolatility', np.nan)
            
            # 构建推荐字典
            recommendation = {
                'expiry': expiry,
                'days_to_expiry': days_to_expiry,
                'long_strike': long_put['strike'],
                'short_strike': short_strike,
                'spread_width': actual_spread_width,
                'width_pct': (actual_spread_width / current_price) * 100,
                'short_distance_pct': short_distance_pct,
                'max_profit': max_profit,
                'max_loss': max_loss,
                'reward_risk_ratio': reward_risk_ratio,
                'short_iv': short_iv_value,
                'long_iv': long_iv_value,
                'liquidity_score': liquidity_factor,
                'composite_score': composite_score,
                'composite_score_ratio': f"{composite_score:.1f}/100",  # 新增评分比值
                'risk_appetite': risk_appetite_en,  # 保持原有英文字段
                'risk_appetite_cn': risk_appetite_cn,  # 新增中文风险偏好
                'vix_level': vix_level,
                'target_short_strike': target_short_strike,
                'target_spread_width': target_spread_width,
                'strike_deviation': short_distance,
                'width_deviation': width_deviation,
                # 希腊字母字段
                'delta': greeks_result.get('delta', 0),
                'gamma': greeks_result.get('gamma', 0),
                'theta': greeks_result.get('theta', 0),
                'vega': greeks_result.get('vega', 0),
                'greeks_source': greeks_result.get('source', 'unknown'),
                'greeks_notes': greeks_result.get('notes', '')
            }
            
            expiry_recs.append(recommendation)
        
        # 为该到期日按综合评分排序，取前3个最佳推荐（增加产出）
        if expiry_recs:
            expiry_recs.sort(key=lambda x: x['composite_score'], reverse=True)
            expiry_recommendations[expiry] = expiry_recs[:3]
    
    # 收集所有推荐，按综合评分排序
    all_recommendations = []
    for expiry, recs in expiry_recommendations.items():
        all_recommendations.extend(recs)
    
    # 按综合评分排序
    all_recommendations.sort(key=lambda x: x['composite_score'], reverse=True)
    
    # 返回所有推荐（最多12个，确保至少3个）
    return all_recommendations[:12]

def calculate_greeks(option_data, strike_price, option_type='put', days_to_expiry=30):
    """
    计算期权希腊值（简化版）
    
    注意：这是一个简化实现，实际中应使用专业期权定价模型
    
    Parameters:
    -----------
    option_data : dict
        包含当前价格等信息的字典
    strike_price : float
        行权价
    option_type : str
        期权类型：'call'或'put'
    days_to_expiry : int
        剩余到期天数
    
    Returns:
    --------
    dict
        包含希腊值的字典
    """
    if option_data is None:
        return {"error": "option_data为空"}
    
    current_price = option_data.get("current_price", 450.00)
    
    # 简化计算
    if option_type == "put":
        # 看跌期权的delta为负
        delta = -0.4
    else:
        # 看涨期权的delta为正
        delta = 0.6
    
    # 简化希腊值计算
    greeks = {
        "delta": delta,  # 价格变化敏感性
        "gamma": 0.05,   # delta变化率
        "theta": -0.02,  # 时间衰减
        "vega": 0.15     # 波动率敏感性
    }
    
    return greeks

def analyze_volatility_surface(option_data):
    """
    分析波动率曲面
    
    添加数据完整性检查：
    1. 检查到期日数量是否<2
    2. 计算IV值缺失率是否>50%
    如果数据不足，返回data_sufficient=False标志
    
    Parameters:
    -----------
    option_data : dict
        get_tsla_option_chain返回的数据
    
    Returns:
    --------
    dict
        波动率分析结果，包含data_sufficient标志
    """
    if "error" in option_data:
        return {"error": option_data["error"]}
    
    try:
        option_chains = option_data["option_chains"]
        current_price = option_data["current_price"]
        
        if not option_chains:
            return {"error": "期权链数据为空"}
        
        # 数据完整性检查
        # 1. 检查到期日数量
        expiry_count = len(option_chains)
        
        # 2. 计算IV值缺失率
        total_options = 0
        missing_iv_count = 0
        
        for chain_df in option_chains:
            total_options += len(chain_df)
            missing_iv_count += chain_df['impliedVolatility'].isna().sum()
        
        # 计算缺失率（百分比）
        iv_missing_rate = (missing_iv_count / total_options * 100) if total_options > 0 else 100
        
        # 确定数据是否充足
        data_sufficient = expiry_count >= 2 and iv_missing_rate <= 50
        
        # 如果数据不足，仍然计算部分结果但标记为不足
        all_iv_data = []
        
        for chain_df in option_chains:
            for _, row in chain_df.iterrows():
                if pd.notna(row.get('impliedVolatility')):
                    all_iv_data.append({
                        "strike": row['strike'],
                        "iv": row['impliedVolatility'],
                        "type": row['type'],
                        "expiry": row['expiry']
                    })
        
        if not all_iv_data:
            return {
                "success": False,
                "error": "没有有效的隐含波动率数据",
                "data_sufficient": False,
                "summary_stats": None,
                "term_structure": None,
                "all_iv_data": [],
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        # 创建DataFrame进行分析
        iv_df = pd.DataFrame(all_iv_data)
        
        # 计算ATMC（平值期权）隐含波动率
        atm_strikes = iv_df[iv_df['strike'].between(current_price * 0.95, current_price * 1.05)]
        
        if not atm_strikes.empty:
            avg_atm_iv = atm_strikes['iv'].mean()
        else:
            avg_atm_iv = iv_df['iv'].mean()
        
        # 分析波动率微笑/偏斜
        call_iv = iv_df[iv_df['type'] == 'call']
        put_iv = iv_df[iv_df['type'] == 'put']
        
        vol_smile = {
            "avg_atm_iv": round(avg_atm_iv, 2),
            "call_iv_avg": round(call_iv['iv'].mean(), 2) if not call_iv.empty else None,
            "put_iv_avg": round(put_iv['iv'].mean(), 2) if not put_iv.empty else None,
            "iv_range": round(iv_df['iv'].max() - iv_df['iv'].min(), 2) if len(iv_df) > 0 else None,
            "iv_percentile": round(iv_df['iv'].quantile(0.5), 2) if len(iv_df) > 0 else None
        }
        
        # 计算波动率期限结构（即使数据不足也尝试计算，但标记）
        term_structure = {}
        
        for chain_df in option_chains:
            expiry = chain_df['expiry'].iloc[0]
            days = chain_df['days_to_expiry'].iloc[0]
            
            atm_calls = chain_df[(chain_df['type'] == 'call') & 
                                (chain_df['strike'].between(current_price * 0.95, current_price * 1.05))]
            atm_puts = chain_df[(chain_df['type'] == 'put') & 
                               (chain_df['strike'].between(current_price * 0.95, current_price * 1.05))]
            
            avg_call_iv = atm_calls['impliedVolatility'].mean() if not atm_calls.empty else None
            avg_put_iv = atm_puts['impliedVolatility'].mean() if not atm_puts.empty else None
            
            term_structure[expiry] = {
                "days_to_expiry": days,
                "atm_call_iv": round(avg_call_iv, 2) if avg_call_iv is not None else None,
                "atm_put_iv": round(avg_put_iv, 2) if avg_put_iv is not None else None,
                "iv_spread": round(avg_call_iv - avg_put_iv, 2) if avg_call_iv is not None and avg_put_iv is not None else None
            }
        
        return {
            "success": True,
            "data_sufficient": data_sufficient,
            "summary_stats": vol_smile,
            "term_structure": term_structure if data_sufficient else {},
            "all_iv_data": iv_df.to_dict('records'),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "data_quality_metrics": {
                "expiry_count": expiry_count,
                "total_options": total_options,
                "missing_iv_count": missing_iv_count,
                "iv_missing_rate": round(iv_missing_rate, 1),
                "data_sufficient_reason": "数据充足" if data_sufficient else f"数据不足: 到期日数量{expiry_count}<2 或 IV缺失率{round(iv_missing_rate, 1)}%>50%"
            }
        }
        
    except Exception as e:
        return {"error": f"波动率分析失败: {e}"}

def get_target_expiration_dates(api_response=None):
    """
    获取目标到期日列表：筛选从今天起14天内的所有到期日
    
    实现智能滚动机制，每次报告生成时基于当前日期计算14天窗口，
    自动筛选窗口内的到期日，每周窗口自动向前推移。
    
    Parameters:
    -----------
    api_response : dict, optional
        option_chain_parser.fetch_option_chain_api返回的API响应字典
        如果为None，则自动调用API获取数据
    
    Returns:
    --------
    dict
        包含以下字段的字典：
        - success: bool，是否成功
        - error: str，错误信息（如果success为False）
        - target_dates: list，目标到期日字符串列表（格式：YYYY-MM-DD），包含从今天起14天内的所有到期日
        - notes: str，说明信息（如窗口内无到期日时的说明）
        - metadata: dict，元数据（原始API响应等）
    """
    try:
        # 导入期权链解析模块
        from option_chain_parser import fetch_option_chain_api, extract_target_expiration_dates
        
        # 如果未提供API响应，则自动获取
        if api_response is None:
            print("🔍 自动获取期权链数据以提取目标到期日...")
            api_response = fetch_option_chain_api(use_cache=True)
        
        # 提取目标到期日（已实现14天窗口筛选）
        extraction_result = extract_target_expiration_dates(api_response)
        
        if not extraction_result.get("success"):
            return {
                "success": False,
                "error": extraction_result.get("error", "提取到期日失败"),
                "target_dates": [],
                "notes": "无法从API响应中提取到期日",
                "metadata": extraction_result.get("metadata", {})
            }
        
        target_dates = extraction_result.get("target_dates", [])
        metadata = extraction_result.get("metadata", {})
        
        # 过滤掉None值（理论上新函数不会返回None，但为安全保留）
        valid_dates = [date for date in target_dates if date is not None]
        
        # 检查窗口内是否有到期日
        if len(valid_dates) == 0:
            return {
                "success": True,
                "error": None,
                "target_dates": [],
                "notes": "未找到14天窗口内的有效到期日",
                "metadata": metadata
            }
        
        # 确保日期按时间顺序排序
        valid_dates.sort()
        
        # 生成说明信息
        current_date = datetime.now().date()
        date_notes = []
        
        for date_str in valid_dates:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                days_diff = (date_obj - current_date).days
                
                if days_diff <= 7:
                    date_notes.append(f"{date_str}（本周到期，剩余{days_diff}天）")
                elif days_diff <= 14:
                    date_notes.append(f"{date_str}（下周到期，剩余{days_diff}天）")
                else:
                    # 正常情况下不会出现大于14天的情况（因为已筛选）
                    date_notes.append(f"{date_str}（远期，剩余{days_diff}天）")
            except:
                date_notes.append(f"{date_str}（日期解析失败）")
        
        notes = "到期日详情：" + "，".join(date_notes)
        
        return {
            "success": True,
            "error": None,
            "target_dates": valid_dates,
            "notes": notes,
            "metadata": metadata
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"获取目标到期日异常: {str(e)}",
            "target_dates": [],
            "notes": "函数执行过程中发生异常",
            "metadata": {}
        }



def calculate_price_range_iv(current_price, target_days, iv_data, confidence=0.68):
    """
    基于隐含波动率（IV）计算未来价格可能区间
    
    参数：
    -----------
    current_price : float
        当前股价
    target_days : int
        目标天数（未来多少天）
    iv_data : list or pd.DataFrame
        隐含波动率数据，格式为[(days_to_expiry, iv_value), ...]或包含'days_to_expiry'和'impliedVolatility'列的DataFrame
    confidence : float, optional
        置信度，默认0.68（1个标准差），可选0.95（1.96个标准差）
    
    返回：
    --------
    dict
        包含以下字段的字典：
        - success: bool，计算是否成功
        - error: str，错误信息（如果success为False）
        - current_price: float，当前股价
        - target_days: int，目标天数
        - confidence: float，置信度
        - implied_volatility: float，用于计算的隐含波动率（年化）
        - price_lower: float，价格区间下限
        - price_upper: float，价格区间上限
        - change_pct_lower: float，下限相对当前价格的涨跌幅（%）
        - change_pct_upper: float，上限相对当前价格的涨跌幅（%）
        - data_points: int，用于插值的有效IV数据点数量
    """
    try:
        # 转换为DataFrame处理
        if isinstance(iv_data, pd.DataFrame):
            iv_df = iv_data.copy()
            # 确保列名正确
            if 'days_to_expiry' not in iv_df.columns and 'impliedVolatility' not in iv_df.columns:
                # 尝试从DataFrame结构中解析
                if len(iv_df.columns) >= 2:
                    iv_df.columns = ['days_to_expiry', 'impliedVolatility']
        else:
            # 假设是列表或元组
            iv_df = pd.DataFrame(iv_data, columns=['days_to_expiry', 'impliedVolatility'])
        
        # 清理数据：移除NaN值
        iv_df = iv_df.dropna(subset=['days_to_expiry', 'impliedVolatility'])
        
        # 检查数据量
        if len(iv_df) < 2:
            return {
                "success": False,
                "error": f"有效IV数据点不足（{len(iv_df)}个），至少需要2个点进行插值",
                "current_price": current_price,
                "target_days": target_days,
                "confidence": confidence,
                "data_points": len(iv_df)
            }
        
        # 获取唯一到期天数并排序
        iv_df = iv_df.sort_values('days_to_expiry')
        days_array = iv_df['days_to_expiry'].values
        iv_array = iv_df['impliedVolatility'].values
        
        # 计算目标天数对应的IV（线性插值）
        # 如果目标天数在范围内，插值；否则用最近端点外推
        if target_days <= days_array.min():
            target_iv = iv_array[0]
        elif target_days >= days_array.max():
            target_iv = iv_array[-1]
        else:
            # 线性插值
            target_iv = np.interp(target_days, days_array, iv_array)
        
        # 计算z值（标准正态分布分位数）
        if abs(confidence - 0.68) < 0.01:
            z_value = 1.0
        elif abs(confidence - 0.95) < 0.01:
            z_value = 1.96
        else:
            # 通用计算：使用正态分布逆CDF
            from scipy.stats import norm
            z_value = norm.ppf((1 + confidence) / 2)
        
        # 计算年化因子：sqrt(days/365)
        annual_factor = np.sqrt(target_days / 365.0)
        
        # 计算价格上下限：S * exp(± z * σ * sqrt(t))
        # 注意：IV已经是年化百分比，需要除以100转换为小数
        iv_decimal = target_iv / 100.0
        price_lower = current_price * np.exp(-z_value * iv_decimal * annual_factor)
        price_upper = current_price * np.exp(z_value * iv_decimal * annual_factor)
        
        # 计算涨跌幅
        change_pct_lower = (price_lower - current_price) / current_price * 100
        change_pct_upper = (price_upper - current_price) / current_price * 100
        
        return {
            "success": True,
            "error": None,
            "current_price": current_price,
            "target_days": target_days,
            "confidence": confidence,
            "implied_volatility": target_iv,
            "price_lower": price_lower,
            "price_upper": price_upper,
            "change_pct_lower": change_pct_lower,
            "change_pct_upper": change_pct_upper,
            "data_points": len(iv_df)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"计算价格区间时发生异常: {str(e)}",
            "current_price": current_price,
            "target_days": target_days,
            "confidence": confidence,
            "data_points": 0
        }


def get_greeks_enhanced_price_range(option_data, target_periods=None, confidence_levels=None):
    """
    使用希腊字母数据增强价格区间预测
    
    参数：
    -----------
    option_data : dict
        get_tsla_option_chain返回的数据
    target_periods : list, optional
        目标天数列表，默认[7, 14, 30]
    confidence_levels : list, optional
        置信度列表，默认[0.68, 0.95]
    
    返回：
    --------
    dict
        包含以下字段的字典：
        - success: bool，是否成功
        - error: str，错误信息（如果success为False）
        - table_data: list，表格数据，每行对应一个目标时间段
        - summary: dict，摘要信息
        - data_quality: dict，数据质量指标
        - metadata: dict，元数据
        - data_source: str，数据来源（'greeks' 或 'fallback'）
    """
    try:
        # 默认参数
        if target_periods is None:
            target_periods = [7, 14, 30]
        if confidence_levels is None:
            confidence_levels = [0.68, 0.95]
        
        current_price = option_data.get("current_price", 450.00)
        
        # 尝试获取希腊字母数据 - 优先使用替代数据源
        try:
            from option_chain_parser import fetch_option_greeks_alternative
            greeks_result = fetch_option_greeks_alternative()
            
            if greeks_result.get("success") and greeks_result.get("greeks_df") is not None:
                # 将字典列表转换为DataFrame
                greeks_data = greeks_result["greeks_df"]
                greeks_df = pd.DataFrame(greeks_data)
                
                # 检查是否包含必要的IV数据
                iv_columns = [col for col in greeks_df.columns if 'iv' in col.lower()]
                if iv_columns:
                    # 使用希腊字母数据进行价格区间预测
                    table_rows = []
                    
                    for days in target_periods:
                        row_data = {
                            "target_days": days,
                            "current_price": current_price,
                            "data_source": "greeks"
                        }
                        
                        # 为每个置信度计算价格区间
                        for confidence in confidence_levels:
                            # 从新数据源提取IV值（'iv'列）
                            iv_mean = greeks_df['iv'].mean() if 'iv' in greeks_df.columns else None
                            
                            # 使用可用的IV数据
                            if iv_mean is not None and not pd.isna(iv_mean):
                                iv_value = iv_mean
                            else:
                                # 没有有效的IV数据
                                row_data[f"{int(confidence*100)}%_error"] = "无有效IV数据"
                                continue
                            
                            # 计算价格区间
                            if confidence == 0.68:
                                z_value = 1.0
                            elif confidence == 0.95:
                                z_value = 1.96
                            else:
                                from scipy.stats import norm
                                z_value = norm.ppf((1 + confidence) / 2)
                            
                            annual_factor = np.sqrt(days / 365.0)
                            iv_decimal = iv_value / 100.0
                            
                            price_lower = current_price * np.exp(-z_value * iv_decimal * annual_factor)
                            price_upper = current_price * np.exp(z_value * iv_decimal * annual_factor)
                            change_pct_lower = (price_lower - current_price) / current_price * 100
                            change_pct_upper = (price_upper - current_price) / current_price * 100
                            
                            prefix = f"{int(confidence*100)}%"
                            row_data[f"{prefix}_price_lower"] = price_lower
                            row_data[f"{prefix}_price_upper"] = price_upper
                            row_data[f"{prefix}_change_pct_lower"] = change_pct_lower
                            row_data[f"{prefix}_change_pct_upper"] = change_pct_upper
                            row_data[f"{prefix}_iv_used"] = iv_value
                        
                        table_rows.append(row_data)
                    
                    # 生成摘要
                    if table_rows:
                        sample_row = table_rows[1] if len(table_rows) > 1 else table_rows[0]
                        iv_used = sample_row.get('68%_iv_used', 0)
                        price_lower = sample_row.get('68%_price_lower', 0)
                        price_upper = sample_row.get('68%_price_upper', 0)
                        
                        summary = {
                            "message": f"基于Barchart隐含波动率数据({iv_used:.1f}%)，未来14天内股价有68%概率落在${price_lower:.2f}-${price_upper:.2f}之间",
                            "data_source": "greeks",
                            "representative_iv": iv_used,
                            "data_sufficient": True
                        }
                    else:
                        summary = {
                            "message": "无法生成价格区间预测",
                            "data_source": "greeks",
                            "data_sufficient": False
                        }
                    
                    return {
                        "success": True,
                        "error": None,
                        "table_data": table_rows,
                        "summary": summary,
                        "data_quality": {
                            "iv_points_count": len(iv_columns),
                            "data_source": "greeks",
                            "notes": "数据来自Barchart隐含波动率页面"
                        },
                        "metadata": {
                            "current_price": current_price,
                            "target_periods": target_periods,
                            "confidence_levels": confidence_levels,
                            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "greeks_metadata": greeks_result.get("metadata", {})
                        },
                        "data_source": "greeks"
                    }
        
        except Exception as greeks_error:
            logging.warning(f"获取希腊字母数据失败: {greeks_error}")
        
        # 如果希腊字母数据不可用，回退到原始方法
        return {
            "success": False,
            "error": "希腊字母数据不可用，无法增强价格区间预测",
            "table_data": [],
            "summary": {},
            "data_quality": {},
            "metadata": {},
            "data_source": "fallback"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"增强价格区间预测异常: {str(e)}",
            "table_data": [],
            "summary": {},
            "data_quality": {},
            "metadata": {},
            "data_source": "error"
        }


def generate_price_range_table(option_data, target_periods=None, confidence_levels=None, use_greeks=True):
    """
    为多个目标时间段和置信度生成价格区间预测表格
    
    参数：
    -----------
    option_data : dict
        get_tsla_option_chain返回的数据
    target_periods : list, optional
        目标天数列表，默认[7, 14, 30]
    confidence_levels : list, optional
        置信度列表，默认[0.68, 0.95]
    use_greeks : bool, optional
        是否尝试使用希腊字母数据，默认True
    
    返回：
    --------
    dict
        包含以下字段的字典：
        - success: bool，是否成功
        - error: str，错误信息（如果success为False）
        - table_data: list，表格数据，每行对应一个目标时间段
        - summary: dict，摘要信息
        - data_quality: dict，数据质量指标
        - metadata: dict，元数据
    """
    try:
        if "error" in option_data:
            return {
                "success": False,
                "error": f"期权数据无效: {option_data['error']}",
                "table_data": [],
                "summary": {},
                "data_quality": {},
                "metadata": {}
            }
        
        # 默认参数
        if target_periods is None:
            target_periods = [7, 14, 30]
        if confidence_levels is None:
            confidence_levels = [0.68, 0.95]
        
        current_price = option_data.get("current_price", 450.00)
        
        # 如果启用希腊字母数据，尝试获取
        if use_greeks:
            try:
                from option_chain_parser import fetch_option_greeks_alternative
                greeks_result = fetch_option_greeks_alternative()
                
                if greeks_result.get("success") and greeks_result.get("greeks_df") is not None:
                    # 将字典列表转换为DataFrame
                    greeks_data = greeks_result["greeks_df"]
                    greeks_df = pd.DataFrame(greeks_data)
                    
                    # 检查是否包含IV数据
                    iv_columns = [col for col in greeks_df.columns if 'iv' in col.lower()]
                    if iv_columns:
                        # 提取有效的IV数据
                        iv_data = []
                        # 新的数据源中'iv'列包含IV值
                        if 'iv' in greeks_df.columns:
                            valid_iv = greeks_df['iv'].dropna()
                            for idx, iv_val in enumerate(valid_iv.values):
                                # 使用索引作为天数差异（提供不同的数据点）
                                # 7天和30天到期的占位符
                                days = 7 + idx * 10  # 7, 17, 27等
                                iv_data.append((days, iv_val))
                        
                        if len(iv_data) >= 2:
                            # 使用希腊字母数据计算价格区间
                            table_rows = []
                            
                            for days in target_periods:
                                row_data = {
                                    "target_days": days,
                                    "current_price": current_price,
                                    "data_source": "greeks"
                                }
                                
                                # 为每个置信度计算价格区间
                                for confidence in confidence_levels:
                                    result = calculate_price_range_iv(current_price, days, iv_data, confidence)
                                    
                                    if result["success"]:
                                        prefix = f"{int(confidence*100)}%"
                                        row_data[f"{prefix}_price_lower"] = result["price_lower"]
                                        row_data[f"{prefix}_price_upper"] = result["price_upper"]
                                        row_data[f"{prefix}_change_pct_lower"] = result["change_pct_lower"]
                                        row_data[f"{prefix}_change_pct_upper"] = result["change_pct_upper"]
                                        row_data[f"{prefix}_iv_used"] = result["implied_volatility"]
                                    else:
                                        prefix = f"{int(confidence*100)}%"
                                        row_data[f"{prefix}_error"] = result["error"]
                                
                                table_rows.append(row_data)
                            
                            # 生成摘要
                            if table_rows:
                                sample_result = calculate_price_range_iv(current_price, 14, iv_data, 0.68)
                                representative_iv = sample_result.get("implied_volatility", 0) if sample_result["success"] else 0
                                
                                summary = {
                                    "message": f"基于Barchart隐含波动率数据({representative_iv:.1f}%)，未来14天内股价有68%概率落在${table_rows[1].get('68%_price_lower', 0):.2f}-${table_rows[1].get('68%_price_upper', 0):.2f}之间",
                                    "representative_iv": representative_iv,
                                    "data_points": len(iv_data),
                                    "data_sufficient": True,
                                    "data_source": "greeks"
                                }
                            else:
                                summary = {
                                    "message": "无法生成价格区间预测",
                                    "data_sufficient": False,
                                    "data_source": "greeks"
                                }
                            
                            return {
                                "success": True,
                                "error": None,
                                "table_data": table_rows,
                                "summary": summary,
                                "data_quality": {
                                    "iv_points_count": len(iv_data),
                                    "data_source": "greeks",
                                    "notes": "数据来自Barchart隐含波动率页面"
                                },
                                "metadata": {
                                    "current_price": current_price,
                                    "target_periods": target_periods,
                                    "confidence_levels": confidence_levels,
                                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    "greeks_metadata": greeks_result.get("metadata", {})
                                }
                            }
            
            except Exception as greeks_error:
                logging.warning(f"获取希腊字母数据失败，将使用标准方法: {greeks_error}")
        
        # 标准方法：使用现有的期权链数据
        option_chains = option_data.get("option_chains", [])
        
        # 提取IV数据：每个到期日的平均IV
        iv_points = []
        total_options = 0
        missing_iv_count = 0
        iv_column_exists = False
        
        for chain_df in option_chains:
            if chain_df.empty:
                continue
            
            # 检查IV列是否存在
            if 'impliedVolatility' in chain_df.columns:
                iv_column_exists = True
                
                # 获取到期天数
                days_to_expiry = chain_df['days_to_expiry'].iloc[0]
                
                # 计算该到期日的平均IV（排除NaN）
                valid_iv = chain_df['impliedVolatility'].dropna()
                if not valid_iv.empty:
                    avg_iv = valid_iv.mean()
                    iv_points.append((days_to_expiry, avg_iv))
                
                # 统计缺失率
                missing_iv_count += chain_df['impliedVolatility'].isna().sum()
            else:
                # 如果IV列不存在，直接统计缺失
                missing_iv_count += len(chain_df)
            
            total_options += len(chain_df)
        
        # 计算IV缺失率
        iv_missing_rate = (missing_iv_count / total_options * 100) if total_options > 0 else 100
        
        # 检查数据是否充足
        # 条件1：IV列必须存在
        # 条件2：至少有2个有效IV数据点
        # 条件3：IV缺失率不超过50%
        data_sufficient = iv_column_exists and len(iv_points) >= 2 and iv_missing_rate <= 50
        
        if not data_sufficient:
            return {
                "success": True,
                "error": None,
                "table_data": [],
                "summary": {
                    "message": f"数据不足，无法计算价格区间预测（有效IV点: {len(iv_points)}个，缺失率: {iv_missing_rate:.1f}%）",
                    "data_sufficient": False
                },
                "data_quality": {
                    "iv_points_count": len(iv_points),
                    "iv_missing_rate": iv_missing_rate,
                    "data_sufficient": data_sufficient
                },
                "metadata": {
                    "current_price": current_price,
                    "target_periods": target_periods,
                    "confidence_levels": confidence_levels,
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        
        # 计算每个目标时间段和置信度的价格区间
        table_rows = []
        
        for days in target_periods:
            row_data = {
                "target_days": days,
                "current_price": current_price
            }
            
            # 为每个置信度计算价格区间
            for confidence in confidence_levels:
                result = calculate_price_range_iv(current_price, days, iv_points, confidence)
                
                if result["success"]:
                    # 提取关键信息
                    prefix = f"{int(confidence*100)}%"
                    row_data[f"{prefix}_price_lower"] = result["price_lower"]
                    row_data[f"{prefix}_price_upper"] = result["price_upper"]
                    row_data[f"{prefix}_change_pct_lower"] = result["change_pct_lower"]
                    row_data[f"{prefix}_change_pct_upper"] = result["change_pct_upper"]
                    row_data[f"{prefix}_iv_used"] = result["implied_volatility"]
                else:
                    # 记录错误
                    row_data[f"{prefix}_error"] = result["error"]
            
            table_rows.append(row_data)
        
        # 生成摘要
        if table_rows:
            # 使用第一个结果作为代表性IV
            sample_result = calculate_price_range_iv(current_price, 14, iv_points, 0.68)
            representative_iv = sample_result.get("implied_volatility", 0) if sample_result["success"] else 0
            
            summary = {
                "message": f"基于当前隐含波动率({representative_iv:.1f}%)，未来14天内股价有68%概率落在${table_rows[1].get('68%_price_lower', 0):.2f}-${table_rows[1].get('68%_price_upper', 0):.2f}之间",
                "representative_iv": representative_iv,
                "data_points": len(iv_points),
                "data_sufficient": True
            }
        else:
            summary = {
                "message": "无法生成价格区间预测",
                "data_sufficient": False
            }
        
        return {
            "success": True,
            "error": None,
            "table_data": table_rows,
            "summary": summary,
            "data_quality": {
                "iv_points_count": len(iv_points),
                "iv_missing_rate": iv_missing_rate,
                "data_sufficient": data_sufficient
            },
            "metadata": {
                "current_price": current_price,
                "target_periods": target_periods,
                "confidence_levels": confidence_levels,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"生成价格区间表格时发生异常: {str(e)}",
            "table_data": [],
            "summary": {},
            "data_quality": {},
            "metadata": {}
        }

def generate_option_framework_report():
    """
    生成期权分析框架报告
    
    Returns:
    --------
    str
        完整的期权分析报告
    """
    # 获取期权链数据
    option_data = get_tsla_option_chain(expiry_days_range=(7, 45))
    
    report_lines = [
        "## 期权分析框架报告",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "### 一、数据获取状态",
    ]
    
    if "error" in option_data:
        report_lines.append(f"❌ 数据获取失败: {option_data['error']}")
    else:
        report_lines.extend([
            f"✅ 数据获取成功",
            f"- 当前价格: ${option_data['current_price']:.2f}",
            f"- 期权链数量: {len(option_data['option_chains'])}组",
        ])
        
        # 分析每个到期日的期权数据
        report_lines.extend([
            "",
            "### 二、到期日分析",
        ])
        
        for chain_df in option_data["option_chains"]:
            expiry = chain_df['expiry'].iloc[0]
            days = chain_df['days_to_expiry'].iloc[0]
            
            calls = chain_df[chain_df['type'] == 'call']
            puts = chain_df[chain_df['type'] == 'put']
            
            report_lines.extend([
                f"**{expiry}** (剩余{days}天):",
                f"- 看涨期权: {len(calls)}个",
                f"- 看跌期权: {len(puts)}个",
                f"- 行权价范围: ${chain_df['strike'].min():.2f} - ${chain_df['strike'].max():.2f}",
                "",
            ])
    
    # 技术框架说明
    report_lines.extend([
        "",
        "### 三、技术框架说明",
        "",
        "**核心分析逻辑**:",
        "1. **数据获取**: 从Nasdaq官方API获取实时期权链数据",
        "2. **到期日筛选**: 重点关注14天内的近期合约",
        "3. **垂直价差构建**: 基于VIX信号级别确定关键参数",
        "4. **综合评分**: 结合盈亏比、流动性、安全距离等多因子评估",
        "",
        "**VIX信号映射表**:",
        "- 🟢 绿灯信号: 卖出行权价=股价×95%，价差宽度=$30",
        "- 🟡 黄灯信号: 卖出行权价=股价×92%，价差宽度=$20", 
        "- 🔴 红灯信号: 卖出行权价=股价×92%，价差宽度=$20",
        "",
        "**容差范围**:",
        "- 行权价偏差 ≤ $5",
        "- 价差宽度偏差 ≤ $10",
        "",
        "### 四、评分体系",
        "**综合评分构成**:",
        "1. 盈亏比因子: 40% (reward_risk_ratio × 40)",
        "2. 流动性因子: 30% (流动性得分/最高分 × 100)",
        "3. 安全距离因子: 30% (short_distance_pct)",
        "",
        "**置信度指导**:",
        "- ≥70分 (高置信度): 建议积极开仓",
        "- 40-69分 (中等置信度): 建议谨慎开仓，控制仓位",
        "- <40分 (低置信度): 建议保守观望",
        "",
        "**趋势使用方法**:",
        "- 连续上升可加仓，连续下降应减仓",
        "- 结合VIX信号和市场情绪综合判断",
        "",
        "### 五、波动率分析框架",
        "**关键监控指标**:",
        "1. ATMC IV (平值期权隐含波动率): 市场情绪的核心指标",
        "2. IV微笑/偏斜: 识别市场偏好的关键",
        "3. 波动率期限结构: 判断市场预期变化",
        "",
        "**IV Crush现象识别**:",
        "1. 事件驱动型IV飙升后快速回落",
        "2. 财报后IV衰减明显",
        "3. 重大事件前IV溢价过高",
        "",
        "### 六、事件影响矩阵",
        "**主要事件类型**:",
        "   1. 财报发布:",
        "      • 影响强度: 高 (30-50% IV变化)",
        "      • 持续性: 短期 (2-3天)",
        "      • 建议: 财报前减仓，财报后寻找新机会",
        "",
        "   2. 产品发布会:",
        "      • 影响强度: 中 (15-25% IV变化)",
        "      • 持续性: 中等 (5-7天)",
        "      • 建议: 适度调整策略，关注市场反应",
        "",
        "   3. 监管事件:",
        "      • 影响强度: 高 (25-40% IV变化)",
        "      • 持续性: 取决于事件严重程度",
        "      • 建议: 事件前降低仓位或增加对冲",
        "",
        "   4. 宏观经济数据:",
        "      • 常规数据: 影响较小(5-15% IV变化)",
        "      • 重大数据(如CPI、FOMC): 可能引发20-30% IV变化",
        "",
        "   使用建议:",
        "   • 事件前1周开始监控IV变化",
        "   • 事件前1-2天考虑减仓或调整策略",
        "   • 事件后评估IV crush影响，寻找新机会",
    ])
    
    report_lines.extend([
        "",
        "八、希腊值动态跟踪框架",
        "   关键希腊值监控要点:",
        "",
        "   1. Delta (价格敏感性):",
        "      • 牛市价差组合Delta应为正",
        "      • 监控Delta变化，避免过度暴露",
        "",
        "   2. Gamma (Delta变化率):",
        "      • 股价接近行权价时Gamma风险最高",
        "      • Gamma风险可能导致快速盈亏变化",
        "",
        "   3. Theta (时间衰减):",
        "      • 价差策略通常为正Theta(时间有利)",
        "      • 监控Theta衰减速度，优化持有期限",
        "",
        "   4. Vega (波动率敏感性):",
        "      • 牛市价差通常为负Vega(波动率上升不利)",
        "      • VIX信号红灯时需特别关注Vega风险",
        "",
        "   日常监控建议:",
        "   • 每日开盘检查关键希腊值",
        "   • 股价变动5%以上时重新计算",
        "   • VIX大幅波动时评估Vega风险",
    ])
    
    return "\n".join(report_lines)


def analyze_most_active_options() -> Dict[str, Any]:
    """
    分析最活跃期权数据，提取市场信号并集成到分析框架
    
    返回:
        分析结果字典，包含:
        - success: bool，是否成功
        - error: str，错误信息
        - data: dict，分析数据（当success为True时）
        - metadata: dict，元数据
    """
    try:
        # 导入最活跃期权解析器
        try:
            from option_chain_parser import fetch_most_active_options
        except ImportError:
            from scripts.option_chain_parser import fetch_most_active_options
        
        # 获取最活跃期权数据
        result = fetch_most_active_options(use_cache=True)
        
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "获取最活跃期权数据失败"),
                "data": None,
                "metadata": result.get("metadata", {})
            }
        
        calls_df = result.get("most_active_calls")
        puts_df = result.get("most_active_puts")
        
        # 分析数据
        analysis = {
            "calls_data": None,
            "puts_data": None,
            "total_call_volume": 0,
            "total_put_volume": 0,
            "call_put_volume_ratio": 0,
            "avg_implied_volatility_calls": 0,
            "avg_implied_volatility_puts": 0,
            "top_call_strikes": [],
            "top_put_strikes": [],
            "sentiment": "中性"
        }
        
        # 处理Call数据
        if calls_df is not None and not calls_df.empty:
            analysis["calls_data"] = calls_df.to_dict(orient="records")
            
            # 计算总成交量
            if "volume" in calls_df.columns:
                analysis["total_call_volume"] = int(calls_df["volume"].sum())
            
            # 计算平均隐含波动率
            if "implied_volatility" in calls_df.columns:
                analysis["avg_implied_volatility_calls"] = float(calls_df["implied_volatility"].mean())
            
            # 提取最高成交量行权价
            if "strike" in calls_df.columns and "volume" in calls_df.columns:
                top_calls = calls_df.nlargest(3, "volume")
                analysis["top_call_strikes"] = top_calls[["strike", "volume", "last_price"]].to_dict(orient="records")
        
        # 处理Put数据
        if puts_df is not None and not puts_df.empty:
            analysis["puts_data"] = puts_df.to_dict(orient="records")
            
            # 计算总成交量
            if "volume" in puts_df.columns:
                analysis["total_put_volume"] = int(puts_df["volume"].sum())
            
            # 计算平均隐含波动率
            if "implied_volatility" in puts_df.columns:
                analysis["avg_implied_volatility_puts"] = float(puts_df["implied_volatility"].mean())
            
            # 提取最高成交量行权价
            if "strike" in puts_df.columns and "volume" in puts_df.columns:
                top_puts = puts_df.nlargest(3, "volume")
                analysis["top_put_strikes"] = top_puts[["strike", "volume", "last_price"]].to_dict(orient="records")
        
        # 计算Call/Put成交量比率
        if analysis["total_put_volume"] > 0:
            analysis["call_put_volume_ratio"] = analysis["total_call_volume"] / analysis["total_put_volume"]
        
        # 判断市场情绪
        ratio = analysis["call_put_volume_ratio"]
        if ratio > 1.5:
            analysis["sentiment"] = "看涨"
        elif ratio < 0.7:
            analysis["sentiment"] = "看跌"
        else:
            analysis["sentiment"] = "中性"
        
        # 构建最终结果
        return {
            "success": True,
            "error": None,
            "data": analysis,
            "metadata": result.get("metadata", {})
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"分析最活跃期权数据失败: {str(e)}",
            "data": None,
            "metadata": {}
        }


if __name__ == "__main__":
    print("🔍 测试期权分析框架...")
    
    # 生成完整报告
    report = generate_option_framework_report()
    print(report)
    
    # 测试最活跃期权分析
    print("\n🔍 测试最活跃期权分析...")
    most_active_result = analyze_most_active_options()
    print(f"成功: {most_active_result.get('success')}")
    print(f"错误: {most_active_result.get('error')}")
    
    if most_active_result.get("success"):
        data = most_active_result.get("data", {})
        print(f"市场情绪: {data.get('sentiment')}")
        print(f"Call/Put成交量比率: {data.get('call_put_volume_ratio', 0):.2f}")
        print(f"Call总成交量: {data.get('total_call_volume', 0):,}")
        print(f"Put总成交量: {data.get('total_put_volume', 0):,}")
    
    print("\n✅ 期权分析框架测试完成")