import { useEffect, useState } from "react";
import type { Elevator, Snapshot } from "../types";

export function interpolatedPosition(e: Elevator, simTime: number) {
  if (!e.segment) return e.position_floor;
  const s = e.segment;
  const t = Math.min(s.end_us, Math.max(s.start_us, simTime * 1e6));
  return (
    s.from_floor +
    ((s.to_floor - s.from_floor) * (t - s.start_us)) / (s.end_us - s.start_us)
  );
}
export function Building({
  snapshot,
  connected,
  onFloor,
}: {
  snapshot: Snapshot;
  connected: boolean;
  onFloor: (floor: number) => void;
}) {
  const [clock, setClock] = useState(snapshot.sim_time_s);
  useEffect(() => {
    const start = performance.now();
    let frame = 0;
    const animate = () => {
      const age = (performance.now() - start) / 1000;
      const advance =
        connected &&
        snapshot.status === "RUNNING" &&
        snapshot.speed_multiplier > 0 &&
        age < 1
          ? age * snapshot.speed_multiplier
          : 0;
      setClock(snapshot.sim_time_s + advance);
      frame = requestAnimationFrame(animate);
    };
    animate();
    return () => cancelAnimationFrame(frame);
  }, [snapshot, connected]);
  const floors = snapshot.floor_queues.length,
    m = snapshot.elevators.length;
  const row = 38,
    height = floors * row + 64,
    width = 200 + m * 84;
  const y = (floor: number) => height - 46 - (floor - 1) * row;
  return (
    <div className="building-scroll">
      <svg
        aria-label={`${floors}层${m}部电梯实时井道`}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
        style={{ minWidth: Math.max(450, width), height }}
      >
        {snapshot.elevators.map((e, i) => (
          <g key={e.id}>
            <rect
              x={162 + i * 84}
              y={18}
              width={66}
              height={height - 44}
              rx={8}
              fill="#eef2f6"
            />
            <text
              x={195 + i * 84}
              y={height - 9}
              textAnchor="middle"
              fill="#708094"
              fontSize="11"
            >
              {e.id}
            </text>
          </g>
        ))}
        {[...snapshot.floor_queues].reverse().map((q) => (
          <g
            key={q.floor}
            onClick={() => onFloor(q.floor)}
            role="button"
            tabIndex={0}
            aria-label={`查看${q.floor}层乘客`}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onFloor(q.floor);
            }}
            className="floor-row"
          >
            <rect
              x={18}
              y={y(q.floor) - 16}
              width={width - 30}
              height={32}
              fill="transparent"
            />
            <line
              x1={18}
              y1={y(q.floor) + 17}
              x2={width - 12}
              y2={y(q.floor) + 17}
              stroke="#dce4ec"
            />
            <text x={24} y={y(q.floor) + 4} fill="#405268" fontSize="12">
              {String(q.floor).padStart(2, "0")}F
            </text>
            <text
              x={72}
              y={y(q.floor) + 4}
              fill={q.up_count + q.down_count ? "#bd721b" : "#96a4b4"}
              fontSize="11"
            >
              ↑{q.up_count}　↓{q.down_count}
            </text>
          </g>
        ))}
        {snapshot.elevators.map((e, i) => (
          <g
            key={e.id}
            pointerEvents="none"
            transform={`translate(${166 + i * 84},${y(interpolatedPosition(e, clock)) - 15})`}
          >
            <rect
              width={58}
              height={31}
              rx={7}
              fill={
                e.purpose === "REPOSITION"
                  ? "#b98330"
                  : e.phase === "IDLE_CLOSED"
                    ? "#6d8299"
                    : "#177e73"
              }
            />
            <line x1={29} x2={29} y1={4} y2={27} stroke="#ffffff55" />
            <text x={29} y={20} textAnchor="middle" fontSize="11" fill="white">
              {e.load}/{e.capacity}{" "}
              {e.direction === "UP" ? "↑" : e.direction === "DOWN" ? "↓" : "·"}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
