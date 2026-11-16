"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import { useAuth } from "@/components/auth/AuthProvider";
import ManagementShell from "@/components/erp/ManagementShell";
import { EmptyRow, ErpAlert, ErpPageHeader, fieldClass, primaryButtonClass, secondaryButtonClass, StatusPill } from "@/components/erp/ErpUi";
import { erpJson } from "@/lib/auth";
import { buildQuery, newOperationId, operationHeaders, PageResult, PurchaseReturn, RETURN_REASON } from "@/lib/erp";

export default function PurchaseReturnsPage() {
  const { hasPermission } = useAuth();
  const canReturn = hasPermission("erp:order:return");
  const [data, setData] = useState<PageResult<PurchaseReturn>>({ records: [], total: 0, pages: 0, current: 1, size: 50 });
  const [status, setStatus] = useState("");
  const [orderId, setOrderId] = useState("");
  const [partId, setPartId] = useState("");
  const [appliedFilters, setAppliedFilters] = useState({ status: "", orderId: "", partId: "" });
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const fetchReturns = useCallback(async (filters: { status: string; orderId: string; partId: string }) => {
    setData(await erpJson<PageResult<PurchaseReturn>>(`/purchase-returns/page${buildQuery({ current: 1, size: 50, ...filters })}`));
  }, []);

  const load = useCallback(() => fetchReturns(appliedFilters), [appliedFilters, fetchReturns]);

  useEffect(() => {
    const timer = window.setTimeout(() => void fetchReturns({ status: "", orderId: "", partId: "" }).catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败")), 0);
    return () => window.clearTimeout(timer);
  }, [fetchReturns]);

  async function run(action: () => Promise<void>, success?: string) {
    try { setError(""); setNotice(""); await action(); if (success) setNotice(success); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
  }

  async function createReturn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      const operationId = newOperationId("ui-return-create");
      await erpJson("/purchase-returns/create", { method: "POST", headers: operationHeaders(operationId), body: JSON.stringify({ purchaseOrderId: Number(form.get("purchaseOrderId")), partId: Number(form.get("partId")), quantity: Number(form.get("quantity")), reasonType: form.get("reasonType"), reason: form.get("reason") || null, operationId }) });
      formElement.reset(); setShowCreate(false); await load();
    }, "采购退货单已创建，确认前不会扣减库存");
  }

  function confirmReturn(row: PurchaseReturn) {
    if (!window.confirm(`确认退货单 ${row.returnNumber}？确认后将扣减 ${row.quantity} 件库存，且不可撤销。`)) return;
    void run(async () => {
      const operationId = newOperationId("ui-return-confirm");
      await erpJson(`/purchase-returns/${row.id}/confirm${buildQuery({ operationId })}`, { method: "POST", headers: operationHeaders(operationId) });
      await load();
    }, "退货已确认，库存和采购退货流水已同步更新");
  }

  return <RequireAuth permission="erp:order:read"><ManagementShell>
    <ErpPageHeader title="采购退货" description="只处理已入库采购单的轻量退货；创建待确认单，确认后再扣库存并生成流水。" actions={canReturn ? <button onClick={() => setShowCreate((value) => !value)} className={primaryButtonClass}>{showCreate ? "收起" : "新建退货单"}</button> : undefined} />
    <div className="space-y-5 p-5 md:p-8">
      {error && <ErpAlert message={error} />}{notice && <ErpAlert message={notice} tone="success" />}
      {showCreate && <form onSubmit={createReturn} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-6"><input required name="purchaseOrderId" type="number" min="1" placeholder="已入库采购单 ID" className={fieldClass} /><input required name="partId" type="number" min="1" placeholder="零件 ID" className={fieldClass} /><input required name="quantity" type="number" min="1" placeholder="退货数量" className={fieldClass} /><select required name="reasonType" className={fieldClass}>{Object.entries(RETURN_REASON).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input name="reason" placeholder="退货说明（其他原因必填）" className={fieldClass} /><button className={primaryButtonClass}>创建待确认退货单</button></form>}
      <form onSubmit={(event) => { event.preventDefault(); const next = { status, orderId, partId }; setAppliedFilters(next); void run(() => fetchReturns(next)); }} className="flex flex-wrap gap-3 rounded-xl border bg-white p-4"><select value={status} onChange={(e) => setStatus(e.target.value)} className={fieldClass}><option value="">全部状态</option><option value="PENDING">待确认</option><option value="CONFIRMED">已确认</option></select><input value={orderId} onChange={(e) => setOrderId(e.target.value)} type="number" min="1" placeholder="采购单 ID" className={fieldClass} /><input value={partId} onChange={(e) => setPartId(e.target.value)} type="number" min="1" placeholder="零件 ID" className={fieldClass} /><button className={secondaryButtonClass}>查询</button><span className="self-center text-sm text-slate-500">共 {data.total} 张退货单</span></form>
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">退货单</th><th className="p-3">来源采购单</th><th className="p-3">零件</th><th className="p-3">数量</th><th className="p-3">原因</th><th className="p-3">状态</th><th className="p-3">操作证据</th><th className="p-3">操作</th></tr></thead><tbody>
        {data.records.map((row) => <tr key={row.id} className="border-t"><td className="p-3"><p className="font-medium">{row.returnNumber}</p><p className="text-xs text-slate-400">{row.createTime || "—"}</p></td><td className="p-3">#{row.purchaseOrderId}</td><td className="p-3">#{row.partId}</td><td className="p-3 font-semibold">{row.quantity}</td><td className="p-3"><p>{RETURN_REASON[row.reasonType] || row.reasonType}</p><p className="max-w-52 truncate text-xs text-slate-400">{row.reason || "—"}</p></td><td className="p-3"><StatusPill tone={row.status === "CONFIRMED" ? "green" : "amber"}>{row.status === "CONFIRMED" ? "已确认" : "待确认"}</StatusPill>{row.confirmedAt && <p className="mt-1 text-xs text-slate-400">{row.confirmedAt}</p>}</td><td className="p-3"><p className="max-w-44 truncate font-mono text-xs" title={row.confirmOperationId || row.operationId}>{row.confirmOperationId || row.operationId || "—"}</p></td><td className="p-3">{canReturn && row.status === "PENDING" && <button onClick={() => confirmReturn(row)} className="font-medium text-red-600">确认扣减库存</button>}</td></tr>)}
        {!data.records.length && <EmptyRow colSpan={8} text="暂无采购退货单" />}
      </tbody></table></div>
    </div>
  </ManagementShell></RequireAuth>;
}
