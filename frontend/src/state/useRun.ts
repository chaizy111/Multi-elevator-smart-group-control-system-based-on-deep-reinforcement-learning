import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Job, Snapshot } from "../types";

export const terminal = (status: string) =>
  ["COMPLETED", "STOPPED", "FAILED"].includes(status);
export function useRun(id: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setJob(null);
    setSnapshot(null);
    setError("");
    setConnected(false);
    if (!id) return;
    let disposed = false,
      finished = false,
      retry = 0;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    function accept(value: Snapshot) {
      if (disposed || !value.elevators) return;
      setSnapshot((old) =>
        !old || value.sequence >= old.sequence ? value : old,
      );
    }
    async function refresh() {
      try {
        const value = await api<Job>(`/simulations/${id}`, {
          signal: abort.signal,
        });
        if (disposed) return;
        setJob(value);
        setError(value.error?.message ?? "");
        if (value.snapshot) accept({ ...value.snapshot, status: value.status });
        finished = terminal(value.status);
        if (finished) {
          socket?.close();
          setConnected(false);
        }
      } catch (e) {
        if (!disposed) setError(String(e));
      }
    }
    function connect() {
      if (disposed || finished) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/v1/simulations/${id}`,
      );
      socket.onopen = () => {
        if (!disposed) {
          setConnected(true);
          retry = 0;
        }
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        const value = JSON.parse(event.data) as Snapshot;
        accept(value);
        if (
          value.type === "completed" ||
          value.type === "error" ||
          value.type === "command_applied" ||
          value.type === "status_changed"
        )
          void refresh();
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnected(false);
        if (!finished)
          timer = setTimeout(connect, Math.min(10000, 500 * 2 ** retry++));
      };
      socket.onerror = () => socket?.close();
    }
    void refresh();
    connect();
    const poll = setInterval(() => {
      if (!finished) void refresh();
    }, 500);
    return () => {
      disposed = true;
      abort.abort();
      clearInterval(poll);
      clearTimeout(timer);
      socket?.close();
    };
  }, [id]);
  return { job, snapshot, connected, error };
}
