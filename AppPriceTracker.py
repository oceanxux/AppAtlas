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


def reset_password(username, new_password):
    """忘记密码时从命令行重置(仅本机/容器内可用,不影响其他数据)。"""
    import secrets
    from appatlas import store
    users, meta = store.load_users()
    if username not in users:
        print(f"❌ 用户 {username} 不存在")
        sys.exit(1)
    if len(new_password) < 6:
        print("❌ 新密码至少 6 位")
        sys.exit(1)
    users[username]["salt"] = secrets.token_hex(8)
    users[username]["hash"] = store._hash_password(users[username]["salt"], new_password)
    users[username]["must_change"] = 0
    store.save_users(users, meta)
    print(f"✅ 已重置 {username} 的密码，请用新密码登录")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "resetpw":
        if len(sys.argv) < 4:
            print("用法: python3 AppPriceTracker.py resetpw <用户名> <新密码>(至少 6 位)")
            sys.exit(1)
        reset_password(sys.argv[2], sys.argv[3])
    else:
        main()
