# 自动验证与证据

`.github/workflows/ci.yml`在push、pull_request或手动触发后安装锁定的Python/Node依赖，训练T0和有界T1–T3课程，再运行`uv run python scripts/run_quality.py`。训练用于提供真实checkpoint和训练曲线，E2E不使用伪造模型。正式9770格实验作为独立验收运行，不放进每次提交的CI。

`run_quality.py`依次执行Python完整单元/属性/集成测试、Ruff lint与format、Pyright、Prettier、TypeScript、Vitest、Vite构建、四策略真实同流链路、Playwright。任一非零退出立即停止，真实命令、耗时、退出码和日志写到`reports/quality/`；CI无论成功与否都上传这些证据。

Playwright按ELEVATOR_PYTHON、仓库.venv、PATH的python顺序选择解释器；真实FastAPI服务固定使用8765并由测试管理生命周期。仓库内浏览器缓存与临时目录由`project_env.sh`设置。Linux CI的系统浏览器依赖安装只发生在临时CI runner。

当前交付记录为本机CPU的完整运行结果。工作流已添加且本地解析验证，尚未推送触发远端GitHub runner，不将其标为远端执行通过。
