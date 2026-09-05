# -*- coding: utf-8 -*-
"""App Atlas — App Store 全球比价工具后端。

模块划分:
  config   环境变量与常量
  cache    内存 + 磁盘缓存、per-key 防击穿锁
  store    用户 / 会话 / API 密钥 / 配置持久化
  apple    Apple 接口封装(搜索 / 详情 / 内购报价)与全局限速
  fx       汇率
  notify   推送渠道(Telegram / Bark / Webhook)
  monitor  价格监控定时任务
  tgbot    Telegram 查价机器人
  server   HTTP 路由与启动
"""

__version__ = "1.1.0"
