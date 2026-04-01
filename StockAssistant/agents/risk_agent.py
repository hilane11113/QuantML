#!/usr/bin/env python3
"""
OptionAgent - 风险管理代理
类似于 TradingAgents 的 Risk Management
"""

import json

class RiskAgent:
    """风险管理代理"""
    
    def __init__(self):
        self.name = "RiskAgent"
    
    def evaluate(self, news_data, option_data, decision):
        """评估风险"""
        
        topics = news_data.get('topics', {})
        strategies = option_data.get('strategies', [])
        
        risk_level = "LOW"
        risk_factors = []
        position_size = "中等"
        stop_loss = "暂不设置"
        
        # 风险因素分析
        if '中东局势' in topics:
            risk_level = "HIGH"
            risk_factors.append("地缘政治风险升温")
        
        if '央行' in topics:
            risk_factors.append("央行政策不确定")
            if risk_level != "HIGH":
                risk_level = "MEDIUM"
        
        # 基于策略评估
        if strategies:
            best = strategies[0]
            rr = best.get('rr_ratio', 0)
            if rr < 1:
                risk_level = "HIGH"
                risk_factors.append("风险回报比过低")
            elif rr < 1.5:
                if risk_level == "LOW":
                    risk_level = "MEDIUM"
                risk_factors.append("风险回报比一般")
            
            # 最大亏损评估
            max_loss = best.get('max_loss', 0)
            if max_loss > 500:
                risk_factors.append("单笔最大亏损较高")
                if risk_level != "HIGH":
                    risk_level = "MEDIUM"
        
        # 仓位建议
        if risk_level == "HIGH":
            position_size = "轻仓 (10-20%)"
            stop_loss = "权利金的50%或$200"
        elif risk_level == "MEDIUM":
            position_size = "中等 (20-30%)"
            stop_loss = "权利金的30%"
        else:
            position_size = "正常 (30-40%)"
            stop_loss = "权利金的20%"
        
        return {
            'risk_level': risk_level,
            'risk_factors': risk_factors,
            'position_size': position_size,
            'stop_loss': stop_loss,
            'recommendation': self._get_recommendation(risk_level, decision)
        }
    
    def _get_recommendation(self, risk_level, decision):
        """获取建议"""
        
        if risk_level == "HIGH":
            return "建议观望或极轻仓"
        elif risk_level == "MEDIUM":
            return "建议轻仓操作"
        else:
            return "可以正常仓位操作"
    
    def run(self, news_data, option_data, decision):
        """执行风险评估"""
        return self.evaluate(news_data, option_data, decision)

if __name__ == "__main__":
    news = {'topics': {'中东局势': 5, 'A股': 3}}
    option = {'strategies': [{'type': 'Iron Condor', 'rr_ratio': 2.5, 'max_loss': 300}]}
    decision = {'action': 'BUY'}
    
    agent = RiskAgent()
    result = agent.run(news, option, decision)
    print(json.dumps(result, indent=2, ensure_ascii=False))
