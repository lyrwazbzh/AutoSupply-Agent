"use client";

import { GitBranch } from "lucide-react";

export interface DispatchSpanView {
  callId: string;
  agent: string;
  status: "running" | "completed" | "error" | "timeout" | "verification_failed";
  startedAt?: string;
  finishedAt?: string;
  elapsedMs?: number;
  error?: string;
}

interface Props {
  spans: DispatchSpanView[];
  visible: boolean;
}

function overlapCount(spans: DispatchSpanView[]): number {
  const ended = spans.filter((s) => s.startedAt && s.finishedAt);
  let n = 0;
  for (let i = 0; i < ended.length; i++) {
    for (let j = i + 1; j < ended.length; j++) {
      const a0 = Date.parse(ended[i].startedAt!);
      const a1 = Date.parse(ended[i].finishedAt!);
      const b0 = Date.parse(ended[j].startedAt!);
      const b1 = Date.parse(ended[j].finishedAt!);
      if (a0 < b1 && b0 < a1) n++;
    }
  }
  return n;
}

const STATUS_STYLE: Record<DispatchSpanView["status"], string> = {
  running: "bg-blue-500",
  completed: "bg-emerald-500",
  error: "bg-rose-500",
  timeout: "bg-amber-500",
  verification_failed: "bg-orange-500",
};

/**
 * 同轮多 task 并行时间线：按 started_at/finished_at 展示条带与重叠数。
 */
export default function AgentDispatchTimeline({ spans, visible }: Props) {
  if (!visible || spans.length === 0) return null;

  const times = spans.flatMap((s) => {
    const out: number[] = [];
    if (s.startedAt) out.push(Date.parse(s.startedAt));
    if (s.finishedAt) out.push(Date.parse(s.finishedAt));
    else if (s.startedAt) out.push(Date.now());
    return out;
  });
  const tMin = Math.min(...times);
  const tMax = Math.max(...times, tMin + 1);
  const spanMs = Math.max(tMax - tMin, 1);
  const overlaps = overlapCount(spans);

  return (
    <div className="px-6 py-2 bg-slate-50/90 border-b border-slate-100 animate-fade-in">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-2">
          <GitBranch size={12} className="text-slate-500" />
          <span className="text-[11px] font-medium text-slate-600">子 Agent 派发</span>
          <span className="text-[10px] text-slate-400">
            {spans.length} 路
            {overlaps > 0 ? ` · ${overlaps} 组时间重叠` : ""}
          </span>
        </div>
        <div className="space-y-1.5">
          {spans.map((s) => {
            const start = s.startedAt ? Date.parse(s.startedAt) : tMin;
            const end = s.finishedAt ? Date.parse(s.finishedAt) : Date.now();
            const left = ((start - tMin) / spanMs) * 100;
            const width = Math.max(((end - start) / spanMs) * 100, 2);
            return (
              <div key={s.callId} className="flex items-center gap-2">
                <span
                  className="w-36 shrink-0 text-[10px] text-slate-600 truncate"
                  title={s.agent}
                >
                  {s.agent}
                </span>
                <div className="relative flex-1 h-2 rounded bg-slate-200/80 overflow-hidden">
                  <div
                    className={`absolute top-0 h-full rounded ${STATUS_STYLE[s.status]} ${
                      s.status === "running" ? "animate-pulse" : ""
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={
                      s.error ||
                      `${s.status}${s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ""}`
                    }
                  />
                </div>
                <span className="w-14 shrink-0 text-right text-[10px] text-slate-400">
                  {s.elapsedMs != null ? `${s.elapsedMs}ms` : s.status === "running" ? "…" : ""}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
