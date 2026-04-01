# 新闻分析项目配置

## 项目信息
- 项目名称: newsnow 新闻分析
- 部署位置: /root/.openclaw/workspace/newsnow
- API 端口: 3000

## 启动命令
```bash
cd /root/.openclaw/workspace/newsnow
PORT=3000 node dist/output/server/index.mjs &
```

## API 接口
- 华尔街见闻: curl http://localhost:3000/api/s?id=wallstreetcn
- 财联社: curl http://localhost:3000/api/s?id=cls
- 格隆汇: curl http://localhost:3000/api/s?id=gelonghui
- 金十数据: curl http://localhost:3000/api/s?id=jin10

## 新闻推送脚本
- 位置: /root/.openclaw/workspace/newsnow/news_push.py
- 功能: 自动抓取并格式化财经新闻

## 定时任务
可配置 cron 任务定期推送新闻
