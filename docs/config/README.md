# config

所有入口通过 Pydantic 严格 schema 加载；拒绝未知字段、非法数字、交通分段空洞和越界突发。配置单位为秒和楼层，进入内核后一次量化为整数微秒。哈希使用排序且无空白的规范 JSON，包含展开后的默认值。

内核配置允许小型人工 fixture；业务规模边界由公开入口额外校验。

提交版训练配置为configs/training/submission.yaml，保留实际801微调参数；同流演示配置为configs/evaluation/submission.yaml，使用随包模型和9001/9002两条已知输入。原standard等矩阵仍被研究输入生成和契约测试使用，保留定义；其中旧模型ID需在dev完整研究环境运行，不能当作main随包模型列表。
