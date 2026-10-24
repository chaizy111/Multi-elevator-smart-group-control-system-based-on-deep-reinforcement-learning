# 候选后果输入PPO研究

> 本文记录整理前的研究过程，默认模型描述属于当时状态。main已按用户认可冻结并采用801检查点，当前入口见[提交建模](前端PPO建模与流程.md)。

按用户要求，已先删除最小改动方案对应的全部训练/模型/实验/报告及专用代码；保留历史记录与设计文本。清理清单见[cleanup.json](../../reports/candidate-ppo/cleanup.json)。当前默认模型仍是原始ppo-curriculum。

本轮只给派梯神经网络增加[六项公开候选后果](../env/candidates.md)。原224维派梯评分输入扩为230维，首层仍为128单元，新增768参数；共享Attention、critic、重定位头、原四目标奖励和时间GAE/PPO保持原定义。输出始终为网络logits+合法动作mask，不加固定候选代价、规则残差、教师动作、行为克隆或兜底。

通过显式迁移复制原ppo-curriculum学习权重，在派梯首层补6列零权重；因此新增特征起初没有影响，随后由PPO更新学习。初始验证检查点与训练中检查点共同参与选模，避免将训练退化后候选冒称比初始化更好；选中0步或候选列仍为零时，不把它算作新输入学习成功。注册与加载严格验证观测/架构，旧模型仍沿旧路径运行。

使用801/802/803三个独立微调随机种子，均从同一个原始已训练PPO开始；它们不是三个独立预训练模型。无候选输入控制组与候选输入组采用同预算、同验证规则，先各6万决策。只有平均等待相对匹配控制组改善至少3%，或至少2seed末次验证比首次训练后验证改善5%，才考虑独立从原初始化重开20万预算。

开发45场景×3条输入，确认45×10，最终45×30，使用6100万/6200万/6300万独立seed区间；上一轮已用范围不重复作为新测试。输入冻结前发现的空cohort完整记入协议，按仅依赖输入的预设50–99备用槽补足非空评价输入，不读取任何策略结果；空输入不填零等待参与排名。

选模先完整服务，再比较P95/距离约束违反，最后比较平均等待和P95；无可行模型的best仅作诊断。目标仍包括等待优于三经典基线、接近固定规则110%、尾部与距离≤各基线105%，不能因新增输入有改善就放宽标准。固定规则仅存在于离线评价路径。

实现入口：`research/candidate_ppo.py`，结果写入artifacts/candidate-ppo，报告写入reports/candidate-ppo。现有完整训练目录会校验配置后复用，现有原始评价按配置/Trace/模型哈希复用；中断目录要求检查last检查点并显式resume，不静默重开或覆盖。当前冻结协议v1/v2均保留，v2还封存45条长窗口、150条泛化、6条压力输入，生成方法与201条冻结配置及Trace哈希逐项复现一致。

在项目根、已配置环境中依次运行：

```bash
source scripts/project_env.sh
.venv/bin/python -m elevator_control.research.candidate_ppo prepare
.venv/bin/python -m elevator_control.research.candidate_ppo references
.venv/bin/python -m elevator_control.research.candidate_ppo run
.venv/bin/python -m elevator_control.research.verify_candidate
.venv/bin/python scripts/run_quality.py
.venv/bin/python -m elevator_control.research.report_candidate
```

报告生成器要求完整质量检查通过；所引用的quality快照由最终交付流程从reports/quality复制，不把检查未完成时的进度报告当作验收证据。复用已打开的数据仅是历史复算，后续新优化需另冻结输入，不能把当前开发集再次称为盲测。

本轮完成两组×三seed×6万/20万，共12次训练、156万微调决策。20万预算获选检查点的开发均值为等待13.7975秒、P95 36.4108秒、距离153.5728层；同预算控制组为25.5432秒/79.4068秒/192.7852层，原始PPO为24.4030秒/75.0211秒/199.6741层。候选输入组等待比原始PPO减少43.46%，相对三经典ETA/ETA-Zone/轮询分别减少61.54%/46.85%/46.18%。

**完整效果目标尚未通过。** 固定规则等待11.3546秒，本轮仍高21.51%，未达到≤110%的门槛；803距离160.5259层超过最严格154.4744层上限，不能用三seed均值掩盖。开发门槛失败，确认和最终数据未打开，原默认模型未替换。六输入置零后等待升到22.7052/24.0517/23.1838秒，支持网络实际使用新信息，但这是分布外诊断，并非独立泛化证据。

研究模型独立注册在`artifacts/candidate-ppo/models/ppo-consequences-s{801,802,803}-n200000/`，训练配置、完整轨迹与获选步数分别保存。Python调用时应显式使用`RLController(model_id, root="artifacts/candidate-ppo/models")`；默认CLI/页面仍读取原注册表。完整数值、逐seed限制与审计见[研究报告](../../reports/candidate-ppo/report.md)和[逐项验收](../../reports/candidate-ppo/acceptance.md)。
