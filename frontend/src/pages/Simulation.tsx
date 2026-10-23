import { useEffect, useMemo, useState } from "react";
import { api, command } from "../api/client";
import { Building } from "../components/Building";
import { Chart } from "../components/Chart";
import { format, Metric } from "../components/Metric";
import { terminal, useRun } from "../state/useRun";
import type { Artifact, Job, Passenger } from "../types";

const statuses: Record<string, string> = {
  CREATED: "待启动",
  QUEUED: "排队中",
  RUNNING: "运行中",
  PAUSED: "已暂停",
  COMPLETED: "已完成",
  STOPPED: "已停止",
  FAILED: "失败",
};
export function Simulation({
  runId,
  setRunId,
  onConfigure,
}: {
  runId: string | null;
  setRunId: (id: string) => void;
  onConfigure: () => void;
}) {
  const { job, snapshot, connected, error } = useRun(runId);
  const [history, setHistory] = useState<Job[]>([]),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState("");
  const [floor, setFloor] = useState<number | null>(null),
    [offset, setOffset] = useState(0),
    [passengers, setPassengers] = useState<Passenger[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]),
    [timeline, setTimeline] = useState<{ time: number; wait: number | null }[]>(
      [],
    );
  const [archivedTimeline, setArchivedTimeline] = useState(false);
  useEffect(() => {
    void api<{ items: Job[] }>("/simulations")
      .then((v) => setHistory(v.items))
      .catch((e) => setActionError(String(e)));
  }, [runId, job?.status]);
  useEffect(() => {
    setTimeline([]);
    setArchivedTimeline(false);
    setFloor(null);
    setArtifacts([]);
  }, [runId]);
  useEffect(() => {
    if (snapshot)
      setTimeline((old) =>
        old.at(-1)?.time === snapshot.sim_time_s
          ? old
          : [
              ...old,
              {
                time: snapshot.sim_time_s,
                wait:
                  typeof snapshot.metrics.mean_wait_picked_s === "number"
                    ? snapshot.metrics.mean_wait_picked_s
                    : null,
              },
            ].slice(-500),
      );
  }, [snapshot]);
  useEffect(() => {
    if (!runId || floor === null) return;
    let active = true;
    const load = () =>
      api<{ items: Passenger[] }>(
        `/simulations/${runId}/passengers?floor=${floor}&offset=${offset}&limit=20`,
      )
        .then((v) => {
          if (active) setPassengers(v.items);
        })
        .catch((e) => {
          if (active) setActionError(String(e));
        });
    void load();
    const timer =
      job && terminal(job.status) ? null : setInterval(() => void load(), 2000);
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [runId, floor, offset, job?.status]);
  useEffect(() => {
    const abort = new AbortController();
    if (runId && job && terminal(job.status)) {
      void api<{ items: Artifact[] }>(`/simulations/${runId}/artifacts`)
        .then((v) => setArtifacts(v.items))
        .catch((e) => setActionError(String(e)));
      void api<{
        available: boolean;
        items: { time: number; wait: number | null }[];
      }>(`/simulations/${runId}/timeseries?limit=500`, { signal: abort.signal })
        .then((value) => {
          if (!abort.signal.aborted && value.available) {
            setTimeline(value.items);
            setArchivedTimeline(true);
          }
        })
        .catch((e) => {
          if (!abort.signal.aborted) setActionError(String(e));
        });
    }
    return () => abort.abort();
  }, [runId, job?.status]);
  const option = useMemo(
    () => ({
      color: ["#177e73"],
      tooltip: { trigger: "axis" as const },
      grid: { left: 48, right: 20, top: 24, bottom: 32 },
      xAxis: { type: "value" as const, name: "秒" },
      yAxis: { type: "value" as const, name: "已接到等待 / 秒" },
      series: [
        {
          type: "line" as const,
          showSymbol:
            timeline.filter((point) => point.wait !== null).length <= 1,
          connectNulls: false,
          areaStyle: { opacity: 0.08 },
          data: timeline.map((p) => [p.time, p.wait]),
        },
      ],
    }),
    [timeline],
  );
  async function act(kind: string, payload: object = {}) {
    if (!runId) return;
    setBusy(true);
    setActionError("");
    try {
      const value = await command(runId, kind, payload);
      if (value.new_run_id) setRunId(value.new_run_id);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!runId)
    return (
      <div className="panel empty">
        <h2>选择或创建一场仿真</h2>
        <p>查看真实的电梯运行、楼层队列与服务指标。</p>
        <button className="primary" onClick={onConfigure}>
          创建场景
        </button>
        {history.map((j) => (
          <button key={j.id} onClick={() => setRunId(j.id)}>
            {j.id} · {statuses[j.status]}
          </button>
        ))}
      </div>
    );
  const status = job?.status ?? "CREATED",
    live = snapshot?.metrics ?? {},
    final = snapshot?.final_metrics?.final;
  return (
    <>
      <div className="run-toolbar panel">
        <div>
          <span
            className={`status ${status.toLowerCase()}`}
            data-testid="run-status"
          >
            {statuses[status] ?? status}
          </span>
          <span className="mono run-id" data-testid="run-id">
            {runId}
          </span>
          <small>
            {connected
              ? "● 实时已连接"
              : terminal(status)
                ? "结果已归档"
                : "连接中 · 自动重连"}
          </small>
        </div>
        <div className="controls">
          <select
            aria-label="历史运行"
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
          >
            <option value={runId}>{runId.slice(-8)}</option>
            {history
              .filter((j) => j.id !== runId)
              .map((j) => (
                <option key={j.id} value={j.id}>
                  {j.id.slice(-8)} · {statuses[j.status]}
                </option>
              ))}
          </select>
          <select
            aria-label="运行速度控制"
            value={snapshot?.speed_multiplier ?? 5}
            onChange={(e) =>
              void act("speed", { speed_multiplier: Number(e.target.value) })
            }
            disabled={busy || !["RUNNING", "PAUSED"].includes(status)}
          >
            <option value={1}>1×</option>
            <option value={5}>5×</option>
            <option value={20}>20×</option>
            <option value={0}>最快</option>
          </select>
          {status === "CREATED" && (
            <button
              className="primary"
              disabled={busy}
              onClick={() => void act("start")}
            >
              开始
            </button>
          )}
          {status === "RUNNING" && (
            <button disabled={busy} onClick={() => void act("pause")}>
              暂停
            </button>
          )}
          {status === "PAUSED" && (
            <button
              className="primary"
              disabled={busy}
              onClick={() => void act("resume")}
            >
              继续
            </button>
          )}
          <button
            disabled={busy || !["RUNNING", "PAUSED", "QUEUED"].includes(status)}
            onClick={() => void act("stop")}
          >
            停止
          </button>
          <button disabled={busy} onClick={() => void act("reset")}>
            重置
          </button>
        </div>
      </div>
      {(error || actionError) && (
        <div role="alert" className="error">
          {error || actionError}
        </div>
      )}
      <div className="metric-grid">
        <Metric
          label="仿真时间"
          value={snapshot?.sim_time_s}
          unit="s"
          note={
            snapshot && job
              ? snapshot.sim_time_s >=
                job.config.config.simulation.arrival_horizon_s
                ? "排空阶段"
                : "到达窗口"
              : "等待工作进程"
          }
        />
        <Metric label="当前等待" value={live.waiting_count} unit="人" />
        <Metric label="已完成服务" value={live.completed_count} unit="人" />
        <Metric
          label="平均等待 · 已接到"
          value={live.mean_wait_picked_s}
          unit="s"
        />
        <Metric
          label="P95等待 · 已接到"
          value={live.p95_wait_picked_s ?? final?.p95_wait_s}
          unit="s"
        />
        <Metric
          label="累计距离 · 含重定位"
          value={live.distance_floors}
          unit="层"
        />
      </div>
      {final && Number(final.unfinished) > 0 && (
        <p className="notice">
          未接到 {String(final.unpicked)} 人，未完成 {String(final.unfinished)}{" "}
          人；不参与完整服务排名。等待下界{" "}
          {format(final.censored_mean_wait_lower_bound_s)} 秒。
        </p>
      )}
      <div className="monitor-layout">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LIVE SHAFT VIEW</span>
              <h2>电梯群运行</h2>
            </div>
            <div className="legend">
              <i />
              服务 <i className="amber" />
              重定位 <i className="gray" />
              空闲
            </div>
          </div>
          {snapshot?.elevators.length ? (
            <Building
              snapshot={{ ...snapshot, status }}
              connected={connected}
              onFloor={(f) => {
                setFloor(f);
                setOffset(0);
              }}
            />
          ) : (
            <div className="empty">正在等待工作进程的首个完整快照…</div>
          )}
          <p className="muted inset">
            点击楼层查看乘客 · 位置按服务器运动段插值
          </p>
        </section>
        <aside className="panel elevator-panel">
          <span className="eyebrow">ELEVATOR DETAILS</span>
          <h2>轿厢状态</h2>
          {snapshot?.elevators.map((e) => (
            <div className="elevator-card" key={e.id}>
              <div>
                <strong>{e.id}</strong>
                <span>{e.purpose === "REPOSITION" ? "重定位" : e.phase}</span>
              </div>
              <div className="load-track">
                <i style={{ width: `${(e.load / e.capacity) * 100}%` }} />
              </div>
              <p>
                {format(e.position_floor, 2)}F{" "}
                <span>→ {e.target_floor ?? "—"}F</span>
              </p>
              <small>
                {e.direction} · {e.load}/{e.capacity}人 ·{" "}
                {format(e.distance_floors)}层
              </small>
            </div>
          ))}
          <dl>
            <dt>已接到人数</dt>
            <dd>{format(live.picked_count, 0)}</dd>
            <dt>能耗代理（非kWh）</dt>
            <dd>{format(live.energy_proxy)}</dd>
            <dt>吞吐（窗口内人/分钟）</dt>
            <dd>
              {format(live.throughput_per_min ?? final?.throughput_per_min)}
            </dd>
            <dt>长等待比例（已接到）</dt>
            <dd>
              {typeof (live.long_wait_ratio ?? final?.long_wait_ratio) ===
              "number"
                ? `${format(Number(live.long_wait_ratio ?? final?.long_wait_ratio) * 100)}%`
                : "暂无样本"}
            </dd>
          </dl>
        </aside>
      </div>
      {floor !== null && (
        <section className="panel passenger-panel">
          <div className="panel-heading">
            <h3>{floor}F 乘客 · 每页20人</h3>
            <div>
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                上一页
              </button>
              <button
                disabled={passengers.length < 20}
                onClick={() => setOffset(offset + 20)}
              >
                下一页
              </button>
              <button onClick={() => setFloor(null)}>关闭</button>
            </div>
          </div>
          {passengers.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>乘客</th>
                    <th>出行</th>
                    <th>电梯</th>
                    <th>状态</th>
                    <th>等待 / 秒</th>
                  </tr>
                </thead>
                <tbody>
                  {passengers.map((p) => (
                    <tr key={p.passenger_id}>
                      <td>{p.passenger_id}</td>
                      <td>
                        {p.origin_floor} → {p.destination_floor}F
                      </td>
                      <td>{p.assigned_elevator ?? "—"}</td>
                      <td>{p.status}</td>
                      <td>{format(p.waiting_time ?? p.censored_wait_age)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted inset">当前页暂无已到达乘客</p>
          )}
        </section>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h3>已接到乘客的平均等待趋势</h3>
          <span className="muted" data-testid="trend-samples">
            {archivedTimeline ? "归档快照" : "实时快照"} · {timeline.length}点 ·
            最多500点
          </span>
        </div>
        <Chart option={option} label="已接到乘客平均等待随仿真时间变化" />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h3>最近调度决策</h3>
        </div>
        <div className="decision-log">
          {snapshot?.recent_decisions?.length ? (
            snapshot.recent_decisions
              .slice(-12)
              .reverse()
              .map((d, i) => (
                <div key={i}>
                  <span className="mono">
                    {format(Number(d.time_us) / 1e6)}s
                  </span>
                  <strong>{String(d.kind)}</strong>
                  <span>
                    {d.kind === "dispatch"
                      ? `${d.passenger_id} · ${d.origin_floor}→${d.destination_floor}F → E${Number(d.action) + 1}`
                      : `E${Number(d.subject_elevator_id) + 1} → ${["Stay", "Lobby", "Low", "Middle", "High"][Number(d.action) - 8]}`}
                  </span>
                  {d.kind === "dispatch" &&
                  d.eta_s &&
                  typeof d.eta_s === "object" ? (
                    <small className="decision-details">
                      候选ETA：
                      {Object.entries(d.eta_s as Record<string, number>)
                        .map(([e, seconds]) => `${e} ${format(seconds)}s`)
                        .join(" · ")}
                      {typeof d.inference_ms === "number"
                        ? ` ｜ 决策 ${format(d.inference_ms, 2)}ms`
                        : ""}
                      {Array.isArray(d.probabilities)
                        ? ` ｜ PPO ${d.probabilities
                            .slice(0, Object.keys(d.eta_s as object).length)
                            .map(
                              (p, i) => `E${i + 1} ${format(Number(p) * 100)}%`,
                            )
                            .join(" · ")}`
                        : ""}
                    </small>
                  ) : null}
                </div>
              ))
          ) : (
            <p className="muted">当前暂无已执行决策</p>
          )}
        </div>
      </section>
      <section className="panel compact">
        <h3>归档与导出</h3>
        {artifacts.length ? (
          <div className="downloads">
            {artifacts.map((a) => (
              <a key={a.id} href={a.url} download>
                {a.name} ↗
              </a>
            ))}
          </div>
        ) : (
          <p className="muted">
            运行完成或停止后，可下载 Trace、乘客明细、指标、事件与决策记录。
          </p>
        )}
      </section>
    </>
  );
}
