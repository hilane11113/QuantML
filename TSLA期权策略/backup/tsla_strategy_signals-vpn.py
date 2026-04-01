import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# 导入之前创建的策略信号数据库类

def setup_proxy(proxy_url=None):
    """设置HTTP和HTTPS代理"""
    proxy_url = 'http://127.0.0.1:7897'
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
    print(f"✅ 代理设置成功: {proxy_url}")
    return True

from create_strategy_signals_db import StrategySignalsDB

def safe_get(data, key, default=np.nan):
    """安全获取字典或Series中的值"""
    try:
        val = data.get(key, default)
        return val if pd.notna(val) else default
    except:
        return default

def calculate_hv(prices, window=30):
    """计算历史波动率（年化）"""
    if len(prices) < window + 1:
        return np.nan
    log_returns = np.log(prices / prices.shift(1))
    hv = log_returns.tail(window).std() * np.sqrt(252)
    # Ensure return value is a scalar
    hv_scalar = hv.item() if isinstance(hv, pd.Series) else hv
    return hv_scalar * 100  # 转为百分比

def get_vix_and_ma10():
    """获取VIX当前值和10日均线"""
    try:
        end = datetime.now()
        start = end - timedelta(days=30)
        vix = yf.download("^VIX", start=start, end=end, interval="1d")["Close"]
        if len(vix) < 10:
            return np.nan, np.nan
        ma10 = vix.tail(10).mean()
        current_vix = vix.iloc[-1]
        # Convert Series to scalar values
        current_vix = current_vix.item() if isinstance(current_vix, pd.Series) else current_vix
        ma10 = ma10.item() if isinstance(ma10, pd.Series) else ma10
        return current_vix, ma10
    except Exception as e:
        print(f"⚠️ 获取VIX数据失败: {e}")
        return np.nan, np.nan

def get_tsla_data():
    """获取TSLA价格、期权隐含波动率等"""
    try:
        tsla = yf.Ticker("TSLA")
        hist = tsla.history(period="60d")
        current_price = hist['Close'].iloc[-1] if not hist.empty else np.nan

        # 尝试获取最近到期的期权链以提取IV
        expiries = tsla.options
        if not expiries:
            return current_price, np.nan, np.nan, []

        # 选择最近的到期日（至少2天后）
        today = datetime.today().date()
        valid_expiries = [e for e in expiries if datetime.strptime(e, "%Y-%m-%d").date() > today + timedelta(days=1)]
        if not valid_expiries:
            return current_price, np.nan, np.nan, []

        near_expiry = valid_expiries[0]
        opt = tsla.option_chain(near_expiry)
        calls = opt.calls
        puts = opt.puts

        # 找最接近平值的PUT
        atm_strike = min(puts['strike'], key=lambda x: abs(x - current_price))
        atm_put = puts[puts['strike'] == atm_strike]
        
        iv = safe_get(atm_put.iloc[0] if not atm_put.empty else {}, 'impliedVolatility', np.nan)
        iv = iv * 100 if pd.notna(iv) else np.nan  # 转为百分比

        # 计算52周IV分位（需多日期IV，此处简化：用最近30天期权IV近似）
        # 实际中建议用ORATS等专业数据源，此处仅作示意
        iv_rank = np.nan  # yfinance无法直接获取历史IV序列，故设为NaN

        return current_price, iv, iv_rank, valid_expiries
    except Exception as e:
        print(f"⚠️ 获取TSLA数据失败: {e}")
        return np.nan, np.nan, np.nan, []

def estimate_iv_metrics(iv, hist_prices):
    """估算IV Rank和IV/HV（简化版）"""
    hv = calculate_hv(hist_prices) if len(hist_prices) > 30 else np.nan
    
    # 确保iv是标量值而不是Series对象
    if isinstance(iv, pd.Series):
        iv_scalar = iv.iloc[0] if len(iv) > 0 else np.nan
    else:
        iv_scalar = iv
    
    # 确保hv是标量值而不是Series对象
    if isinstance(hv, pd.Series):
        hv_scalar = hv.iloc[0] if len(hv) > 0 else np.nan
    else:
        hv_scalar = hv
    
    iv_hv_ratio = (iv_scalar / hv_scalar * 100) if pd.notna(iv_scalar) and pd.notna(hv_scalar) and hv_scalar > 0 else np.nan

    # 简化IV Rank：若IV > 50%，假设Rank高；否则低（实际需历史IV分布）
    iv_rank_est = 70 if pd.notna(iv_scalar) and iv_scalar > 50 else 40 if pd.notna(iv_scalar) and iv_scalar > 35 else 20

    return iv_rank_est, hv_scalar, iv_hv_ratio

