#!/usr/bin/env python3
"""
LLMChatAgent - LLM 对话增强代理
使用 MiniMax API 进行自然语言交互
"""

import json
import os
import requests

# LLM API 配置（OpenAI-compatible）
LLM_API_KEY = "sk-5rNVlTyBkZrRLKVA5KvYOxFTjAZCjsPuo2qSAv2QFWGmmTut"
LLM_BASE_URL = "https://llm.hytriu.cn/v1"
LLM_MODEL = "MiniMax-M2.7-highspeed"

def chat_with_llm(prompt: str, context: dict = None) -> str:
    """
    使用 LLM API 进行对话（OpenAI-compatible）
    
    Args:
        prompt: 用户输入
        context: 上下文信息（持仓、绩效等）
    
    Returns:
        str: LLM 回复
    """
    # 构建系统提示
    system_prompt = """你是一个专业的股票投资助手，名叫"小Q助手"。

你的职责：
1. 回答用户关于股票分析的问题
2. 解读技术指标和基本面数据
3. 提供投资建议（但不构成投资建议）
4. 解释期权策略

你应该：
- 用简洁易懂的语言解释专业术语
- 给出明确的分析结论
- 提醒投资风险
- 适当使用 emoji 增加可读性

当前用户有以下信息：
"""

    # 添加上下文
    if context:
        positions = context.get('positions', [])
        performance = context.get('performance', {})
        
        if positions:
            system_prompt += f"\n当前持仓：\n"
            for p in positions:
                system_prompt += f"- {p['symbol']}: {p['quantity']}股, 成本${p['avg_cost']:.2f}, 现价${p['current_price']:.2f}, 盈亏{p['pnl_pct']:+.2f}%\n"
        else:
            system_prompt += "\n当前持仓：空仓\n"
        
        system_prompt += f"\n绩效统计：\n"
        system_prompt += f"- 总交易次数: {performance.get('total_trades', 0)}\n"
        system_prompt += f"- 胜率: {performance.get('win_rate', 0):.1f}%\n"
        system_prompt += f"- 总盈亏: {performance.get('total_pnl', 0):.2f}元\n"
    
    system_prompt += "\n请用友好的方式回答用户的问题。"
    
    try:
        headers = {
            'Authorization': f'Bearer {LLM_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 512,
            "temperature": 0.7
        }
        
        response = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        result = response.json()
        if result.get('choices') and len(result['choices']) > 0:
            return result['choices'][0]['message']['content']
        if result.get('error'):
            return f"API错误: {result['error']}"
    except Exception as e:
        return f"请求错误: {str(e)}"
    
    return "抱歉，暂时无法回复。"

