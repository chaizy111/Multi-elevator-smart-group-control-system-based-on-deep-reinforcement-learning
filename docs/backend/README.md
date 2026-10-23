# backend

FastAPI lifespan只创建一个协调器，计算使用multiprocessing spawn。SQLite WAL仅协调器写索引；每个worker写独立目录，产物成功落盘后才报告完成。最多两个worker、队列32；超限429。重启将遗留RUNNING/PAUSED/QUEUED记为FAILED并保留产物，不伪造恢复。

运行CREATED后start入队，pause/resume在一致事件边界确认，速度0/1/5/20只改变墙钟节奏。Reset保留旧run并返回新的CREATED run_id。command_id及payload哈希持久化，重复相同命令返回原结果，复用ID不同payload返回409。UI必须以确认后的status显示。

API前缀/api/v1，交互式契约见/docs。WebSocket /ws/v1/simulations/{id} 每100ms至多一个完整状态/心跳，重连先取得最新全量；终态始终可经REST补查。下载只按已知job与文件名解析，禁止路径穿越。训练只由CLI启动，Web读取真实目录。