def check_earnings_next_7_days():
    """检查未来7天是否有财报（简化：固定已知日期或返回False）"""
    # 实际应用中可接入财经日历API（如Finnhub、Alpha Vantage）
    # 此处仅作示例，返回False
    return False

def main():
    print("🚀 启动 TSLA Short Put Spread 决策引擎...\n")
    
    # 1. 设置代理
    setup_proxy()

    # 2. 获取VIX和MA10
    vix, vix_ma10 = get_vix_and_ma10()
    
    # 3. 获取TSLA数据
    tsla_price, iv, _, expiries = get_tsla_data()
    
    # 4. 获取TSLA历史价格用于HV计算
    hist = yf.download("TSLA", period="60d")["Close"]
    
    # 5. 估算IV Rank 和 HV
    iv_rank, hv, iv_hv_ratio = estimate_iv_metrics(iv, hist)
    
    # 6. 检查事件
    has_earnings = check_earnings_next_7_days()
    
    # 7. 打印所有指标
    print("📊 当前市场与TSLA指标:")
    print(f"  • TSLA 价格       : ${tsla_price:.2f}" if pd.notna(tsla_price) else "  • TSLA 价格       : ❌ 无法获取")
    print(f"  • VIX             : {vix:.2f}" if pd.notna(vix) else "  • VIX             : ❌ 无法获取")
    print(f"  • VIX 10日均线    : {vix_ma10:.2f}" if pd.notna(vix_ma10) else "  • VIX 10日均线    : ❌ 无法获取")
    print(f"  • TSLA IV         : {iv:.1f}%" if pd.notna(iv) else "  • TSLA IV         : ❌ 无法获取")
    print(f"  • 估算 IV Rank    : {iv_rank:.0f}%" if pd.notna(iv_rank) else "  • 估算 IV Rank    : ❌ 无法获取")
    print(f"  • 历史波动率 (HV) : {hv:.1f}%" if pd.notna(hv) else "  • 历史波动率 (HV) : ❌ 无法计算")
    print(f"  • IV / HV 比值    : {iv_hv_ratio:.0f}%" if pd.notna(iv_hv_ratio) else "  • IV / HV 比值    : ❌ 无法计算")
    print(f"  • 未来7天财报     : {'是' if has_earnings else '否'}")
    print()

    # 定义条件检查函数（在所有变量都确定后再定义，避免作用域问题）
    def check_iv_condition(iv):
        if pd.isna(iv): return "UNKNOWN"
        if iv > 65: return "RED"
        if 51 <= iv <= 65: return "YELLOW"
        if 30 <= iv <= 50: return "GREEN"
        return "YELLOW"  # <30

    def check_iv_rank_condition(rank):
        if pd.isna(rank): return "YELLOW"
        if rank >= 50: return "GREEN"
        if rank >= 30: return "YELLOW"
        return "RED"

    def check_iv_hv_condition(ratio):
        if pd.isna(ratio): return "YELLOW"
        if ratio > 160: return "RED"
        if 100 <= ratio <= 140: return "GREEN"
        return "YELLOW"

    # 计算条件
    iv_cond = check_iv_condition(iv)
    rank_cond = check_iv_rank_condition(iv_rank)
    hv_cond = check_iv_hv_condition(iv_hv_ratio)
    event_cond = "RED" if has_earnings else "GREEN"

    # 8. 决策逻辑
    # 修复问题1: 重新设计VIX趋势判断逻辑
    # 获取更多VIX数据来计算MA10的趋势
    try:
        vix_data = yf.download("^VIX", period="20d")["Close"]
        if len(vix_data) >= 20:
            # 计算今天的MA10
            ma10_today = vix_data.tail(10).mean()
            # 计算昨天的MA10（用前9天数据计算）
            ma10_yesterday = vix_data.tail(19).head(10).mean()
            # 确保是标量值再进行比较
            ma10_today_scalar = ma10_today.item() if isinstance(ma10_today, pd.Series) else ma10_today
            ma10_yesterday_scalar = ma10_yesterday.item() if isinstance(ma10_yesterday, pd.Series) else ma10_yesterday
            # 判断MA10是否上升
            ma10_is_rising = ma10_today_scalar > ma10_yesterday_scalar
        else:
            # 如果数据不足，使用之前的简单方法
            ma10_is_rising = True  # 默认为上升趋势
    except:
        # 如果下载VIX历史数据失败，使用之前的比较
        ma10_is_rising = True

    # 确保vix_ma10是标量值
    vix_ma10_scalar = vix_ma10.item() if isinstance(vix_ma10, pd.Series) else vix_ma10
    vix_scalar = vix.item() if isinstance(vix, pd.Series) else vix
    
    if pd.isna(vix_scalar) or pd.isna(vix_ma10_scalar):
        vix_status = "UNKNOWN"
        allow_check = False
    elif vix_scalar > vix_ma10_scalar and ma10_is_rising:  # 修复问题1：正确的MA10上升判断
        vix_status = "🔴红灯"
        allow_check = False
    elif vix_scalar < vix_ma10_scalar:
        vix_status = "🟢绿灯"
        allow_check = True
    else:
        vix_status = "🟡黄灯"
        allow_check = True

    print(f"🔍 VIX 趋势状态: {vix_status}")

    # 修复问题3: 检查关键数据是否缺失
    if pd.isna(iv):
        decision = "❌禁止（IV数据缺失）"
        print(f"\n🛑 决策结果: {decision}")
    # 修复问题2: 重新设计决策逻辑
    elif vix_status.startswith("🔴"):
        decision = "❌禁止（VIX趋势不利）"
        print(f"\n🛑 决策结果: {decision}")
    elif vix_status.startswith("🟡"):  # 黄灯区
        # 黄灯区不允许标准开仓
        conditions = [iv_cond, rank_cond, hv_cond, event_cond]
        red_count = conditions.count("RED")
        green_count = conditions.count("GREEN")
        
        print("\n📋 TSLA 个股条件检查:")
        print(f"  • IV (30–50%为绿)      : {iv_cond}")
        print(f"  • IV Rank (≥50%为绿)   : {rank_cond}")
        print(f"  • IV/HV (100–140%为绿) : {hv_cond}")
        print(f"  • 无事件 (无为绿)       : {event_cond}")
        
        if red_count > 0:
            decision = "❌禁止（存在红灯条件）"
            print(f"\n🛑 决策结果: {decision}（存在红灯条件）")
        else:
            decision = "⚠️试探（半仓，≤3天）"
            print(f"\n⚠️ 决策结果: {decision}，密切监控IV变化")
    else:  # 绿灯区
        conditions = [iv_cond, rank_cond, hv_cond, event_cond]
        red_count = conditions.count("RED")
        green_count = conditions.count("GREEN")

        print("\n📋 TSLA 个股条件检查:")
        print(f"  • IV (30–50%为绿)      : {iv_cond}")
        print(f"  • IV Rank (≥50%为绿)   : {rank_cond}")
        print(f"  • IV/HV (100–140%为绿) : {hv_cond}")
        print(f"  • 无事件 (无为绿)       : {event_cond}")

        if red_count > 0:
            decision = "❌禁止（存在红灯条件）"
            print(f"\n🛑 决策结果: {decision}（存在红灯条件）")
        elif green_count >= 3:
            decision = "✅开仓"
            print(f"\n✅ 决策结果: {decision}！建议：35点 Short Put Spread，持有5–7天")
        else:
            decision = "⚠️试探（半仓，≤3天）"
            print(f"\n⚠️ 决策结果: {decision}，密切监控IV变化")
    
    # 获取实际可用的期权执行价来计算推荐的执行价
    try:
        # 获取TSLA期权链
        tsla = yf.Ticker("TSLA")
        expiries = tsla.options
        if expiries:
            # 选择最近的到期日
            near_expiry = expiries[0]
            opt = tsla.option_chain(near_expiry)
            puts = opt.puts
            
            # 找到最接近当前价格的执行价作为ATM
            if not puts.empty and pd.notna(tsla_price):
                atm_strike = min(puts['strike'], key=lambda x: abs(x - tsla_price))
                
                # 根据VIX值决定系数
                vix_scalar = vix.item() if isinstance(vix, pd.Series) else vix
                if pd.notna(vix_scalar) and vix_scalar > 17:
                    long_strike = atm_strike * 0.92
                    short_strike = long_strike - 20
                else:
                    long_strike = atm_strike * 0.96
                    short_strike = long_strike - 35
                
                spread_width = abs(long_strike - short_strike)
            else:
                # 如果无法获取期权数据，使用默认计算
                long_strike = tsla_price * 0.95 if pd.notna(tsla_price) else 0.0
                short_strike = tsla_price * 0.90 if pd.notna(tsla_price) else 0.0
                spread_width = abs(long_strike - short_strike)
        else:
            # 如果没有期权数据，使用默认计算
            long_strike = tsla_price * 0.95 if pd.notna(tsla_price) else 0.0
            short_strike = tsla_price * 0.90 if pd.notna(tsla_price) else 0.0
            spread_width = abs(long_strike - short_strike)
    except Exception as e:
        print(f"⚠️ 获取实际期权执行价失败，使用默认计算: {e}")
        # 如果出现异常，使用默认计算
        long_strike = tsla_price * 0.95 if pd.notna(tsla_price) else 0.0
        short_strike = tsla_price * 0.90 if pd.notna(tsla_price) else 0.0
        spread_width = abs(long_strike - short_strike)

    # 特殊情况处理：如果最后信号为红色，按指定公式计算价差策略，但不存入数据库
    if decision.startswith("❌") and pd.notna(tsla_price):  # 最后信号为红色的情况
        try:
            # 使用期权链找到ATM价格
            if expiries:
                near_expiry = expiries[0]
                opt = tsla.option_chain(near_expiry)
                puts = opt.puts
                
                if not puts.empty:
                    atm_strike = min(puts['strike'], key=lambda x: abs(x - tsla_price))
                    
                    # 按照指定公式计算执行价格
                    special_long_strike = atm_strike * 0.94
                    special_short_strike = special_long_strike - 20
                    
                    print(f"\n💡 特殊策略提示（非数据库记录）:")
                    print(f"  当前ATM价格: {atm_strike}")
                    print(f"  多头执行价 (Long Strike): {special_long_strike:.2f}")
                    print(f"  空头执行价 (Short Strike): {special_short_strike:.2f}")
                    print(f"  价差宽度: {abs(special_long_strike - special_short_strike):.2f}")
                    print(f"  ⚠️ 注意：Vega可能变大，注意风险")
        except Exception as e:
            print(f"⚠️ 特殊策略计算失败: {e}")
    
    # 存储策略信号到数据库
    try:
        db = StrategySignalsDB()
        
        # 准备要存储的信号数据 - 包含新增的字段
        signal_data = (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # RunDateTime
            'TSLA',                                        # UnderlyingSymbol
            'Put',                                         # OptionType
            long_strike,                                   # LongStrike
            short_strike,                                  # ShortStrike
            spread_width,                                  # SpreadWidth
            vix if pd.notna(vix) else 0.0,                 # VIXLevel
            iv if pd.notna(iv) else 0.0,                   # IVLevel
            iv_rank if pd.notna(iv_rank) else 0.0,         # IVRankEstimate
            iv_hv_ratio if pd.notna(iv_hv_ratio) else 0.0, # IV_HV_Ratio
            int(has_earnings),                             # HasEarnings (0 or 1)
            vix_status,                                    # VIX_TrendStatus
            iv_cond,                                       # IVCondition
            decision,                                      # Decision
            0,                                             # IsRealTrade (初始为0，模拟信号)
            0.0,                                           # ProfitLoss (初始为0)
            0.0,                                           # Cost (初始为0)
            f"VIX:{vix_status}, IV:{iv_cond}, Earnings:{'Yes' if has_earnings else 'No'}"  # Notes
        )
        
        # 插入信号记录到数据库
        signal_id = db.insert_signal(signal_data)
        #print(f"\n💾 策略信号已保存到数据库，记录ID: {signal_id}")
        
            # 显示最近的策略信号记录（简化版）
        print("\n📋 最近信号:")
        recent_signals = db.get_latest_signals(limit=3)
        for _, signal in recent_signals.iterrows():
            print(f"  {signal['RunDateTime'][5:16]} {signal['Decision'][:6]} VIX:{signal['VIXLevel']:.1f} IV:{signal['IVLevel']:.1f}")
                  
        # 显示决策统计
        #print("\n📈 决策统计:")
        #decision_stats = db.get_decision_stats()
        #print(decision_stats.to_string(index=False))
        
        # 显示绩效统计
        #print("\n💰 绩效统计:")
        #performance_stats = db.get_performance_by_decision()
        #print(performance_stats.to_string(index=False))
                  
    except Exception as e:
        print(f"❌ 保存策略信号到数据库时出错: {e}")

if __name__ == "__main__":
    main()