# 冻结与提交设计

开发冻结点dev/bc0fef6基于4adf1be，保留代码和12份注册模型。frozen/manifest.json固定权重SHA，artifact-inventory.json.gz列出274571份原始档案及关键检查点SHA。本机约10.06GB原始artifacts不删除，也不声称它们已进入Git。main随代码携带约14.7MB的必要模型、初始化检查点和曲线。

默认模型ppo-consequences-s801-n200000来自已有开发可行模型中等待最低者，训练预算200000、获选143360步；不读取确认/最终数据选模。三新模型与原PPO由assets/release/manifest.json固定。安装器先验证全部源文件和存在的目标文件，再复制及建索引，有差异即拒绝，不静默覆盖。

默认运行目录artifacts/submission让Web、CLI推理、评价、注册及归档共享一个命名空间，与旧开发数据库隔离。ELEVATOR_ARTIFACTS可改到项目内其他目录，项目外目录被拒绝。

PPO数学、仿真、奖励和网络不改变。CLI的migrate_candidate_inputs只暴露既有显式补零迁移能力，默认不开启，错误版本仍拒绝。新回归覆盖干净目录、幂等、拒绝覆盖、模型与曲线服务；[质量记录](../../reports/quality/checks.json)。[冻结清单](development-freeze.json)。