def chat_with_llm(prompt: str, context: dict = None) -> str:
    """
    使用 MiniMax API 进行对话
    
    Args:
        prompt: 用户输入
        context: 上下文信息（持仓、绩效等）
    
    Returns:
        str: LLM 回复
    """
    # 构建系统提示
    system_prompt = """你是一个专业的股票投资助手，名叫"小Q助手"。

你的职责：
1. 回答用户关于股票分析的问题
2. 解读技术指标和基本面数据
3. 提供投资建议（但不构成投资建议）
4. 解释期权策略

你应该：
- 用简洁易懂的语言解释专业术语
- 给出明确的分析结论
- 提醒投资风险
- 适当使用 emoji 增加可读性

当前用户有以下信息：
"""

    # 添加上下文
    if context:
        positions = context.get('positions', [])
        performance = context.get('performance', {})
        
        if positions:
            system_prompt += f"\n当前持仓：\n"
            for p in positions:
                system_prompt += f"- {p['symbol']}: {p['quantity']}股, 成本${p['avg_cost']:.2f}, 现价${p['current_price']:.2f}, 盈亏{p['pnl_pct']:+.2f}%\n"
        else:
            system_prompt += "\n当前持仓：空仓\n"
        
        system_prompt += f"\n绩效统计：\n"
        system_prompt += f"- 总交易次数: {performance.get('total_trades', 0)}\n"
        system_prompt += f"- 胜率: {performance.get('win_rate', 0):.1f}%\n"
        system_prompt += f"- 总盈亏: {performance.get('total_pnl', 0):.2f}元\n"
    
    system_prompt += "\n请用友好的方式回答用户的问题。"
    
    try:
        headers = {
            'Authorization': f'Bearer {MINIMAX_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "model": "abab6.5-chat",
            "messages": [
                {"role": "user", "content": system_prompt + "\n\n用户问题: " + prompt, "sender_name": "user", "sender_type": "USER"}
            ],
            "tokens_to_generate": 512,
            "temperature": 0.7,
            "bot_setting": [
                {
                    "bot_name": "assistant",
                    "content": system_prompt
                }
            ],
            "reply_constraints": {
                "reply_language": "zh",
                "sender_type": "BOT",
                "sender_name": "assistant"
            }
        }
        
        response = requests.post(MINIMAX_BASE_URL, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            reply = result.get('reply', '')
            if reply:
                return reply
            # 检查 choices
            choices = result.get('choices', [])
            if choices:
                msgs = choices[0].get('messages', [])
                if msgs:
                    return msgs[-1].get('content', '抱歉，无法生成回复')
            return '抱歉，未收到回复'
        else:
            return f"API 错误: {response.status_code}"
    
    except requests.exceptions.Timeout:
        return "请求超时，请稍后重试"
    except Exception as e:
        return f"发生错误: {str(e)}"


def generate_recommendation(stock_data: dict, fundamental_data: dict = None) -> str:
    """
    生成股票推荐理由
    
    Args:
        stock_data: 股票技术数据
        fundamental_data: 基本面数据
    """
    prompt = f"""请根据以下数据生成简短的股票分析：

股票代码: {stock_data.get('symbol')}
当前价格: {stock_data.get('price')}
涨跌幅: {stock_data.get('change_pct', 0):.2f}%
趋势: {stock_data.get('trend', 'N/A')}
RSI: {stock_data.get('technical', {}).get('rsi', 0):.1f}

"""
    
    if fundamental_data and 'error' not in fundamental_data:
        prompt += f"""
基本面:
- ROE: {fundamental_data.get('profitability', {}).get('roe', 0):.2f}%
- PE: {fundamental_data.get('valuation', {}).get('pe', 0):.2f}
"""
    
    prompt += "\n请给出30字以内的简短投资建议，以 emoji 开头。"
    
    return chat_with_llm(prompt)


class LLMChatAgent:
    """LLM 对话代理"""
    
    def __init__(self):
        self.conversation_history = []
    
    def chat(self, user_input: str, context: dict = None) -> str:
        """
        处理用户对话
        
        Args:
            user_input: 用户输入
            context: 上下文（持仓、当前分析等）
        
        Returns:
            str: 回复内容
        """
        # 添加到历史
        self.conversation_history.append({"role": "user", "content": user_input})
        
        # 生成回复
        response = chat_with_llm(user_input, context)
        
        # 添加到历史
        self.conversation_history.append({"role": "assistant", "content": response})
        
        # 保持历史简洁（最近10轮）
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
        
        return response
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []


def intent_recognition(user_input: str) -> dict:
    """
    意图识别
    
    Args:
        user_input: 用户输入
    
    Returns:
        dict: 识别的意图和参数
    """
    user_input_lower = user_input.lower()
    
    # 买入意图
    buy_keywords = ['买', '买入', '做多', '开多', '买入', 'buy', 'long']
    if any(kw in user_input_lower for kw in buy_keywords):
        # 尝试提取股票代码
        import re
        codes = re.findall(r'\d{6}', user_input)
        if codes:
            return {"intent": "buy", "symbol": codes[0]}
        symbols = re.findall(r'[A-Z]{2,5}', user_input.upper())
        if symbols:
            return {"intent": "buy", "symbol": symbols[0]}
        return {"intent": "buy", "symbol": None}
    
    # 卖出意图
    sell_keywords = ['卖', '卖出', '平仓', '止盈', '止损', 'sell', 'close']
    if any(kw in user_input_lower for kw in sell_keywords):
        import re
        codes = re.findall(r'\d{6}', user_input)
        if codes:
            return {"intent": "sell", "symbol": codes[0]}
        symbols = re.findall(r'[A-Z]{2,5}', user_input.upper())
        if symbols:
            return {"intent": "sell", "symbol": symbols[0]}
        return {"intent": "sell", "symbol": None}
    
    # 分析意图
    analyze_keywords = ['分析', '看看', '怎么样', '建议', 'analyze', 'look', 'recommend']
    if any(kw in user_input_lower for kw in analyze_keywords):
        import re
        codes = re.findall(r'\d{6}', user_input)
        if codes:
            return {"intent": "analyze", "symbol": codes[0], "market": "A"}
        symbols = re.findall(r'[A-Z]{2,5}', user_input.upper())
        if symbols:
            return {"intent": "analyze", "symbol": symbols[0], "market": "US"}
        return {"intent": "analyze", "symbol": None}
    
    # 持仓查询
    portfolio_keywords = ['持仓', '仓位', '有什么', ' portfolio', 'position']
    if any(kw in user_input_lower for kw in portfolio_keywords):
        return {"intent": "portfolio"}
    
    # 绩效查询
    performance_keywords = ['盈亏', '赚了多少', '亏了多少', '绩效', 'pnl', 'profit']
    if any(kw in user_input_lower for kw in performance_keywords):
        return {"intent": "performance"}
    
    # 默认：对话
    return {"intent": "chat"}
