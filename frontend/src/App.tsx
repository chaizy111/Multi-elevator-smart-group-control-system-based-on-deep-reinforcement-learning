import { useEffect, useState } from "react";
import { api, command, post } from "./api/client";
import { Configuration } from "./pages/Configuration";
import { Simulation } from "./pages/Simulation";
import { Evaluation } from "./pages/Evaluation";
import { Training } from "./pages/Training";
import type { Config, Model, Trace } from "./types";
import "./style.css";

const navigation = [
  ["config", "01", "场景配置"],
  ["simulation", "02", "实时仿真"],
  ["evaluation", "03", "实验评价"],
  ["training", "04", "训练与模型"],
] as const;
export default function App() {
  const [page, setPage] = useState("config"),
    [config, setConfig] = useState<Config | null>(null),
    [models, setModels] = useState<Model[]>([]),
    [traces, setTraces] = useState<Trace[]>([]),
    [error, setError] = useState("");
  const [runId, setRunId] = useState<string | null>(() =>
    localStorage.getItem("elevator-run"),
  );
  useEffect(() => {
    Promise.all([
      api<{ config: Config }>("/config/defaults"),
      api<{ items: Model[] }>("/models"),
      api<{ items: Trace[] }>("/traces"),
    ])
      .then(([defaults, models, traces]) => {
        setConfig(defaults.config);
        setModels(models.items);
        setTraces(traces.items);
      })
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (runId) localStorage.setItem("elevator-run", runId);
  }, [runId]);
  useEffect(() => {
    if (page === "config")
      void api<{ items: Trace[] }>("/traces")
        .then((v) => setTraces(v.items))
        .catch((e) => setError(String(e)));
  }, [page]);
  async function start(traceId: string | null, speed: number) {
    const value = await post<{ run_id: string }>("/simulations", {
      config,
      trace_id: traceId,
      speed_multiplier: speed,
    });
    await command(value.run_id, "start");
    setRunId(value.run_id);
    setPage("simulation");
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("config");
          }}
        >
          <span className="brand-icon">↟</span>
          <span>
            VERTEX<small>智能电梯群控实验室</small>
          </span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {navigation.map(([key, index, title]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              onClick={() => setPage(key)}
            >
              <span>{index}</span>
              {title}
              {page === key && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="online-dot" /> 本地仿真引擎
          <small>离散事件 · 可变规模 · PPO</small>
          <div className="version">SIMULATION WORKSPACE / v0.1</div>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div>
            <span className="eyebrow">ELEVATOR GROUP CONTROL</span>
            <h1>{navigation.find((n) => n[0] === page)?.[2]}</h1>
          </div>
          <div className="header-right">
            <span className="pill">研究与演示</span>
            <span>确定性仿真 / 01</span>
          </div>
        </header>
        <main>
          {error ? (
            <div className="error" role="alert">
              服务连接失败：{error}
              <button onClick={() => location.reload()}>重新连接</button>
            </div>
          ) : !config ? (
            <div className="panel empty">正在连接本地仿真服务…</div>
          ) : page === "config" ? (
            <Configuration
              config={config}
              setConfig={setConfig}
              models={models}
              traces={traces}
              onStart={start}
            />
          ) : page === "simulation" ? (
            <Simulation
              runId={runId}
              setRunId={setRunId}
              onConfigure={() => setPage("config")}
            />
          ) : page === "evaluation" ? (
            <Evaluation
              config={config}
              models={models}
              onRun={(id) => {
                if (id) setRunId(id);
                setPage("simulation");
              }}
            />
          ) : (
            <Training models={models} />
          )}
        </main>
        <footer>
          VERTEX · Multi-elevator intelligent group control
          <span>工程验收与算法效果分别评价</span>
        </footer>
      </div>
    </div>
  );
}
