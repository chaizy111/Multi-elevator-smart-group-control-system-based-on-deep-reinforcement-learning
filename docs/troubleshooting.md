# 故障排查

- **Python版本/依赖错误**：先`conda activate elevator`，`python --version`应3.11；或运行仓库内uv隔离环境。默认系统python可能不同，勿向全局环境安装项目依赖。
- **无注册模型**：先执行`.venv/bin/python -m elevator_control.submission`校验安装随包模型；新训练按docs/training.md注册。不存在模型时不创建随机策略或静默回退ETA。
- **版本不兼容**：新物理/奖励/输入版本会拒绝旧模型。使用随包当前模型或按当前语义重训的模型，不手改metadata伪装兼容。
- **仿真完成但乘客未完成**：查看termination_reason、unpicked/unfinished和等待下界。drain_timeout不等于请求丢失；不能仅对已完成样本排名。提高drain应在实验固定前统一设置。
- **PPO表现差/argmax集中派单**：先看所有训练seed、双头样本/梯度、固定验证和原始决策，检查物理/积分，再讨论预算。不能通过削弱ETA或挑选Trace制造提升。
- **网页断线**：确认8000服务及health，Vite开发端应代理/api与/ws。关闭浏览器不停止作业；自动重连并用REST取完整快照。
- **作业失败**：看artifacts/submission/runs/{id}/failure.json及manifest；API不会向普通错误响应暴露完整traceback。重启遗留worker标记FAILED并保留文件；活着的CLI协调器不被误报中断。
- **Playwright找不到浏览器**：`PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/playwright" node frontend/node_modules/playwright/cli.js install chromium`，浏览器缓存仍在项目内。
- **测试依赖警告**：锁定Starlette对httpx发出弃用警告，目前不影响真实集成测试；不在未验证的版本间随意升级。
- **端口占用**：serve可显式`--port`，默认8000只绑定本地回环。不要停止无关进程。

诊断顺序：物理/守恒 → 决策协议 → 奖励/指标 → PPO数学 → 训练规模与效果。每次修改记录history.md、对应模块文档和验收证据。
