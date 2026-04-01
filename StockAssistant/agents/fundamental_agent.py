#!/usr/bin/env python3
"""
FundamentalAgent - 基本面分析代理
使用 tushare 获取 A股基本面数据
"""

import warnings
warnings.filterwarnings('ignore')

# Token 配置
TUSHARE_TOKEN = '92adb3188debf618f297c1ff102cdde6ac8b575aceae620d340aad3f'

def code_to_tushare(code: str) -> str:
    """转换为 tushare 格式"""
    if code.startswith('6'):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"

class FundamentalAgent:
    """基本面分析代理"""
    
    def __init__(self):
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        self.pro = ts.pro_api()
    
    def run(self, symbol: str) -> dict:
        """
        获取A股基本面数据
        
        Returns:
            dict: 包含估值、盈利能力、成长性、财务数据
        """
        print(f"  📊 正在获取基本面数据: {symbol}")
        
        try:
            result = {
                "symbol": symbol,
                "success": True
            }
            
            ts_code = code_to_tushare(symbol)
            
            # 获取财务指标
            try:
                df_fina = self.pro.fina_indicator(ts_code=ts_code, start_date='20250101', end_date='20260320')
                if not df_fina.empty:
                    latest = df_fina.iloc[0]
                    
                    # 盈利能力
                    result["profitability"] = {
                        "roe": float(latest.get('roe', 0)),           # 净资产收益率
                        "roa": float(latest.get('roa', 0)),           # 资产收益率
                        "gross_margin": float(latest.get('grossprofit_rate', 0)),  # 毛利率
                        "net_margin": float(latest.get('netprofit_margin', 0)),   # 净利率
                    }
                    
                    # 估值指标
                    result["valuation"] = {
                        "pe": float(latest.get('pe', 0)),             # 市盈率
                        "pb": float(latest.get('pb', 0)),             # 市净率
                        "ps": float(latest.get('ps', 0)),             # 市销率
                    }
                    
                    # 成长性
                    result["growth"] = {
                        "revenue_growth": float(latest.get('revenue_revenue_yearly_yoy', 0)),  # 营收增速
                        "profit_growth": float(latest.get('profit_revenue_yearly_yoy', 0)),      # 利润增速
                    }
                    
                    # 财务状况
                    result["financial"] = {
                        "debt_ratio": float(latest.get('debt_to_assets', 0)),  # 资产负债率
                        "current_ratio": float(latest.get('current_ratio', 0)),  # 流动比率
                        "quick_ratio": float(latest.get('quick_ratio', 0)),      # 速动比率
                    }
                    
                    print(f"  → 财务指标获取成功")
                else:
                    result["error"] = "无财务数据"
            except Exception as e:
                print(f"  ⚠️ 财务指标失败: {str(e)[:50]}")
                result["profitability"] = {}
                result["valuation"] = {}
                result["growth"] = {}
                result["financial"] = {}
            
            # 获取股票基本信息
            try:
                df_basic = self.pro.stock_basic(ts_code=ts_code, fields='name,industry,market,list_date')
                if not df_basic.empty:
                    result["info"] = {
                        "name": df_basic.iloc[0]['name'],
                        "industry": df_basic.iloc[0]['industry'],
                        "market": df_basic.iloc[0]['market'],
                        "list_date": df_basic.iloc[0]['list_date'],
                    }
                    print(f"  → 基本信息: {result['info']['name']} | {result['info']['industry']}")
            except Exception as e:
                print(f"  ⚠️ 基本信息失败: {str(e)[:50]}")
            
            return result
            
        except Exception as e:
            return {
                "error": f"错误: {str(e)}",
                "success": False
            }

def format_fundamental_report(data: dict) -> str:
    """格式化基本面分析报告"""
    if "error" in data:
        return f"❌ 基本面获取失败: {data['error']}"
    
    info = data.get("info", {})
    name = info.get('name', data.get('symbol', ''))
    industry = info.get('industry', 'N/A')
    
    valuation = data.get("valuation", {})
    profitability = data.get("profitability", {})
    growth = data.get("growth", {})
    financial = data.get("financial", {})
    
    report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 基本面分析 | {name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 行业: {industry}

💰 估值指标:
   市盈率 (PE): {valuation.get('pe', 0):.2f}
   市净率 (PB): {valuation.get('pb', 0):.2f}
   市销率 (PS): {valuation.get('ps', 0):.2f}

📈 盈利能力:
   净资产收益率 (ROE): {profitability.get('roe', 0):.2f}%
   资产收益率 (ROA): {profitability.get('roa', 0):.2f}%
   毛利率: {profitability.get('gross_margin', 0):.2f}%
   净利率: {profitability.get('net_margin', 0):.2f}%

📊 成长性:
   营收增速: {growth.get('revenue_growth', 0):.2f}%
   利润增速: {growth.get('profit_growth', 0):.2f}%

🏦 财务状况:
   资产负债率: {financial.get('debt_ratio', 0):.2f}%
   流动比率: {financial.get('current_ratio', 0):.2f}
   速动比率: {financial.get('quick_ratio', 0):.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    return report

def score_fundamental(data: dict) -> dict:
    """基本面综合评分"""
    if "error" in data:
        return {"score": 0, "level": "N/A"}
    
    scores = {"valuation": 0, "profitability": 0, "growth": 0, "financial": 0}
    
    # 估值评分 (30%) - PE越低越好
    pe = data.get("valuation", {}).get('pe', 0)
    if 0 < pe < 10:
        scores["valuation"] = 30
    elif 10 <= pe < 20:
        scores["valuation"] = 25
    elif 20 <= pe < 30:
        scores["valuation"] = 20
    elif 30 <= pe < 50:
        scores["valuation"] = 10
    elif pe >= 50 or pe <= 0:
        scores["valuation"] = 5
    
    # 盈利能力 (40%) - ROE越高越好
    roe = data.get("profitability", {}).get('roe', 0)
    if roe > 20:
        scores["profitability"] = 40
    elif 15 <= roe <= 20:
        scores["profitability"] = 35
    elif 10 <= roe < 15:
        scores["profitability"] = 25
    elif 5 <= roe < 10:
        scores["profitability"] = 15
    elif roe > 0:
        scores["profitability"] = 10
    else:
        scores["profitability"] = 0
    
    # 成长性 (20%)
    rev_growth = data.get("growth", {}).get('revenue_growth', 0)
    if rev_growth > 30:
        scores["growth"] = 20
    elif 20 <= rev_growth <= 30:
        scores["growth"] = 17
    elif 10 <= rev_growth < 20:
        scores["growth"] = 14
    elif 0 <= rev_growth < 10:
        scores["growth"] = 10
    else:
        scores["growth"] = 5
    
    # 财务状况 (10%) - 负债率越低越好
    debt_ratio = data.get("financial", {}).get('debt_ratio', 100)
    if 0 <= debt_ratio < 30:
        scores["financial"] = 10
    elif 30 <= debt_ratio < 50:
        scores["financial"] = 8
    elif 50 <= debt_ratio < 70:
        scores["financial"] = 5
    else:
        scores["financial"] = 2
    
    total = sum(scores.values())
    
    if total >= 80:
        level = "🟢 优秀"
    elif total >= 60:
        level = "🟡 良好"
    elif total >= 40:
        level = "🟠 一般"
    else:
        level = "🔴 较差"
    
    return {
        "total": total,
        "level": level,
        "breakdown": scores
    }
