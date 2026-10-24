# 自动验证

CI安装锁定依赖，校验和安装随仓库提供的真实模型及训练曲线，再执行scripts/run_quality.py；不在CI重训另一个默认模型。远程Linux runner尚未实际执行。

本机完整检查含Python90、Vitest2、Playwright5及Ruff、格式、Pyright、TypeScript、Vite和真实链路，共10/10通过。真实退出码保存在reports/quality。Playwright使用项目内解释器、浏览器缓存和8765测试服务。

运行数据在artifacts/submission，模型及曲线来自assets/release，原开发归档保持隔离。CI的系统浏览器依赖仅在临时远程runner安装。
