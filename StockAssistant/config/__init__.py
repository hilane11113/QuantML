#!/usr/bin/env python3
"""
OptionAgent 配置文件
"""

# 代理配置
PROXY = 'http://127.0.0.1:7897'

# API配置
NEWS_API = "http://localhost:3000/api/s"

# Finnhub配置
FINNHUB_KEY = 'd2cd2vpr01qihtcr7dkgd2cd2vpr01qihtcr7dl0'

# MiniMax配置（旧）
MINIMAX_API_KEY = 'sk-cp-h85POtIVYn0DGNzXAgTuCVYwpOVEa-b-B3rgZjprixoYSOBhwtDKwiXwECSNDzsiqgUuHy9U5LQUqKrheTV19L9Kuc9Mn3mrrm7wTlkduoqIjDkA8lYhIto'
MINIMAX_BASE_URL = "https://api.minimaxi.com"

# LLM API 配置（OpenAI-compatible）
LLM_API_KEY = "sk-5rNVlTyBkZrRLKVA5KvYOxFTjAZCjsPuo2qSAv2QFWGmmTut"
LLM_BASE_URL = "https://llm.hytriu.cn/v1"
LLM_MODEL = "MiniMax-M2.7-highspeed"

# 日志配置
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
