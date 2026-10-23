import { useEffect, useMemo, useState } from "react";
import { api, post } from "../api/client";
import { Chart } from "../components/Chart";
import { format, numeric } from "../components/Metric";
import type { Config, Job, Model, Row } from "../types";

interface Distribution {
  controller: string;
  count: number;
  box: number[];
  conditional: boolean;
}
interface RunDetail {
  manifest: { run_id: string; trace_hash: string };
  metrics: { at_horizon: Row; final: Row };
  artifacts: { name: string; url: string }[];
}

export function Evaluation({
  config,
  models,
  onRun,
}: {
  config: Config;
  models: Model[];
  onRun: (id: string) => void;
}) {
  const [modelId, setModelId] = useState(
    models.find((m) => m.model_id === "ppo-curriculum")?.model_id ??
      models[0]?.model_id ??
      "",
  );
  const [jobs, setJobs] = useState<Job[]>([]),
    [id, setId] = useState(""),
    [job, setJob] = useState<Job | null>(null),
    [rows, setRows] = useState<Row[]>([]),
    [intervals, setIntervals] = useState<Row[]>([]);
  const [runPage, setRunPage] = useState(0),
    [intervalPage, setIntervalPage] = useState(0);
  const [distributions, setDistributions] = useState<Distribution[]>([]);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [seeds, setSeeds] = useState("9001,9002");
  useEffect(() => {
    void api<{ items: Job[] }>("/experiments")
      .then((v) => setJobs(v.items))
      .catch((e) => setError(String(e)));
  }, [id, job?.status]);
  useEffect(() => {
    setRows([]);
    setIntervals([]);
    setJob(null);
    setDetail(null);
    setRunPage(0);
    setIntervalPage(0);
    if (!id) return;
    let active = true;
    let finished = false;
    async function load() {
      try {
        const value = await api<Job>(`/experiments/${id}`);
        if (!active) return;
        setJob(value);
        const result = await api<{
          tables: { runs: Row[]; confidence_intervals: Row[] };
          distributions: Distribution[];
        }>(`/experiments/${id}/results`);
        if (active) {
          setRows(result.tables.runs);
          setIntervals(result.tables.confidence_intervals);
          setDistributions(result.distributions ?? []);
          finished = ["COMPLETED", "STOPPED", "FAILED"].includes(value.status);
        }
      } catch (e) {
        if (active) setError(String(e));
      }
    }
    void load();
    const timer = setInterval(() => {
      if (!finished) void load();
    }, 1000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id]);
  const grouped = useMemo(() => {
    const result = new Map<string, Row[]>();
    for (const row of rows) {
      const key = String(row.controller);
      result.set(key, [...(result.get(key) ?? []), row]);
    }
    return [...result].map(([controller, values]) => {
      const complete = values.every(
        (r) => r.completion_ratio === 1 && Number(r.sample_count) > 0,
      );
      const average = (key: string) => {
        const nums = values
          .map((r) => r[key])
          .filter((v): v is number => typeof v === "number");
        return nums.length
          ? nums.reduce((a, b) => a + b, 0) / nums.length
          : null;
      };
      return {
        controller,
        complete,
        count: values.length,
        wait: complete ? average("mean_wait_s") : null,
        p95: complete ? average("p95_wait_s") : null,
        max: average("max_wait_s"),
        ride: average("mean_travel_s"),
        long: average("long_wait_ratio"),
        throughput: average("throughput_per_min"),
        ratio: average("completion_ratio"),
        distance: average("distance_floors"),
        energy: average("energy_proxy"),
      };
    });
  }, [rows]);
  const option = useMemo(
    () => ({
      color: ["#177e73", "#b98330", "#586aa6", "#91a9bd"],
      tooltip: { trigger: "item" as const },
      legend: { bottom: 0 },
      xAxis: { type: "value" as const, name: "运行距离 / 层" },
      yAxis: { type: "value" as const, name: "平均等待 / 秒" },
      grid: { left: 55, top: 35, right: 55, bottom: 50 },
      series: grouped.map((g) => ({
        name: g.controller,
        type: "scatter" as const,
        symbolSize: 10,
        data: rows
          .filter(
            (r) => r.controller === g.controller && r.eligible_for_ranking,
          )
          .filter(
            (_r, i, all) => i % Math.max(1, Math.ceil(all.length / 500)) === 0,
          )
          .map((r) => [numeric(r.distance_floors), numeric(r.mean_wait_s)]),
      })),
    }),
    [rows, grouped],
  );
  const boxOption = useMemo(
    () => ({
      tooltip: { trigger: "item" as const },
      grid: { left: 55, right: 30, top: 30, bottom: 65 },
      xAxis: {
        type: "category" as const,
        data: distributions.map((d) => d.controller),
        axisLabel: { rotate: 12 },
      },
      yAxis: { type: "value" as const, name: "已接到等待 / 秒" },
      series: [
        {
          type: "boxplot" as const,
          data: distributions.map((d) => d.box),
          itemStyle: { color: "#e8f5ef", borderColor: "#177e73" },
        },
      ],
    }),
    [distributions],
  );
  async function inspect(runId: string) {
    try {
      setDetail(await api<RunDetail>(`/experiments/${id}/runs/${runId}`));
    } catch (e) {
      setError(String(e));
    }
  }
  async function start() {
    setBusy(true);
    setError("");
    try {
      const seedList = seeds.split(",").map((s) => Number(s.trim()));
      if (
        seedList.some((s) => !Number.isInteger(s) || s < 9001 || s > 99999) ||
        !seedList.length
      )
        throw new Error("测试种子需为9001–99999的逗号分隔整数");
      const cfg = structuredClone(config);
      cfg.controller = { name: "eta", model_id: null };
      const suite = {
        controllers: ["round_robin", "eta", "eta_zone"],
        scenarios: [
          {
            name: `${cfg.building.floor_count}F${cfg.building.elevator_count}E-${cfg.traffic.pattern}`,
            seeds: seedList,
            config: cfg,
          },
        ],
      };
      const value = await post<{ experiment_id: string }>("/experiments", {
        suite,
        model_ids: modelId ? [modelId] : [],
      });
      setId(value.experiment_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel compact">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PAIRED EXPERIMENTS</span>
            <h2>相同客流，比较不同策略</h2>
          </div>
          <span className="pill">Trace 配对 · 95% 区间</span>
        </div>
        <p className="muted">
          使用配置页的建筑与交通设置，每个种子固化一个共享 Trace。默认同时运行
          RR、ETA、ETA-Zone 与所选 PPO。
        </p>
        <div className="fields three">
          <label>
            真实训练模型
            <select
              aria-label="实验模型"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            >
              <option value="">仅运行传统基线</option>
              {models.map((m) => (
                <option key={m.model_id}>{m.model_id}</option>
              ))}
            </select>
          </label>
          <label>
            独立测试种子
            <input
              aria-label="独立测试种子"
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
            />
          </label>
          <label>
            已有实验
            <select
              aria-label="已有实验"
              value={id}
              onChange={(e) => setId(e.target.value)}
            >
              <option value="">选择历史实验</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.id.slice(-8)} · {j.status}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          className="primary"
          disabled={busy}
          onClick={() => void start()}
        >
          {busy ? "正在创建…" : "运行同流对比"}
        </button>
        {job && (
          <span className="experiment-progress" data-testid="experiment-status">
            {job.status} · {job.progress?.completed ?? rows.length}/
            {job.progress?.total ?? "—"} 个运行
          </span>
        )}
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h3>最终 cohort · 跨 Trace 均值</h3>
          <small>未完成或空样本停止排名</small>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>策略</th>
                <th>Trace数</th>
                <th>MeanWait / s</th>
                <th>P95 / s</th>
                <th>Max / s</th>
                <th>乘梯 / s</th>
                <th>长等待</th>
                <th>吞吐 / 人/分</th>
                <th>完成率</th>
                <th>距离 / 层</th>
                <th>能耗代理</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => (
                <tr key={g.controller}>
                  <td>
                    <strong>{g.controller}</strong>
                    {!g.complete && <small>未完成 / 无样本</small>}
                  </td>
                  <td>{g.count}</td>
                  <td>{format(g.wait)}</td>
                  <td>{format(g.p95)}</td>
                  <td>{format(g.max)}</td>
                  <td>{format(g.ride)}</td>
                  <td>
                    {g.long === null ? "暂无样本" : `${format(g.long * 100)}%`}
                  </td>
                  <td>{format(g.throughput)}</td>
                  <td>
                    {g.ratio === null ? "—" : `${format(g.ratio * 100)}%`}
                  </td>
                  <td>{format(g.distance)}</td>
                  <td>{format(g.energy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && (
            <p className="empty">
              尚无实验结果。创建实验后，已完成的真实数据将在这里出现。
            </p>
          )}
        </div>
      </section>
      {detail && (
        <section className="panel compact">
          <div className="panel-heading">
            <h3>运行详情 · {detail.manifest.run_id}</h3>
            <button onClick={() => setDetail(null)}>关闭详情</button>
          </div>
          <p className="muted mono">
            Trace SHA256 {detail.manifest.trace_hash}
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>口径</th>
                  <th>MeanWait / 秒</th>
                  <th>P95 / 秒</th>
                  <th>完成率</th>
                  <th>未接到</th>
                  <th>未完成</th>
                  <th>等待下界 / 秒</th>
                </tr>
              </thead>
              <tbody>
                {(["at_horizon", "final"] as const).map((k) => (
                  <tr key={k}>
                    <td>{k === "at_horizon" ? "到达窗口 H" : "最终 cohort"}</td>
                    <td>{format(detail.metrics[k].mean_wait_s)}</td>
                    <td>{format(detail.metrics[k].p95_wait_s)}</td>
                    <td>
                      {format(Number(detail.metrics[k].completion_ratio) * 100)}
                      %
                    </td>
                    <td>{detail.metrics[k].unpicked}</td>
                    <td>{detail.metrics[k].unfinished}</td>
                    <td>
                      {format(
                        detail.metrics[k].censored_mean_wait_lower_bound_s,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="downloads">
            {detail.artifacts.map((a) => (
              <a key={a.name} href={a.url} download>
                {a.name} ↗
              </a>
            ))}
          </div>
        </section>
      )}
      {rows.length > 0 && (
        <>
          <div className="two-panels">
            <section className="panel">
              <div className="panel-heading">
                <h3>等待与距离的权衡</h3>
                <small>绘图每策略最多500条，统计/下载使用全量</small>
              </div>
              <Chart
                option={option}
                label="各策略每条Trace的等待和距离散点图"
              />
            </section>
            <section className="panel compact">
              <h3>相对 ETA 的配对差异</h3>
              <div className="page-controls">
                <button
                  disabled={intervalPage === 0}
                  onClick={() => setIntervalPage(intervalPage - 1)}
                >
                  上一组区间
                </button>
                <span>
                  {intervalPage + 1}/
                  {Math.max(1, Math.ceil(intervals.length / 50))} · 共
                  {intervals.length}项
                </span>
                <button
                  disabled={(intervalPage + 1) * 50 >= intervals.length}
                  onClick={() => setIntervalPage(intervalPage + 1)}
                >
                  下一组区间
                </button>
              </div>
              <p className="muted">
                负值代表该指标更低；按Trace进行2000次bootstrap，非乘客独立抽样。
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>策略 / 指标</th>
                      <th>差值</th>
                      <th>95% 区间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intervals
                      .slice(intervalPage * 50, intervalPage * 50 + 50)
                      .map((r, i) => (
                        <tr key={i}>
                          <td>
                            {r.controller}
                            <small>{r.metric}</small>
                          </td>
                          <td>{format(r.mean_difference)}</td>
                          <td>
                            [{format(r.ci_low)}, {format(r.ci_high)}]
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
          {distributions.length > 0 && (
            <section className="panel">
              <div className="panel-heading">
                <h3>乘客等待分布 · 描述性箱线图</h3>
                <small>min / Q1 / median / Q3 / max；条件样本另标</small>
              </div>
              <Chart option={boxOption} label="真实乘客等待时间箱线分布" />
              <p className="muted inset">
                {distributions
                  .map(
                    (d) =>
                      `${d.controller}: ${d.count}人${d.conditional ? "（含不完整运行的已接到样本）" : ""}`,
                  )
                  .join(" · ")}
              </p>
            </section>
          )}
          <section className="panel compact">
            <h3>原始运行与导出</h3>
            <div className="page-controls">
              <button
                disabled={runPage === 0}
                onClick={() => setRunPage(runPage - 1)}
              >
                上一页运行
              </button>
              <span>
                {runPage + 1}/{Math.max(1, Math.ceil(rows.length / 20))} · 共
                {rows.length}条
              </span>
              <button
                disabled={(runPage + 1) * 20 >= rows.length}
                onClick={() => setRunPage(runPage + 1)}
              >
                下一页运行
              </button>
            </div>
            <div className="downloads">
              {[
                "report.md",
                "runs.csv",
                "summary.csv",
                "paired_differences.csv",
                "confidence_intervals.csv",
                "manifest.json",
                "suite.yaml",
                "distributions.json",
                "figure~wait_distance.svg",
                "figure~wait_distance.png",
              ].map((name) => (
                <a key={name} href={`/api/v1/artifacts/${id}:${name}`} download>
                  {name} ↗
                </a>
              ))}
            </div>
            <p className="muted">
              能耗是代理量，不是真实kWh。正式结论需至少20条测试Trace及多训练seed；少量页面实验仅作开发验证。
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>策略</th>
                    <th>Seed</th>
                    <th>Trace SHA256</th>
                    <th>运行</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(runPage * 20, runPage * 20 + 20).map((r, i) => (
                    <tr key={i}>
                      <td>{r.controller}</td>
                      <td>{r.seed}</td>
                      <td className="mono" title={String(r.trace_hash)}>
                        {String(r.trace_hash).slice(0, 20)}…
                      </td>
                      <td>
                        <button
                          className="mono"
                          onClick={() => void inspect(String(r.run_id))}
                        >
                          查看 {r.run_id}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button onClick={() => onRun("")}>返回实时仿真</button>
          </section>
        </>
      )}
    </>
  );
}
