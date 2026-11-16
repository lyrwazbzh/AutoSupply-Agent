"use client";

import { useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { erpJson } from "@/lib/auth";

interface AuditEvent { event_id: string; actor_username?: string; source: string; http_method: string; request_path: string; action: string; resource_type?: string; outcome: string; status_code: number; request_id?: string; occurred_at: string; }

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { erpJson<AuditEvent[]>("/audit?limit=200").then(setEvents).catch((err) => setError(err instanceof Error ? err.message : "加载失败")); }, []);
  return <RequireAuth permission="audit:read:self"><ManagementShell><header className="border-b bg-white px-8 py-5"><h2 className="text-xl font-semibold">业务操作审计</h2><p className="mt-1 text-sm text-slate-500">记录 UI、助手和 API 的写操作结果；密码、令牌和请求正文不会进入审计表。</p></header><div className="p-8">{error && <p className="mb-4 rounded bg-red-50 p-3 text-red-700">{error}</p>}<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">时间</th><th className="p-3">操作者</th><th className="p-3">来源</th><th className="p-3">动作</th><th className="p-3">路径</th><th className="p-3">结果</th><th className="p-3">请求 ID</th></tr></thead><tbody>{events.map((event) => <tr key={event.event_id} className="border-t"><td className="whitespace-nowrap p-3">{event.occurred_at}</td><td className="p-3">{event.actor_username || "system"}</td><td className="p-3">{event.source}</td><td className="p-3">{event.action}</td><td className="p-3 font-mono text-xs">{event.http_method} {event.request_path}</td><td className="p-3"><span className={event.outcome === "SUCCESS" ? "text-emerald-700" : "text-red-700"}>{event.outcome} ({event.status_code})</span></td><td className="p-3 font-mono text-xs">{event.request_id || "—"}</td></tr>)}</tbody></table></div></div></ManagementShell></RequireAuth>;
}
