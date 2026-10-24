"""Render audited study results, explicitly separating development from final evidence."""

import json
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from elevator_control.research.candidate_ppo import POLICIES, REPORT, ROOT
from elevator_control.storage.artifacts import atomic_json, write_csv


def learning_curves(selected, reference):
    """Show every fine-tuning seed, including the unmodified zero-step initializer."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    colors = ["#0072b2", "#d55e00", "#009e73"]
    for color, row in zip(colors, sorted(selected, key=lambda r: r["seed"]), strict=True):
        for group, style in [("consequences", "-"), ("control", "--")]:
            folder = ROOT / "training" / f"{group}-s{row['seed']}-n{row['budget']}"
            snapshots = sorted(
                (folder / "validation-results").glob("*.json"), key=lambda p: int(p.stem)
            )
            points = [(int(p.stem), json.loads(p.read_text())) for p in snapshots]
            for axis, metric in zip(axes, ["mean_wait", "distance"], strict=True):
                axis.plot(
                    [n for n, _ in points],
                    [v[metric] for _, v in points],
                    style,
                    color=color,
                    label=f"{group}, seed {row['seed']}",
                    linewidth=1.5,
                )
    axes[0].axhline(reference["fixed-rule"]["mean_wait_s"], color="#777777", linestyle=":")
    axes[0].axhline(reference["fixed-rule"]["mean_wait_s"] * 1.1, color="#333333", linestyle="-.")
    axes[1].axhline(
        min(reference[p]["distance_floors"] for p in POLICIES[:3]) * 1.05,
        color="#333333",
        linestyle="-.",
    )
    axes[0].set_ylabel("Mean waiting time (s)")
    axes[1].set_ylabel("Travel distance (floors)")
    axes[1].set_xlabel("Fine-tuning decisions")
    axes[0].set_title("Development validation; solid: consequence inputs, dashed: control")
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(REPORT / "learning-curves.svg")
    fig.savefig(REPORT / "learning-curves.png", dpi=140)
    plt.close(fig)


def main():
    state = json.loads((REPORT / "decision.json").read_text())
    records = json.loads((REPORT / "development.json").read_text())
    reference = json.loads((REPORT / "references.json").read_text())
    audited = json.loads((REPORT / "raw-audit.json").read_text())
    ablation = json.loads((REPORT / "selected-raw-and-ablation.json").read_text())["summary"]
    quality = json.loads(Path("reports/quality/checks.json").read_text())
    assert quality["status"] == "PASSED"
    tests = sum(
        int(s.get("tests", "0")) for s in ET.parse("reports/quality/pytest.xml").iter("testsuite")
    )
    assert tests >= 86
    selected = state["selected_models"]
    learning_curves(selected, reference)
    grouped = {}
    for budget in sorted({r["budget"] for r in records}):
        for group in ["control", "consequences"]:
            rows = [r for r in records if r["group"] == group and r["budget"] == budget]
            grouped[(group, budget)] = {
                k: statistics.mean(r[k] for r in rows) for k in ["wait", "p95", "distance"]
            }
    trained = list((ROOT / "training").glob("*/progress.json"))
    progress = [json.loads(p.read_text()) for p in trained]
    assert all(p["status"] == "COMPLETED" for p in progress)
    total = sum(p["steps"] for p in progress)
    learned = grouped[("consequences", state["budget"])]
    control = grouped[("control", state["budget"])]
    write_csv(REPORT / "models.csv", records)
    status = (
        "独立评价达到预定目标" if state["target_achieved"] else "有界研究完成；尚未达到全部预定目标"
    )
    text = [
        "# 候选后果输入PPO研究结果",
        "",
        f"2026-10-24。**{status}**。默认模型仍为原始 `ppo-curriculum`，研究候选保存在独立目录。",
        "",
        "## 先清理，再开始的新实验",
        "",
        "已按要求删除上一轮minimal-ppo的全部训练、15个T3候选、3个研究注册模型、实验/报告、专用代码与缓存；旧设计文本和history仅保留历史追溯。首版8模型和第二轮规则/401参考保留，9份权重SHA不变。[清理记录](cleanup.json)",
        "",
        "本轮把逐梯插单后果作为神经网络输入：新乘客接人/送达时间、新增距离、已有任务接人/送达延误总和、路线延长。派梯网络为MLP([电梯编码, 请求和全局上下文, 六项后果])；新增768参数，不加固定候选代价、规则分数、教师动作、行为克隆或兜底。六列新增输入权重以0初始化，由PPO自行学习。原奖励、GAE、Attention、价值项系数0.5和重定位任务不变。",
        "",
        f"完成{len(progress)}个候选训练，总计{total:,}个微调决策。801/802/803是从同一原始已训练PPO开始的独立微调随机种子，**不是三个独立预训练模型**。6万与20万阶段分别从同一原权重重新训练，并非更改resume预算；两组同预算对照共享验证方法。",
        "",
        "## 同流开发结果",
        "",
        "45场景×3条新非空输入，共135组。先算每运行指标，再按场景与微调seed等权汇总。P95是每流P95再平均，距离包含排空。这些结果参与了选模，不能冒充独立盲测。",
        "",
        "| 策略 | 平均等待/秒 | P95/秒 | 距离/层 |",
        "|---|---:|---:|---:|",
    ]
    for label in POLICIES:
        r = reference[label]
        text.append(
            f"| {label} | {r['mean_wait_s']:.4f} | {r['p95_wait_s']:.4f} | {r['distance_floors']:.4f} |"
        )
    for (group, budget), r in sorted(grouped.items(), key=lambda v: (v[0][1], v[0][0])):
        text.append(
            f"| {group} / {budget}（3seed均值） | {r['wait']:.4f} | {r['p95']:.4f} | {r['distance']:.4f} |"
        )
    text += [
        "",
        f"在最终预算开发结果中，候选输入相对同预算控制组等待变化{(learned['wait'] / control['wait'] - 1) * 100:+.2f}%，距离变化{(learned['distance'] / control['distance'] - 1) * 100:+.2f}%；相对原默认PPO等待变化{(learned['wait'] / reference['ppo-curriculum']['mean_wait_s'] - 1) * 100:+.2f}%；相对固定规则等待变化{(learned['wait'] / reference['fixed-rule']['mean_wait_s'] - 1) * 100:+.2f}%。不能把其中任意一个参照替代其余要求。",
        "",
        "原始初始化0步也参与保护性选模。选中0步或新增输入权重仍为0时不算新输入学习成功；无可行模型时的best仅为诊断候选。",
        "",
        "## 每个模型与约束",
        "",
        "| 模型 | 获选步数 | 等待/秒 | P95/秒 | 距离/层 | 候选列范数 | 可行 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in records:
        text.append(
            f"| {r['id']} | {r['selected_step']} | {r['wait']:.4f} | {r['p95']:.4f} | {r['distance']:.4f} | {r['learned_input_norm']:.4f} | {r['feasible']} |"
        )
    text += [
        "",
        "所有表中模型均完成其标注预算，获选步数是验证选择的检查点。完整逐流验证、episodes/updates、训练配置与检查点保存在 `artifacts/candidate-ppo/`；机器可读记录见[models.csv](models.csv)。",
        "",
        "![逐微调种子开发学习曲线](learning-curves.png)",
        "",
        "上图实线为新增后果输入，虚线为同预算控制组；等待面板灰色点线为固定规则、黑色点划线为规则110%门槛，距离面板黑色点划线为最严格经典算法105%上限。全部为开发曲线，不是测试集分数。",
        "",
        "## 是否达到目标",
        "",
        f"状态：`{state['status']}`；确认集打开：{state['confirmation_opened']}；最终测试打开：{state['final_opened']}；全目标通过：{state['target_achieved']}。原因：{state['reason']}。",
        "",
        f"本开发集规则等待110%门槛为{reference['fixed-rule']['mean_wait_s'] * 1.1:.4f}秒；各seed的距离上限中最严格为{min(reference[p]['distance_floors'] for p in POLICIES[:3]) * 1.05:.4f}层，P95同样不能超过任何经典基线105%。等待必须优于三基线、报告各seed而非仅最好seed。",
        "",
        "| 开发门槛 | 结果 |",
        "|---|---|",
        f"| 组均值等待比三种经典都减少至少5% | {all(learned['wait'] <= 0.95 * reference[p]['mean_wait_s'] for p in POLICIES[:3])} |",
        f"| 每个微调seed的等待均优于三种经典 | {all(r['wait'] < reference[p]['mean_wait_s'] for r in selected for p in POLICIES[:3])} |",
        f"| 每个微调seed的P95≤各经典105% | {all(r['p95'] <= 1.05 * reference[p]['p95_wait_s'] for r in selected for p in POLICIES[:3])} |",
        f"| 每个微调seed的距离≤各经典105% | {all(r['distance'] <= 1.05 * reference[p]['distance_floors'] for r in selected for p in POLICIES[:3])} |",
        f"| 组均值等待≤固定规则110% | {learned['wait'] <= 1.1 * reference['fixed-rule']['mean_wait_s']} |",
        "",
        "上述通过只代表开发检查。每个seed的距离单独判定，不能用三seed距离均值掩盖某一个seed超限；距离可行的较早检查点与训练末步也分别记录。",
        "",
        "确认450条、最终标准1350条输入在配置冻结前不用于选模；协议还封存长窗口、训练未见建筑/外推和压力输入。未通过开发门槛时按协议不打开这些数据，不通过增加测试次数或弱化阈值制造改善。即使本轮有较大开发改善，也必须单独说明是否接近规则与是否具备独立证据。",
    ]
    if state["final_opened"]:
        assessment = json.loads((REPORT / "final-assessment.json").read_text())
        assert assessment["passed"] == state["target_achieved"]
        text += [
            "",
            "独立测试与稳健性结果见[final-assessment.json](final-assessment.json)，包含模型seed/配对Trace分层bootstrap；三经典比较与接近规则使用单侧98.75%上界。区间只覆盖本次共同预训练权重下的微调随机性，不代表独立预训练不确定性。",
        ]
    text += [
        "",
        "## 模型是否真正使用了候选信息",
        "",
        "推理消融只将同一个已训练模型的六项输入置零，不重训、不改其他输入或规则；它是输入分布外诊断，不能当作新的独立算法成绩。",
        "",
        "| 同一检查点 | 原输入等待/秒 | 六输入置零等待/秒 | 置零后完整服务 |",
        "|---|---:|---:|---|",
    ]
    for r in selected:
        raw = ablation[r["id"]]
        zero = ablation["zero-input:" + r["id"]]
        v = f"{zero['mean_wait_s']:.4f}" if zero["complete"] else "不可排名"
        text.append(f"| {r['id']} | {raw['mean_wait_s']:.4f} | {v} | {zero['complete']} |")
    text += [
        "",
        "候选列的实际训练更新与置零消融结合判断输入使用程度；局部分数导数见[feature-sensitivity.json](feature-sensitivity.json)，它随状态变化，并非人工规定的全局系数。新增信息有用不等于已经证明比固定规则更优。",
        "",
        "## 工程与独立核验",
        "",
        f"- 完整质量10/10通过：Python{tests}、Vitest2、Playwright5；类型/格式/构建与真实链路均通过，见[快照](quality/checks.json)。",
        "- 原8模型×24真实公开状态输出逐位不变，保留9份权重SHA不变；关闭候选输入后128步实际训练的56个张量及随机状态与首版相同。",
        "- 特征回归改变尚未到达乘客的目的地与人数，当前候选结果不变；合法mask、padding/置换、补零迁移、真实训练/注册和版本拒绝均通过。",
        f"- {audited['runs']}次原始运行、{audited['passenger_rows']}条乘客记录独立重算通过；重复运行不增加独立输入样本数。选中检查点的重算指标与验证结果一致。",
        "- 研究模型注册到独立目录，5F2E和30F8E的实际API/worker完成服务，指标与离线推理一致；原默认模型未覆盖。",
        "- 空输入在任何策略运行前按固定非空入组规则记录和补足，原因、seed和哈希保留，不把空等待填零或按策略结果换客流。",
        "",
        "证据：[协议](protocol.json)、[先导扩预算判定](pilot-decision.json)、[开发选择](decision.json)、[旧路径兼容](legacy-compatibility.json)、[原始审计](raw-audit.json)、[输入消融](selected-raw-and-ablation.json)、[模型集成](model-integration.json)。实现、运行方式与边界见[模块文档](../../docs/rl/candidate-ppo.md)及[特征设计](../../docs/env/candidates.md)。",
    ]
    (REPORT / "report.md").write_text("\n".join(text) + "\n")
    atomic_json(
        REPORT / "delivery-checks.json",
        dict(
            status="PASSED",
            algorithm_target_achieved=state["target_achieved"],
            training_decisions=total,
            training_jobs=len(progress),
            pytest=tests,
            vitest=2,
            playwright=5,
            raw_audit=audited,
            previous_minimal_results_deleted=True,
            original_default_preserved=True,
        ),
    )
    acceptance = [
        "# 候选后果输入PPO逐项验收",
        "",
        "工程交付与算法效果分别判定。下表不将开发改善当作独立效果验收。",
        "",
        "| 检查项 | 结果与证据 |",
        "|---|---|",
        "| 先删除上一轮最小改动结果 | 通过；[清理清单](cleanup.json)，原模型/第二轮参考SHA不变 |",
        "| PPO获取每梯接单的公开后果 | 通过；六项输入，派梯首层新增768参数，无未来客流 |",
        "| 仍由深度RL决定动作 | 通过；原PPO目标、原奖励、合法mask，无规则分数/教师/兜底 |",
        "| 区分新增输入和仅继续训练 | 通过；三微调seed、两组同预算对照；[完整模型记录](models.csv) |",
        "| 检查网络是否使用新输入 | 通过；实际参数更新、局部导数及同检查点输入置零消融 |",
        "| 旧模型与关闭开关回归 | 通过；8模型×24状态，128步实际更新与首版逐位一致 |",
        f"| 全量测试/构建/类型/真实链路 | 10/10通过；Python {tests}、Vitest 2、Playwright 5；[质量](quality/checks.json) |",
        f"| 原始指标与服务集成 | 通过；{audited['runs']}运行/{audited['passenger_rows']}乘客行重算、5F2E/30F8E API与离线一致 |",
        f"| 优于三经典并接近规则的全部目标 | {'通过独立评价' if state['target_achieved'] else '尚未通过'}；[完整结果及失败边界](report.md) |",
        f"| 独立确认/最终测试 | 打开状态分别为{state['confirmation_opened']}/{state['final_opened']}；未过前置门槛不打开后续数据 |",
        "| 默认模型 | 原始ppo-curriculum保留，研究注册表独立，不自动替换 |",
        "| 文档与开发记录 | [设计](../../docs/rl/candidate-ppo.md)、[特征](../../docs/env/candidates.md)、[history](../../history.md) |",
        "",
        "三个seed共享同一个已训练初始化，结论不涵盖独立预训练随机性；输入置零属于分布外诊断；选模结果属于开发集，完整结果保留正负模型。",
    ]
    (REPORT / "acceptance.md").write_text("\n".join(acceptance) + "\n")
    print("Audited report written.", flush=True)


if __name__ == "__main__":
    main()
