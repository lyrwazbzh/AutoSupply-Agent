"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import { useAuth } from "@/components/auth/AuthProvider";
import ManagementShell from "@/components/erp/ManagementShell";
import { EmptyRow, ErpAlert, ErpPageHeader, fieldClass, primaryButtonClass, secondaryButtonClass, StatusPill } from "@/components/erp/ErpUi";
import { erpJson } from "@/lib/auth";
import { buildQuery, newOperationId, operationHeaders, PageResult, ReplenishmentTask } from "@/lib/erp";

const STATUS_LABEL: Record<string, string> = { PENDING: "待处理", ORDER_CREATED: "已转订单", COMPLETED: "已完成", CANCELLED: "已取消" };

export default function ReplenishmentPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("erp:replenishment:manage");
  const [data, setData] = useState<PageResult<ReplenishmentTask>>({ records: [], total: 0, pages: 0, current: 1, size: 50 });
  const [status, setStatus] = useState("");
  const [partId, setPartId] = useState("");
  const [appliedFilters, setAppliedFilters] = useState({ status: "", partId: "" });
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const fetchTasks = useCallback(async (filters: { status: string; partId: string }) => {
    setData(await erpJson<PageResult<ReplenishmentTask>>(`/replenishment/page${buildQuery({ current: 1, size: 50, ...filters })}`));
  }, []);

  const load = useCallback(() => fetchTasks(appliedFilters), [appliedFilters, fetchTasks]);

  useEffect(() => {
    const timer = window.setTimeout(() => void fetchTasks({ status: "", partId: "" }).catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败")), 0);
    return () => window.clearTimeout(timer);
  }, [fetchTasks]);

  async function run(action: () => Promise<void>, success?: string) {
    try {
      setError(""); setNotice(""); await action(); if (success) setNotice(success);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
  }

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      const operationId = newOperationId("ui-replenishment-create");
      await erpJson("/replenishment/create", { method: "POST", headers: operationHeaders(operationId), body: JSON.stringify({ partId: Number(form.get("partId")), suggestedQuantity: form.get("suggestedQuantity") ? Number(form.get("suggestedQuantity")) : null, preferredSupplierId: form.get("preferredSupplierId") ? Number(form.get("preferredSupplierId")) : null, reason: form.get("reason") || null, operationId }) });
      formElement.reset(); setShowCreate(false); await load();
    }, "补货任务已创建");
  }

  function inspect() {
    if (!window.confirm("立即按当前库存执行一次确定性低库存巡检？")) return;
    void run(async () => {
      const operationId = newOperationId("ui-replenishment-inspect");
      await erpJson(`/replenishment/inspect${buildQuery({ operationId })}`, { method: "POST", headers: operationHeaders(operationId) });
      await load();
    }, "库存巡检已完成，补货任务列表已刷新");
  }

  function taskAction(task: ReplenishmentTask, action: "create-order" | "complete" | "cancel") {
    const label = action === "create-order" ? "转为采购订单" : action === "complete" ? "完成" : "取消";
    if (!window.confirm(`确认${label}补货任务 ${task.taskNo}？`)) return;
    void run(async () => {
      const operationId = newOperationId(`ui-replenishment-${action}`);
      await erpJson(`/replenishment/${task.id}/${action}${buildQuery({ operationId })}`, {
        method: "POST",
        headers: operationHeaders(operationId),
        ...(action === "create-order" ? { body: JSON.stringify({ operationId }) } : {}),
      });
      await load();
    }, action === "create-order" ? "补货任务已生成待审核采购订单" : `补货任务已${label}`);
  }

  return <RequireAuth permission="erp:replenishment:read"><ManagementShell>
    <ErpPageHeader title="补货任务" description="由安全库存规则生成补货建议，采购员确认后再转为待审核采购订单。" actions={canManage ? <><button onClick={inspect} className={secondaryButtonClass}>立即库存巡检</button><button onClick={() => setShowCreate((value) => !value)} className={primaryButtonClass}>{showCreate ? "收起" : "人工建任务"}</button></> : undefined} />
    <div className="space-y-5 p-5 md:p-8">
      {error && <ErpAlert message={error} />}{notice && <ErpAlert message={notice} tone="success" />}
      {showCreate && <form onSubmit={createTask} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-5"><input required name="partId" type="number" min="1" placeholder="零件 ID" className={fieldClass} /><input name="suggestedQuantity" type="number" min="1" placeholder="建议数量（可自动计算）" className={fieldClass} /><input name="preferredSupplierId" type="number" min="1" placeholder="首选供应商 ID" className={fieldClass} /><input name="reason" placeholder="补货原因" className={fieldClass} /><button className={primaryButtonClass}>创建任务</button></form>}
      <form onSubmit={(event) => { event.preventDefault(); const next = { status, partId }; setAppliedFilters(next); void run(() => fetchTasks(next)); }} className="flex flex-wrap gap-3 rounded-xl border bg-white p-4"><select value={status} onChange={(e) => setStatus(e.target.value)} className={fieldClass}><option value="">全部状态</option>{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={partId} onChange={(e) => setPartId(e.target.value)} type="number" min="1" placeholder="零件 ID" className={fieldClass} /><button className={secondaryButtonClass}>查询</button><span className="self-center text-sm text-slate-500">共 {data.total} 个任务</span></form>
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">任务</th><th className="p-3">零件</th><th className="p-3">库存依据</th><th className="p-3">建议采购</th><th className="p-3">首选供应商</th><th className="p-3">来源 / 原因</th><th className="p-3">状态</th><th className="p-3">操作</th></tr></thead><tbody>
        {data.records.map((task) => <tr key={task.id} className="border-t"><td className="p-3"><p className="font-medium">{task.taskNo}</p><p className="text-xs text-slate-400">{task.createTime || task.inspectionDate || "—"}</p></td><td className="p-3">零件 #{task.partId}</td><td className="p-3">当前 {task.currentQuantity} / 安全 {task.safetyStock}</td><td className="p-3 font-semibold">{task.suggestedQuantity}</td><td className="p-3">{task.preferredSupplierId ? `#${task.preferredSupplierId}` : "系统择优"}</td><td className="p-3"><p>{task.source === "MANUAL" ? "人工" : "库存巡检"}</p><p className="max-w-56 truncate text-xs text-slate-400">{task.reason || "—"}</p></td><td className="p-3"><StatusPill tone={task.status === "COMPLETED" ? "green" : task.status === "CANCELLED" ? "red" : task.status === "ORDER_CREATED" ? "blue" : "amber"}>{STATUS_LABEL[task.status]}</StatusPill>{task.relatedOrderId && <p className="mt-1 text-xs text-slate-400">订单 #{task.relatedOrderId}</p>}</td><td className="p-3">{canManage && task.status === "PENDING" && <div className="flex min-w-40 flex-wrap gap-3"><button onClick={() => taskAction(task, "create-order")} className="font-medium text-blue-600">转采购单</button><button onClick={() => taskAction(task, "complete")} className="text-emerald-700">直接完成</button><button onClick={() => taskAction(task, "cancel")} className="text-red-600">取消</button></div>}</td></tr>)}
        {!data.records.length && <EmptyRow colSpan={8} text="暂无补货任务" />}
      </tbody></table></div>
    </div>
  </ManagementShell></RequireAuth>;
}
