#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App Store 全球比价工具 — 启动入口
========================================
功能:
  • 应用搜索 (iTunes Search API)
  • 应用本身价格跨地区对比 (iTunes Lookup API)
  • 内购订阅价格跨地区对比 (apps.apple.com 内部 API)
  • 实时汇率换算
  • 价格监控 + Telegram / Bark / Webhook 推送
  • Telegram 查价机器人
  • REST API(可开启密钥保护)

技术:
  • 仅使用 Python 标准库 (无需 pip install)
  • 实现拆分在 appatlas/ 包内,本文件只是一键启动入口
  • 本地 HTTP 服务,默认监听 127.0.0.1:8765
  • 启动后自动打开浏览器;关闭:在终端窗口按 Ctrl+C
"""
import sys
from pathlib import Path

# 保证双击/任意工作目录启动都能找到 appatlas 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from appatlas.server import main

if __name__ == "__main__":
    main()
