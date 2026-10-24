# frontend

main提交版默认PPO选择801后果输入模型；其他微调模型和原PPO保留对照。页面依旧分为Configuration、Simulation、Evaluation、Training，API、状态和图表组件独立，全部业务数据来自实际服务。

使用者请阅读[零基础手册](用户使用手册.md)。WebSocket结合REST校准，按run隔离，序列去旧，终态从归档补查。SVG只在服务端给定的相邻运动段内插值，暂停或断线停止，30层可滚动。图表实例卸载释放，趋势和日志有上限；等待/距离图保留独立底边距与图例空间。

生产构建由FastAPI同源托管；Vite开发代理/api与/ws至8000。提交运行根为artifacts/submission，不混入历史开发数据库。少量页面比较属于演示，不冒充独立研究结论。
