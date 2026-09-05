FROM python:3.12-alpine

WORKDIR /app
COPY AppPriceTracker.py AppPriceTracker.html ./
COPY appatlas/ ./appatlas/

# 仅内网/反代使用, 绑 0.0.0.0 供 Caddy 转发
# (后端原生支持 HOST/PORT 环境变量, 后台运行时不会弹浏览器)
ENV PORT=8765 HOST=0.0.0.0

EXPOSE 8765
# 轻量健康检查
HEALTHCHECK --interval=60s --timeout=5s CMD wget -qO- http://127.0.0.1:8765/health || exit 1

CMD ["python", "-u", "AppPriceTracker.py"]
