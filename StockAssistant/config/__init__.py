#!/usr/bin/env python3
"""
OptionAgent 配置文件
⚠️ 请填写自己的 API Key，不要提交到 GitHub
"""

# 代理配置
PROXY = 'http://127.0.0.1:7897'

# API配置
NEWS_API = "http://localhost:3000/api/s"

# Finnhub配置
FINNHUB_KEY = 'YOUR_FINNHUB_KEY'

# MiniMax配置（旧）
MINIMAX_API_KEY = 'YOUR_MINIMAX_API_KEY'
MINIMAX_BASE_URL = "https://api.minimaxi.com"

# LLM API 配置（OpenAI-compatible）
LLM_API_KEY = "YOUR_LLM_API_KEY"
LLM_BASE_URL = "https://llm.hytriu.cn/v1"
LLM_MODEL = "MiniMax-M2.7-highspeed"

# 日志配置
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
