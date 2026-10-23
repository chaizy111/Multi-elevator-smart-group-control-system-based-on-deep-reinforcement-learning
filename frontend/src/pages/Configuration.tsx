import { useState, useEffect } from "react";
import type { Config, Model, Pattern, Trace, ControllerName } from "../types";
import { post } from "../api/client";
import { format } from "../components/Metric";

const patterns: [Pattern, string, string][] = [
  ["normal", "普通办公", "均匀楼层互访"],
  ["morning", "早高峰", "80% 大堂上行"],
  ["evening", "晚高峰", "80% 返回大堂"],
  ["interfloor", "楼层互访", "非大堂之间出行"],
  ["burst", "会议散场", "集中突发叠加背景流"],
];
export function Configuration({
  config,
  setConfig,
  models,
  traces,
  onStart,
}: {
  config: Config;
  setConfig: (config: Config) => void;
  models: Model[];
  traces: Trace[];
  onStart: (trace: string | null, speed: number) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [traceId, setTraceId] = useState(""),
    [speed, setSpeed] = useState(5);
  const [advanced, setAdvanced] = useState("");
  const [jsonDirty, setJsonDirty] = useState(false);
  useEffect(() => {
    if (!jsonDirty) setAdvanced(JSON.stringify(config, null, 2));
  }, [config, jsonDirty]);
  function update(
    section: "building" | "simulation" | "physics" | "traffic",
    key: string,
    value: number,
  ) {
    const next = structuredClone(config);
    Object.assign(next[section], { [key]: value });
    if (section === "building") next.building.initial_floors = null;
    setConfig(next);
    setTraceId("");
  }
  function field(
    label: string,
    section: "building" | "simulation" | "physics" | "traffic",
    key: string,
    min: number,
    max?: number,
    step = 1,
  ) {
    return (
      <label>
        {label}
        <input
          type="number"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          required
          value={Number(
            (config[section] as unknown as Record<string, unknown>)[key],
          )}
          onChange={(e) => update(section, key, e.target.valueAsNumber)}
        />
      </label>
    );
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/config/validate", config);
      await onStart(traceId || null, speed);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function save() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(config, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "elevator-config.json";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="config-layout">
      <form onSubmit={submit} className="panel config-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">SCENARIO SETUP</span>
            <h2>创建仿真场景</h2>
          </div>
          <span className="pill">可复现 · 本地运行</span>
        </div>
        <fieldset>
          <legend>
            <b>01</b> 建筑与物理
          </legend>
          <div className="fields three">
            {field("楼层数量", "building", "floor_count", 5, 30)}
            {field("电梯数量", "building", "elevator_count", 2, 8)}
            {field("每梯容量（人）", "building", "capacity", 6, 20)}
          </div>
          <div className="fields three">
            {field(
              "每层运行时间（秒）",
              "physics",
              "seconds_per_floor",
              0.1,
              60,
              0.1,
            )}
            {field(
              "到达窗口（秒）",
              "simulation",
              "arrival_horizon_s",
              1,
              86400,
            )}
            <label>
              随机种子
              <input
                aria-label="随机种子"
                type="number"
                min={0}
                max={4294967295}
                value={config.seed}
                onChange={(e) => {
                  setConfig({ ...config, seed: e.target.valueAsNumber });
                  setTraceId("");
                }}
                required
              />
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>
            <b>02</b> 客流模式
          </legend>
          <div className="presets">
            {patterns.map(([key, title, description]) => (
              <button
                key={key}
                type="button"
                aria-pressed={config.traffic.pattern === key}
                className={
                  config.traffic.pattern === key ? "preset selected" : "preset"
                }
                onClick={() => {
                  setConfig({
                    ...config,
                    traffic: {
                      ...config.traffic,
                      pattern: key,
                      segments: [],
                      bursts: [],
                    },
                  });
                  setTraceId("");
                }}
              >
                <strong>{title}</strong>
                <span>{description}</span>
              </button>
            ))}
          </div>
          <div className="fields two">
            {field(
              "到达率（人/分钟）",
              "traffic",
              "arrival_rate_per_min",
              0,
              600,
              0.5,
            )}
            <label>
              乘客输入流
              <select
                aria-label="乘客输入流"
                value={traceId}
                onChange={(e) => {
                  const trace = traces.find(
                    (t) => t.trace_id === e.target.value,
                  );
                  setTraceId(e.target.value);
                  if (trace)
                    setConfig({
                      ...trace.config,
                      controller: config.controller,
                    });
                }}
              >
                <option value="">按当前配置生成新 Trace</option>
                {traces.map((t) => (
                  <option key={t.trace_id} value={t.trace_id}>
                    {t.trace_id.slice(-8)} · {t.count}人 · seed {t.seed}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>
            <b>03</b> 控制策略
          </legend>
          <div className="fields two">
            <label>
              调度算法
              <select
                aria-label="调度算法"
                value={config.controller.name}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    controller: {
                      name: e.target.value as ControllerName,
                      model_id:
                        e.target.value === "ppo"
                          ? (models[0]?.model_id ?? null)
                          : null,
                    },
                  })
                }
              >
                <option value="round_robin">Round Robin · 轮转</option>
                <option value="eta">ETA · 最早接人</option>
                <option value="eta_zone">ETA-Zone · 热度重定位</option>
                <option value="ppo">PPO · 双任务强化学习</option>
              </select>
            </label>
            <label>
              运行速度
              <select
                aria-label="运行速度"
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                <option value={1}>1× 实时</option>
                <option value={5}>5×</option>
                <option value={20}>20×</option>
                <option value={0}>最快</option>
              </select>
            </label>
          </div>
          {config.controller.name === "ppo" && (
            <label>
              已训练模型
              <select
                aria-label="已训练模型"
                value={config.controller.model_id ?? ""}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    controller: {
                      ...config.controller,
                      model_id: e.target.value,
                    },
                  })
                }
                required
              >
                <option value="">选择已注册模型</option>
                {models
                  .filter(
                    (m) =>
                      m.support.max_floors >= config.building.floor_count &&
                      m.support.max_elevators >= config.building.elevator_count,
                  )
                  .map((m) => (
                    <option key={m.model_id} value={m.model_id}>
                      {m.model_id} · {format(m.training_steps, 0)}决策 · seed{" "}
                      {m.seed}
                    </option>
                  ))}
              </select>
              {!models.length && (
                <span className="notice">
                  暂无模型。请先按 README 运行 train 和 model
                  register，训练进度可在“训练与模型”页查看。
                </span>
              )}
            </label>
          )}
        </fieldset>
        <details>
          <summary>高级设置 · 门时间、排空、突发与奖励</summary>
          <div className="fields three">
            {field("开门时间（秒）", "physics", "door_open_s", 0.1, 60, 0.1)}
            {field("关门时间（秒）", "physics", "door_close_s", 0.1, 60, 0.1)}
            {field(
              "登梯耗时（秒/人）",
              "physics",
              "board_s_per_person",
              0.1,
              60,
              0.1,
            )}
            {field(
              "离梯耗时（秒/人）",
              "physics",
              "alight_s_per_person",
              0.1,
              60,
              0.1,
            )}
            {field("排空上限（秒）", "simulation", "max_drain_s", 0, 86400)}
            {field(
              "采样间隔（秒）",
              "simulation",
              "snapshot_interval_s",
              0.1,
              60,
              0.1,
            )}
          </div>
          <label>
            完整配置 JSON
            <textarea
              aria-label="完整配置 JSON"
              value={advanced}
              onChange={(e) => {
                setAdvanced(e.target.value);
                setJsonDirty(true);
              }}
              rows={10}
            />
          </label>
          {jsonDirty && (
            <p className="notice">JSON尚未应用；启动使用当前表单配置。</p>
          )}
          <button
            type="button"
            onClick={async () => {
              try {
                const result = await post<{ normalized_config: Config }>(
                  "/config/validate",
                  JSON.parse(advanced),
                );
                setJsonDirty(false);
                setConfig(result.normalized_config);
                setError("");
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            校验并应用 JSON
          </button>
        </details>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        <div className="form-actions">
          <button
            type="submit"
            className="primary"
            disabled={
              busy ||
              (config.controller.name === "ppo" && !config.controller.model_id)
            }
          >
            {busy ? "正在创建…" : "启动仿真 →"}
          </button>
          <button type="button" onClick={save}>
            导出配置
          </button>
          <label className="file-button">
            加载配置
            <input
              aria-label="加载配置文件"
              type="file"
              accept=".json"
              onChange={async (e) => {
                try {
                  const file = e.target.files?.[0];
                  if (file) {
                    const result = await post<{ normalized_config: Config }>(
                      "/config/validate",
                      JSON.parse(await file.text()),
                    );
                    setJsonDirty(false);
                    setConfig(result.normalized_config);
                    setAdvanced("");
                    setError("");
                  }
                } catch (e) {
                  setError(String(e));
                }
              }}
            />
          </label>
        </div>
      </form>
      <aside className="scenario-aside">
        <div className="dark-card">
          <span className="eyebrow">BUILDING CONTEXT</span>
          <h2>
            {config.building.floor_count}
            <small> FLOORS</small>
            <br />
            {config.building.elevator_count}
            <small> ELEVATORS</small>
          </h2>
          <div className="building-preview">
            {Array.from(
              { length: Math.min(config.building.floor_count, 12) },
              (_, i) => (
                <div key={i}>
                  {Array.from(
                    { length: config.building.elevator_count },
                    (_, j) => (
                      <i
                        key={j}
                        className={(i * 3 + j) % 7 === 0 ? "lit" : ""}
                      />
                    ),
                  )}
                </div>
              ),
            )}
          </div>
          <p>
            总运载容量{" "}
            <strong>
              {config.building.capacity * config.building.elevator_count} 人
            </strong>
          </p>
        </div>
        <div className="panel compact">
          <h3>可复现的每一次调度</h3>
          <p>固定种子生成独立乘客流。各策略共享相同的物理规则与路线规划。</p>
          <dl>
            <dt>背景流预计人数</dt>
            <dd>
              ≈{" "}
              {format(
                (config.traffic.arrival_rate_per_min *
                  config.simulation.arrival_horizon_s) /
                  60,
                0,
              )}
            </dd>
            <dt>随机种子</dt>
            <dd className="mono">{config.seed}</dd>
            <dt>重定位冷却</dt>
            <dd>{config.reposition.cooldown_s} 秒</dd>
          </dl>
          <p className="muted">
            预计人数不含额外 Burst，实际以归档 Trace
            为准。距离与能耗均包含排空阶段，能耗为代理量。
          </p>
        </div>
      </aside>
    </div>
  );
}
