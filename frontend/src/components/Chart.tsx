import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";

export function Chart({
  option,
  label,
  className = "",
}: {
  option: EChartsOption;
  label: string;
  className?: string;
}) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!node.current) return;
    const chart = echarts.init(node.current, undefined, { renderer: "svg" });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(node.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  return (
    <div
      className={`chart ${className}`.trim()}
      role="img"
      aria-label={label}
      ref={node}
    />
  );
}
