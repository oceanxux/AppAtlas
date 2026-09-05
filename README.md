# 🌍  比价工具

> 运行 Python 脚本或 Docker 部署 → 浏览器自动打开 → 搜索 App → 一键看 175 个国家的订阅价格对比

## 🆕 V2.2 (2026-09)

- 🎨 **全新 UI**：首页 / 搜索页 / 详情页三页路由（浏览器前进后退可用），首页只有一个搜索框 + 热门 App 快捷入口
- 🌙 **深色模式**：自动跟随系统 + 手动切换（右上角 🌙/☀️）
- 🔐 **账号系统**：支持注册 / 登录，默认只展示各国价格；登录后解锁监控列表、订阅家族大表、多 App 对比、历史走势与导出 CSV
  - 默认管理员 `admin / admin123`（首次启动自动创建 `users.json`，可用环境变量 `APT_ADMIN_PASSWORD` 覆盖）
  - 管理员在右上角「用户」面板：给别人授管理员、重置密码、删号、开关注册
- 🌏 **区域覆盖增强**：后端全局请求节流 + 429 多级退避重试 + 查询结果落盘缓存（`cache.json`），30 区查询不再出现"网络失败"，重复查询秒出
- 🔔 **价格监控 + Telegram 推送**：详情页点「监控」配置通知时机（降价/涨价/新增/移除套餐）与限定套餐/区域，后端定时任务（`MONITOR_HOURS`，默认 6 小时）自动比对并推送
- 🔑 **API 密钥**：登录后右上角「API」创建密钥，脚本带 `X-API-Key` 头即可调用全部数据接口
- 📱 **详情页丰富化**：App 截图横滑、「关于此 App」全文展开、信息栅格（版本/大小/更新时间等）
- 🌍 英文界面下地区名自动本地化（Intl.DisplayNames）
- 🐛 修复：i18n 漏翻、复制功能与表格换算币种不一致、图表币种跟随换算选择等



## 📜 License

[MIT](LICENSE) © 2026 paradossio

## 🙏 致谢
- [fork 大佬](https://github.com/paradossio/AppPriceTracker-iOS)
- [Apple iTunes Search API](https://performance-partners.apple.com/search-api) — 应用搜索 + 价格数据源
- [@fawazahmed0/currency-api](https://github.com/fawazahmed0/exchange-api) — 免费汇率 CDN
- [BestLemoon/ApplePriceTracker](https://github.com/BestLemoon/ApplePriceTracker) — App Store IAP 解析思路启发

## 💡 反馈与贡献

发现 bug 或想加新功能？欢迎 [开 issue](../../issues) 或 PR。

