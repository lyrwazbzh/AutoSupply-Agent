"use client";

import { useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { authFetch } from "@/lib/auth";
import { BASE_URL } from "@/lib/api";

interface ApprovalTask {
  task_id: string;
  operation_id: string;
  requester_id: string;
  tool_name: string;
  domain: string;
  action: string;
  payload_redacted: Record<string, unknown>;
  payload_hash: string;
  created_at: string;
}

export default function ApprovalQueuePage() {
  const [tasks, setTasks] = useState<ApprovalTask[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const response = await authFetch(`${BASE_URL}/write-audit/approval-queue`);
    if (!response.ok) throw new Error(`审批队列加载失败 (${response.status})`);
    const body = await response.json();
    setTasks(body.approvals ?? []);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      load().catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function decide(task: ApprovalTask, decision: "approve" | "reject") {
    const note = decision === "reject" ? window.prompt("请输入拒绝原因") ?? "" : "";
    if (decision === "reject" && !note) return;
    setBusy(task.operation_id);
    setError("");
    try {
      const response = await authFetch(
        `${BASE_URL}/write-audit/approvals/${encodeURIComponent(task.operation_id)}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, note, payload_hash: task.payload_hash }),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `审批失败 (${response.status})`);
      }
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <RequireAuth permission="erp:order:approve">
      <ManagementShell>
        <header className="border-b bg-white px-8 py-5">
          <h2 className="text-xl font-semibold">写操作审批</h2>
          <p className="mt-1 text-sm text-slate-500">按 operation_id 审批脱敏业务载荷，无需访问申请人的对话。</p>
        </header>
        <div className="space-y-4 p-8">
          {error && <p className="rounded bg-red-50 p-3 text-red-700">{error}</p>}
          {tasks.length === 0 && <p className="rounded-xl border bg-white p-8 text-center text-slate-500">暂无待审批任务</p>}
          {tasks.map((task) => (
            <article key={task.task_id} className="rounded-xl border bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-mono text-sm font-semibold">{task.operation_id}</p>
                  <p className="mt-1 text-sm text-slate-500">申请人 {task.requester_id} · {task.tool_name} · {task.created_at}</p>
                </div>
                <div className="flex gap-2">
                  <button disabled={busy === task.operation_id} onClick={() => void decide(task, "approve")} className="rounded bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50">批准</button>
                  <button disabled={busy === task.operation_id} onClick={() => void decide(task, "reject")} className="rounded bg-red-600 px-4 py-2 text-sm text-white disabled:opacity-50">拒绝</button>
                </div>
              </div>
              <pre className="mt-4 max-h-72 overflow-auto rounded bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(task.payload_redacted, null, 2)}</pre>
              <p className="mt-2 break-all font-mono text-[11px] text-slate-400">payload hash: {task.payload_hash}</p>
            </article>
          ))}
        </div>
      </ManagementShell>
    </RequireAuth>
  );
}
