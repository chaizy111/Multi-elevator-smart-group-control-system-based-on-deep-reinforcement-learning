# storage

每个 run 独立目录，先写 RUNNING manifest，所有产物成功后原子替换为终态。JSON 禁止 NaN；输入 trace 副本只保存输入字段，passengers.csv 包含全体 cohort 与未完成空字段。周期采样与关键事件快照均归档。失败不得登记 COMPLETED；未来作业协调器负责 SQLite 索引，计算进程只写自己目录。
