"""
VIX MA10 信号体系完善模块
基于用户上传的 tsla_strategy_signals.py 代码，实现四个维度的完善：
1. 阈值量化：计算 VIX 与 MA10 的偏离度，定义三级信号
2. 趋势强度：计算 MA10 的5日斜率，区分趋势强度
3. 历史分位：计算 VIX 在过去一年中的历史分位
4. 信号集成：将 VIX MA10 信号与其他因子加权，生成综合开单评分
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def get_vix_data(days=365):
    """
    获取 VIX 历史数据（严格按照新数据源规范）
    
    数据源：使用datahub.io/finance-vix的CSV数据作为CBOE官网的可靠替代
    原始URL: https://datahub.io/core/finance-vix/r/vix-daily.csv
    镜像URL: https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv
    
    Parameters:
    -----------
    days : int
        获取历史数据的天数
    
    Returns:
    --------
    pd.Series
        VIX 收盘价序列，索引为日期
    """
    try:
        # 导入新的解析模块
        from vix_data_parser import get_vix_series
        
        # 获取指定天数的数据
        series = get_vix_series(days=days)
        
        if len(series) == 0:
            print(f"⚠️  获取VIX数据失败，返回空Series")
            return pd.Series(dtype=float)
        
        print(f"✅ 成功获取VIX数据: {len(series)} 天")
        return series
        
    except Exception as e:
        print(f"❌ 获取VIX数据失败: {e}")
        # 返回空Series
        return pd.Series(dtype=float)

def calculate_ma10_slope(vix_data, window=5):
    """
    计算 MA10 的斜率（趋势强度）
    
    Parameters:
    -----------
    vix_data : pd.Series
        VIX 收盘价序列
    window : int
        计算斜率的窗口期（默认5天）
    
    Returns:
    --------
    float
        MA10 的斜率（过去window天的变化率）
        np.nan 如果数据不足
    """
    if len(vix_data) < 30:  # 至少需要30天数据来计算MA10
        return np.nan
    
    # 计算每日的MA10
    ma10_series = vix_data.rolling(window=10).mean()
    
    # 获取最近window天的MA10值
    recent_ma10 = ma10_series.tail(window)
    
    if len(recent_ma10) < window:
        return np.nan
    
    # 计算斜率（线性回归斜率）
    x = np.arange(window)
    y = recent_ma10.values
    
    # 简单斜率计算：每日变化率
    slope = (y[-1] - y[0]) / (window - 1) if window > 1 else 0
    
    return slope

def calculate_vix_percentile(vix_data, current_vix):
    """
    计算当前 VIX 在历史数据中的分位
    
    Parameters:
    -----------
    vix_data : pd.Series
        VIX 历史收盘价序列
    current_vix : float
        当前 VIX 值
    
    Returns:
    --------
    float
        历史分位（0-100），np.nan 如果数据不足
    """
    if len(vix_data) < 20:  # 至少需要20天数据
        return np.nan
    
    # 计算当前VIX在历史数据中的分位
    percentile = (np.sum(vix_data <= current_vix) / len(vix_data)) * 100
    return percentile

def get_vix_signal_details(current_vix=None, vix_ma10=None, vix_data=None):
    """
    获取 VIX MA10 信号的详细分析
    
    Parameters:
    -----------
    current_vix : float, optional
        当前 VIX 值，如果为None则从网络获取
    vix_ma10 : float, optional
        当前 VIX MA10 值，如果为None则从网络获取
    vix_data : pd.Series, optional
        VIX 历史数据，如果为None则从网络获取最近365天数据
    
    Returns:
    --------
    dict
        包含完整信号分析的字典
    """
    # 如果未提供数据，则从网络获取
    if vix_data is None:
        vix_data = get_vix_data(days=365)
    
    if current_vix is None or vix_ma10 is None:
        try:
            # 使用新的解析模块获取当前VIX和MA10
            from vix_data_parser import get_vix_with_ma10
            ma_df = get_vix_with_ma10()
            
            if ma_df is None or len(ma_df) == 0:
                return {"error": "VIX数据不足"}
            
            # 获取最新数据
            latest = ma_df.iloc[-1]
            current_vix = float(latest['CLOSE'])
            vix_ma10 = float(latest['MA10'])
            
            print(f"✅ 成功获取当前VIX: {current_vix:.2f}, MA10: {vix_ma10:.2f}")
        except Exception as e:
            print(f"⚠️ 获取当前VIX数据失败: {e}")
            return {"error": f"获取数据失败: {e}"}
    
    # 1. 计算偏离度
    if pd.isna(current_vix) or pd.isna(vix_ma10) or vix_ma10 == 0:
        deviation_pct = np.nan
    else:
        deviation_pct = ((current_vix - vix_ma10) / vix_ma10) * 100
    
    # 2. 确定三级信号
    if pd.isna(deviation_pct):
        signal_level = "UNKNOWN"
        signal_color = "🟡黄灯"
    elif deviation_pct > 5:
        signal_level = "GREEN"
        signal_color = "🟢绿灯"
    elif deviation_pct < -5:
        signal_level = "RED"
        signal_color = "🔴红灯"
    else:
        signal_level = "YELLOW"
        signal_color = "🟡黄灯"
    
    # 3. 计算趋势强度（MA10斜率）
    ma10_slope = calculate_ma10_slope(vix_data)
    
    if pd.isna(ma10_slope):
        trend_strength = "UNKNOWN"
    elif ma10_slope > 0.5:
        trend_strength = "加速上升"  # 加速上升
    elif ma10_slope >= 0:
        trend_strength = "温和上升"  # 温和上升
    else:
        trend_strength = "下降趋势"  # 下降趋势
    
    # 4. 计算历史分位
    vix_percentile = calculate_vix_percentile(vix_data, current_vix)
    
    if pd.isna(vix_percentile):
        percentile_warning = False
    else:
        percentile_warning = vix_percentile > 80  # 超过80分位提示风险
    
    # 5. 生成综合评分（0-100）
    # 评分规则：偏离度权重50%，趋势强度权重30%，历史分位权重20%
    score = 50  # 基础分
    
    # 偏离度贡献（-50到+50）
    if not pd.isna(deviation_pct):
        deviation_score = min(max(deviation_pct * 2, -50), 50)  # 偏离度每1%对应2分
        score += deviation_score
    
    # 趋势强度贡献（-30到+30）
    if not pd.isna(ma10_slope):
        if trend_strength == "下降趋势":
            trend_score = 30  # 下降趋势最有利
        elif trend_strength == "温和上升":
            trend_score = 0   # 温和上升中性
        elif trend_strength == "加速上升":
            trend_score = -30  # 加速上升不利
        else:
            trend_score = 0
        score += trend_score
    
    # 历史分位贡献（-20到0）
    if not pd.isna(vix_percentile):
        if percentile_warning:
            percentile_score = -20  # 高位风险
        else:
            percentile_score = 0    # 正常水平
        score += percentile_score
    
    # 确保分数在0-100范围内
    score = max(0, min(100, score))
    
    # 6. 映射仓位建议
    if score >= 70:
        position_suggestion = "FULL"        # 全仓
        position_desc = "全仓（建议标准仓位）"
    elif score >= 40:
        position_suggestion = "HALF"        # 半仓
        position_desc = "半仓（建议降低仓位）"
    elif score >= 20:
        position_suggestion = "TRIAL"       # 试探仓
        position_desc = "试探仓（建议最小仓位）"
    else:
        position_suggestion = "AVOID"       # 避免开仓
        position_desc = "避免开仓（风险过高）"
    
    # 7. 返回完整信号字典
    return {
        "current_vix": current_vix,
        "vix_ma10": vix_ma10,
        "deviation_pct": deviation_pct,
        "signal_level": signal_level,
        "signal_color": signal_color,
        "ma10_slope": ma10_slope,
        "trend_strength": trend_strength,
        "vix_percentile": vix_percentile,
        "percentile_warning": percentile_warning,
        "composite_score": score,
        "position_suggestion": position_suggestion,
        "position_desc": position_desc,
        "data_points": len(vix_data),
        "last_update": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def integrate_with_other_factors(vix_signal, iv_rank=None, iv_hv_ratio=None, has_event=False):
    """
    将 VIX MA10 信号与其他因子集成
    
    Parameters:
    -----------
    vix_signal : dict
        get_vix_signal_details 返回的信号字典
    iv_rank : float, optional
        IV Rank 值（0-100）
    iv_hv_ratio : float, optional
        IV/HV 比值（百分比）
    has_event : bool, optional
        是否有重大事件
    
    Returns:
    --------
    dict
        集成后的综合信号
    """
    # 基础评分来自 VIX 信号
    base_score = vix_signal.get("composite_score", 50)
    
    # 各因子权重
    weights = {
        "vix": 0.4,      # VIX MA10 信号权重40%
        "iv_rank": 0.25,  # IV Rank 权重25%
        "iv_hv": 0.25,    # IV/HV 权重25%
        "event": 0.10     # 事件影响权重10%
    }
    
    # 计算各因子得分（0-100）
    # 1. VIX 得分直接使用 composite_score
    vix_score = base_score
    
    # 2. IV Rank 得分：越高越好（50-100为绿灯）
    if iv_rank is None or pd.isna(iv_rank):
        iv_rank_score = 50  # 中性
    elif iv_rank >= 50:
        iv_rank_score = 100  # 绿灯
    elif iv_rank >= 30:
        iv_rank_score = 60   # 黄灯
    else:
        iv_rank_score = 20   # 红灯
    
    # 3. IV/HV 得分：100-140%为最佳
    if iv_hv_ratio is None or pd.isna(iv_hv_ratio):
        iv_hv_score = 50  # 中性
    elif 100 <= iv_hv_ratio <= 140:
        iv_hv_score = 100  # 绿灯
    elif iv_hv_ratio > 160:
        iv_hv_score = 20   # 红灯
    else:
        iv_hv_score = 60   # 黄灯
    
    # 4. 事件得分：无事件为好
    event_score = 20 if has_event else 100
    
    # 计算加权总分
    weighted_score = (
        vix_score * weights["vix"] +
        iv_rank_score * weights["iv_rank"] +
        iv_hv_score * weights["iv_hv"] +
        event_score * weights["event"]
    )
    
    # 映射最终仓位建议
    if weighted_score >= 70:
        final_position = "FULL"
        final_desc = "全仓开仓"
    elif weighted_score >= 40:
        final_position = "HALF"
        final_desc = "半仓开仓"
    elif weighted_score >= 20:
        final_position = "TRIAL"
        final_desc = "试探仓"
    else:
        final_position = "AVOID"
        final_desc = "禁止开仓"
    
    return {
        "weighted_score": weighted_score,
        "final_position": final_position,
        "final_desc": final_desc,
        "factor_scores": {
            "vix": vix_score,
            "iv_rank": iv_rank_score,
            "iv_hv": iv_hv_score,
            "event": event_score
        },
        "factor_weights": weights,
        "vix_signal_details": vix_signal
    }

def generate_vix_signal_report():
    """
    生成完整的 VIX MA10 信号报告
    
    Returns:
    --------
    str
        格式化的报告文本
    """
    # 获取信号详情
    signal_details = get_vix_signal_details()
    
    if "error" in signal_details:
        return f"❌ 生成信号报告失败: {signal_details['error']}"
    
    report_lines = [
        "📊 VIX MA10 信号分析报告",
        "=" * 40,
        f"数据时间: {signal_details['last_update']}",
        f"数据点数: {signal_details['data_points']} 天",
        "",
        "1. 核心指标",
        f"   • 当前 VIX: {signal_details['current_vix']:.2f}",
        f"   • VIX MA10: {signal_details['vix_ma10']:.2f}",
        f"   • 偏离度: {signal_details['deviation_pct']:.1f}%",
        "",
        "2. 信号分析",
        f"   • 信号级别: {signal_details['signal_level']} {signal_details['signal_color']}",
        f"   • MA10斜率: {signal_details['ma10_slope']:.3f}",
        f"   • 趋势强度: {signal_details['trend_strength']}",
        f"   • 历史分位: {signal_details['vix_percentile']:.1f}%",
        f"   • 分位预警: {'是' if signal_details['percentile_warning'] else '否'}",
        "",
        "3. 综合评估",
        f"   • VIX综合评分: {signal_details['composite_score']:.1f}/100",
        f"   • 仓位建议: {signal_details['position_suggestion']}",
        f"   • 建议说明: {signal_details['position_desc']}",
        "",
        "4. 使用说明",
        "   • 绿灯(偏离度>5%): 允许开仓，建议全仓",
        "   • 黄灯(-5%≤偏离度≤5%): 限制仓位，建议半仓或试探仓",
        "   • 红灯(偏离度<-5%): 禁止开仓，建议观望",
        "   • MA10加速上升(斜率>0.5): 提示风险，建议降低仓位",
        "   • 历史分位>80%: 提示风险，建议谨慎",
    ]
    
    return "\n".join(report_lines)

# 主函数：测试信号生成
if __name__ == "__main__":
    print("🔍 测试 VIX MA10 信号体系...")
    
    # 生成报告
    report = generate_vix_signal_report()
    print(report)
    
    # 测试信号集成
    print("\n🔗 测试信号集成...")
    vix_signal = get_vix_signal_details()
    
    if "error" not in vix_signal:
        integrated_signal = integrate_with_other_factors(
            vix_signal,
            iv_rank=65,      # 示例值
            iv_hv_ratio=120,  # 示例值
            has_event=False
        )
        
        print(f"加权总分: {integrated_signal['weighted_score']:.1f}")
        print(f"最终仓位: {integrated_signal['final_desc']}")
        print(f"因子得分: VIX={integrated_signal['factor_scores']['vix']:.1f}, "
              f"IV Rank={integrated_signal['factor_scores']['iv_rank']:.1f}, "
              f"IV/HV={integrated_signal['factor_scores']['iv_hv']:.1f}, "
              f"事件={integrated_signal['factor_scores']['event']:.1f}")
    
    print("\n✅ VIX MA10 信号体系测试完成")