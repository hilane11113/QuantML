#!/usr/bin/env python3
"""
AShareAgent - A股股票分析代理
功能：股票数据、技术指标，资金流向（无期权）
使用 tushare 获取数据
"""

import warnings
warnings.filterwarnings('ignore')

# Token 配置
TUSHARE_TOKEN = '92adb3188debf618f297c1ff102cdde6ac8b575aceae620d340aad3f'

def detect_market(code: str) -> str:
    """智能识别市场"""
    code = code.strip().upper()
    
    # A股：6位数字
    if code.isdigit() and len(code) == 6:
        if code.startswith('6'):
            return "A_SHARE_SH"  # 上海
        elif code.startswith(('0', '3')):
            return "A_SHARE_SZ"  # 深圳/创业板
        else:
            return "A_SHARE"
    
    # 美股：大写字母，1-5位
    elif code.isupper() and len(code) <= 5 and code.isalpha():
        return "US_STOCK"
    
    return "UNKNOWN"

def code_to_tushare(code: str) -> str:
    """转换为 tushare 格式"""
    if code.startswith('6'):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"

class AShareAgent:
    """A股分析代理"""
    
    def __init__(self):
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        self.pro = ts.pro_api()
    
    def run(self, symbol: str) -> dict:
        """
        分析A股股票
        
        Args:
            symbol: A股代码（6位数字，如 000001, 600519, 510050）
        
        Returns:
            dict: 包含市场、价格、技术指标，资金流向等
        """
        print(f"  📊 正在获取A股数据: {symbol}")
        
        try:
            result = {
                "market": "A_SHARE",
                "symbol": symbol,
                "success": True
            }
            
            # 转换为 tushare 格式
            ts_code = code_to_tushare(symbol)
            
            # 获取日线数据
            from datetime import datetime, timedelta
            end_date = datetime.now().strftime('%Y%m%d')
            start_date_5d = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
            start_date_60d = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
            
            try:
                df_5d = self.pro.daily(ts_code=ts_code, start_date=start_date_5d, end_date=end_date)
                print(f"  → 5日数据: {len(df_5d)} 条")
            except Exception as e:
                print(f"  ⚠️ 5日数据失败: {str(e)[:50]}")
                df_5d = None
            
            try:
                df_60d = self.pro.daily(ts_code=ts_code, start_date=start_date_60d, end_date=end_date)
                print(f"  → 60日数据: {len(df_60d)} 条")
            except Exception as e:
                print(f"  ⚠️ 60日数据失败: {str(e)[:50]}")
                df_60d = None
            
            # 解析价格数据
            if df_5d is not None and not df_5d.empty:
                latest = df_5d.iloc[0]  # 第一行是最新的
                prev = df_5d.iloc[1] if len(df_5d) > 1 else latest
                
                result.update({
                    "name": symbol,
                    "price": float(latest['close']),
                    "change_pct": float(latest['pct_chg']),
                    "open": float(latest['open']),
                    "high": float(latest['high']),
                    "low": float(latest['low']),
                    "volume": float(latest['vol']),
                    "amount": float(latest['amount']),
                    "prev_close": float(prev['close']),
                })
                
                # 获取股票名称
                try:
                    stock_basic = self.pro.stock_basic(ts_code=ts_code, fields='name')
                    if not stock_basic.empty:
                        result["name"] = stock_basic.iloc[0]['name']
                except:
                    pass
            else:
                result["name"] = symbol
                result["price"] = 0
                result["change_pct"] = 0
            
            # 计算技术指标
            if df_60d is not None and not df_60d.empty:
                try:
                    closes = df_60d['close'].values[::-1]  # 反转，最早的在前面
                    ma5 = float(pd.Series(closes).tail(5).mean())
                    ma10 = float(pd.Series(closes).tail(10).mean())
                    ma20 = float(pd.Series(closes).tail(20).mean())
                    
                    # 计算RSI
                    deltas = pd.Series(closes).diff()
                    gains = deltas.where(deltas > 0, 0)
                    losses = -deltas.where(deltas < 0, 0)
                    avg_gain = gains.tail(14).mean()
                    avg_loss = losses.tail(14).mean()
                    rs = avg_gain / avg_loss if avg_loss != 0 else 100
                    rsi = float(100 - (100 / (1 + rs)))
                    
                    result["technical"] = {
                        "ma5": ma5,
                        "ma10": ma10,
                        "ma20": ma20,
                        "rsi": rsi,
                    }
                    
                    # 趋势判断
                    price = result.get('price', ma5)
                    if price > ma5 > ma10 > ma20:
                        result["trend"] = "强势上涨"
                    elif price > ma5 > ma10:
                        result["trend"] = "上涨趋势"
                    elif ma5 > price > ma10:
                        result["trend"] = "震荡整理"
                    elif price < ma5 < ma10:
                        result["trend"] = "下跌趋势"
                    else:
                        result["trend"] = "弱势整理"
                except Exception as e:
                    print(f"  ⚠️ 技术指标计算失败: {str(e)[:50]}")
            
            # 获取资金流向（可选）
            try:
                mkt = 'sh' if symbol.startswith('6') else 'sz'
                money = self.pro.moneyflow(ts_code=ts_code)
                if not money.empty:
                    latest = money.iloc[0]
                    result["money_flow"] = {
                        "main_inflow": float(latest.get('buy_sm_amount', 0)) - float(latest.get('sell_sm_amount', 0)),
                        "retail_inflow": float(latest.get('buy_md_amount', 0)) - float(latest.get('sell_md_amount', 0)),
                    }
            except Exception as e:
                print(f"  ⚠️ 资金流向失败: {str(e)[:50]}")
            
            return result
            
        except Exception as e:
            return {
                "error": f"错误: {str(e)}",
                "success": False
            }

def format_a_stock_report(data: dict) -> str:
    """格式化A股分析报告"""
    if "error" in data:
        return f"❌ 分析失败: {data['error']}"
    
    name = data.get('name', data.get('symbol'))
    price = data.get('price', 0)
    change = data.get('change_pct', 0)
    trend = data.get('trend', 'N/A')
    
    emoji = "🟢" if change >= 0 else "🔴"
    sign = "+" if change >= 0 else ""
    
    report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 A股分析报告 | {name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 最新价: {price:.3f} {emoji} {sign}{change:.2f}%
📊 趋势: {trend}

📊 技术指标:"""
    
    if "technical" in data:
        tech = data["technical"]
        report += f"""
   MA5:  {tech.get('ma5', 0):.3f}
   MA10: {tech.get('ma10', 0):.3f}
   MA20: {tech.get('ma20', 0):.3f}
   RSI:  {tech.get('rsi', 50):.1f}"""
    
    if "money_flow" in data:
        mf = data["money_flow"]
        report += f"""
💵 资金流向:
   主力净流入: {mf.get('main_inflow', 0):,.0f}元
   散户净流入: {mf.get('retail_inflow', 0):,.0f}元"""
    
    report += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    return report

# 导入 pandas 用于计算
import pandas as pd
