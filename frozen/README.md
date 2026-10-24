# 开发状态冻结

当前开发代码与完整注册模型冻结在dev分支，源提交为4adf1be。models保留首版8模型、本轮3模型与第二轮401模型，权重SHA见manifest.json。

约10GB原始训练/仿真归档继续保存在项目内被Git忽略的artifacts目录，不因切换分支而删除；目录清单及关键权重/配置/检查点SHA在artifact-inventory.json.gz。Git分支本身不包含这10GB归档，迁移机器时需另复制artifacts。

main面向教师提交，dev保留研究过程，不在dev继续优化。
