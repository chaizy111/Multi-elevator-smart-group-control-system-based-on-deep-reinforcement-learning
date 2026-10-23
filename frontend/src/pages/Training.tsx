import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { Chart } from "../components/Chart";
import { format, numeric } from "../components/Metric";
import type { Model, Row } from "../types";

interface TrainingRun {
  id: string;
  progress: {
    status: string;
    steps: number;
    budget: number;
    device: string;
    elapsed_s: number;
  };
  config: {
    stage: string;
    seed: number;
    attention: boolean;
    dispatch_only: boolean;
    domain_randomization: boolean;
  };
}
export function Training({ models }: { models: Model[] }) {
  const [runs, setRuns] = useState<TrainingRun[]>([]),
    [id, setId] = useState(""),
    [updates, setUpdates] = useState<Row[]>([]),
    [validation, setValidation] = useState<Row[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = () =>
      api<{ items: TrainingRun[] }>("/training-runs")
        .then((v) => {
          if (active) {
            setRuns(v.items);
            setId((old) => old || v.items.at(-1)?.id || "");
          }
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!id) return;
    let active = true;
    const load = () =>
      api<{ series: { updates: Row[]; validation: Row[] } }>(
        `/training-runs/${id}/curves`,
      )
        .then((v) => {
          if (active) {
            setUpdates(v.series.updates);
            setValidation(v.series.validation);
          }
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id]);
  const selected = runs.find((r) => r.id === id);
  const option = useMemo(
    () => ({
      color: ["#177e73", "#b98330"],
      tooltip: { trigger: "axis" as const },
      legend: { bottom: 0 },
      grid: { left: 55, right: 55, top: 25, bottom: 45 },
      xAxis: { type: "value" as const, name: "决策数" },
      yAxis: [
        { type: "value" as const, name: "区间平均Reward" },
        { type: "value" as const, name: "验证成本" },
      ],
      series: [
        {
          name: "训练 Reward",
          type: "line" as const,
          showSymbol: false,
          data: updates.map((r) => [numeric(r.step), numeric(r.reward_mean)]),
        },
        {
          name: "固定验证成本",
          type: "line" as const,
          yAxisIndex: 1,
          data: validation.map((r) => [numeric(r.step), numeric(r.cost)]),
        },
      ],
    }),
    [updates, validation],
  );
  const entropy = useMemo(
    () => ({
      color: ["#177e73", "#586aa6"],
      tooltip: { trigger: "axis" as const },
      legend: { bottom: 0 },
      grid: { left: 45, right: 25, top: 25, bottom: 45 },
      xAxis: { type: "value" as const },
      yAxis: { type: "value" as const, name: "Active head entropy" },
      series: ["dispatch_entropy", "reposition_entropy"].map((key) => ({
        name: key,
        type: "line" as const,
        showSymbol: false,
        data: updates.map((r) => [numeric(r.step), numeric(r[key])]),
      })),
    }),
    [updates],
  );
  const validationOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" as const },
      legend: { bottom: 0 },
      grid: { left: 50, right: 30, top: 30, bottom: 45 },
      xAxis: { type: "value" as const, name: "决策数" },
      yAxis: { type: "value" as const, name: "固定验证等待 / 秒" },
      series: [
        {
          name: "MeanWait",
          type: "line" as const,
          data: validation.map((r) => [numeric(r.step), numeric(r.mean_wait)]),
        },
        {
          name: "P95Wait",
          type: "line" as const,
          data: validation.map((r) => [numeric(r.step), numeric(r.p95)]),
        },
      ],
    }),
    [validation],
  );
  const costsOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" as const },
      legend: { bottom: 0 },
      grid: { left: 50, right: 30, top: 30, bottom: 45 },
      xAxis: { type: "value" as const },
      yAxis: { type: "value" as const, name: "每update原始积分" },
      series: ["wait", "ride", "energy", "fairness"].map((k) => ({
        name: k,
        type: "line" as const,
        showSymbol: false,
        data: updates.map((r) => [numeric(r.step), numeric(r[k])]),
      })),
    }),
    [updates],
  );
  const latest = updates.at(-1);
  return (
    <>
      <section className="panel compact">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TRAINING OBSERVATORY</span>
            <h2>真实训练与模型注册表</h2>
          </div>
          <label>
            训练记录
            <select
              aria-label="训练记录"
              value={id}
              onChange={(e) => setId(e.target.value)}
            >
              <option value="">选择训练</option>
              {runs.map((r) => (
                <option key={r.id}>{r.id}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          训练和续训通过 CLI
          独立启动，此页只读取真实日志。模型效果以独立测试为准。
        </p>
        {selected ? (
          <div className="training-stats">
            <div>
              <small>阶段 / 状态</small>
              <strong>
                {selected.config.stage} · {selected.progress.status}
              </strong>
            </div>
            <div>
              <small>实际决策 / 预算</small>
              <strong>
                {format(selected.progress.steps, 0)} /{" "}
                {format(selected.progress.budget, 0)}
              </strong>
            </div>
            <div>
              <small>设备 / Seed</small>
              <strong>
                {selected.progress.device} / {selected.config.seed}
              </strong>
            </div>
            <div>
              <small>最后 KL / 截断率</small>
              <strong>
                {format(latest?.kl, 4)} /{" "}
                {format(Number(latest?.truncation_rate ?? 0) * 100)}%
              </strong>
            </div>
          </div>
        ) : (
          <p>尚无训练日志。先运行下面的 smoke 命令。</p>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
      </section>
      {updates.length > 0 && (
        <>
          <div className="two-panels">
            <section className="panel">
              <div className="panel-heading">
                <h3>Reward 与固定验证</h3>
              </div>
              <Chart option={option} label="真实训练Reward和固定验证成本曲线" />
            </section>
            <section className="panel">
              <div className="panel-heading">
                <h3>双动作头探索</h3>
              </div>
              <Chart option={entropy} label="Dispatch和Reposition两头的熵" />
            </section>
          </div>
          <section className="panel compact">
            <h3>最后一次更新诊断</h3>
            <div className="training-stats">
              {[
                "policy_loss",
                "value_loss",
                "dispatch_gradient",
                "reposition_gradient",
                "dispatch_samples",
                "reposition_samples",
                "wait",
                "ride",
                "energy",
                "fairness",
              ].map((key) => (
                <div key={key}>
                  <small>{key}</small>
                  <strong>{format(latest?.[key], 4)}</strong>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
      {updates.length > 0 && (
        <div className="two-panels">
          <section className="panel">
            <div className="panel-heading">
              <h3>验证 MeanWait / P95</h3>
            </div>
            <Chart
              option={validationOption}
              label="固定验证集MeanWait和P95等待曲线"
            />
            <p className="muted inset">
              历史记录未记录的字段保持缺失，不补造曲线。
            </p>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h3>原始奖励成本分项</h3>
            </div>
            <Chart
              option={costsOption}
              label="等待乘梯能耗公平性原始成本积分"
            />
          </section>
        </div>
      )}
      <section className="panel compact">
        <h3>已注册模型</h3>
        {models.length ? (
          <div className="model-grid">
            {models.map((m) => (
              <article key={m.model_id} className="model-card">
                <span className="pill">
                  {m.attention
                    ? "Shared Encoder + Attention"
                    : "Shared Encoder"}
                </span>
                <h3>{m.model_id}</h3>
                <p>
                  {format(m.training_steps, 0)} 次真实决策 · seed {m.seed}
                </p>
                <dl>
                  <dt>输入上限</dt>
                  <dd>
                    {m.support.max_floors}F / {m.support.max_elevators}E
                  </dd>
                  <dt>选模验证</dt>
                  <dd>
                    {m.validation?.complete ? "完整服务" : "查看原始记录"}
                  </dd>
                  <dt>SHA256</dt>
                  <dd className="mono" title={m.sha256}>
                    {m.sha256.slice(0, 16)}…
                  </dd>
                </dl>
              </article>
            ))}
          </div>
        ) : (
          <p className="notice">暂无注册模型，不提供随机权重作为已训练PPO。</p>
        )}
      </section>
      <section className="panel compact">
        <h3>最短训练与注册命令</h3>
        <pre>{`conda activate elevator\nsource scripts/project_env.sh\npython -m elevator_control.cli train --config configs/training/smoke.yaml --output artifacts/training/smoke\npython -m elevator_control.cli model register --checkpoint artifacts/training/smoke/checkpoints/best.pt --model-id ppo-smoke`}</pre>
        <p className="muted">
          T0只验证工程流程；完整课程和正式多seed结果见项目
          reports/。best根据固定验证集选择，last保留最终更新。
        </p>
      </section>
    </>
  );
}
