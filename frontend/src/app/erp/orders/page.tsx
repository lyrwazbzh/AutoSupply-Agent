"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import { useAuth } from "@/components/auth/AuthProvider";
import ManagementShell from "@/components/erp/ManagementShell";
import {
  EmptyRow,
  ErpAlert,
  ErpPageHeader,
  fieldClass,
  primaryButtonClass,
  secondaryButtonClass,
  StatusPill,
} from "@/components/erp/ErpUi";
import { erpJson } from "@/lib/auth";
import { buildQuery, money, newOperationId, operationHeaders, ORDER_STATUS, PageResult, PurchaseOrder, PurchaseOrderLine } from "@/lib/erp";

type NewLine = Pick<PurchaseOrderLine, "partId" | "quantity" | "unitPrice" | "remark">;

export default function PurchaseOrdersPage() {
  const { hasPermission } = useAuth();
  const canCreate = hasPermission("erp:order:create");
  const canChangeStatus = hasPermission("erp:order:status");
  const canReceive = hasPermission("erp:order:receive");
  const [data, setData] = useState<PageResult<PurchaseOrder>>({ records: [], total: 0, pages: 0, current: 1, size: 50 });
  const [orderNumber, setOrderNumber] = useState("");
  const [status, setStatus] = useState("");
  const [appliedFilters, setAppliedFilters] = useState({ orderNumber: "", status: "" });
  const [showCreate, setShowCreate] = useState(false);
  const [lines, setLines] = useState<NewLine[]>([{ partId: 0, quantity: 1, unitPrice: 0, remark: "" }]);
  const [receiveOrder, setReceiveOrder] = useState<PurchaseOrder | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const fetchOrders = useCallback(async (filters: { orderNumber: string; status: string }) => {
    const query = buildQuery({ current: 1, size: 50, ...filters });
    setData(await erpJson<PageResult<PurchaseOrder>>(`/orders/page${query}`));
  }, []);

  const load = useCallback(() => fetchOrders(appliedFilters), [appliedFilters, fetchOrders]);

  useEffect(() => {
    const timer = window.setTimeout(() => void fetchOrders({ orderNumber: "", status: "" }).catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败")), 0);
    return () => window.clearTimeout(timer);
  }, [fetchOrders]);

  const draftTotal = useMemo(() => lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unitPrice || 0), 0), [lines]);

  async function run(action: () => Promise<void>, success?: string) {
    try {
      setError("");
      setNotice("");
      await action();
      if (success) setNotice(success);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    }
  }

  function updateLine(index: number, patch: Partial<NewLine>) {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  }

  async function createOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      if (lines.some((line) => line.partId <= 0 || line.quantity <= 0 || line.unitPrice < 0)) throw new Error("请完整填写有效的订单明细");
      const operationId = newOperationId("ui-order-create");
      await erpJson("/orders/create", {
        method: "POST",
        headers: operationHeaders(operationId),
        body: JSON.stringify({
          orderNumber: form.get("orderNumber") || null,
          supplierId: Number(form.get("supplierId")),
          expectedDeliveryDate: form.get("expectedDeliveryDate") || null,
          remark: form.get("remark") || null,
          totalAmount: draftTotal,
          orderDetail: lines,
          operationId,
          idempotencyKey: operationId,
        }),
      });
      formElement.reset();
      setLines([{ partId: 0, quantity: 1, unitPrice: 0, remark: "" }]);
      setShowCreate(false);
      await load();
    }, "采购订单已创建，当前状态为待审核");
  }

  function changeStatus(order: PurchaseOrder, nextStatus: number) {
    if (!window.confirm(`确认将 ${order.orderNumber} 变更为“${ORDER_STATUS[nextStatus]}”？`)) return;
    void run(async () => {
      const operationId = newOperationId("ui-order-status");
      await erpJson(`/orders/update-status/${order.id}${buildQuery({ status: nextStatus, operationId })}`, { method: "PATCH", headers: operationHeaders(operationId) });
      await load();
    }, `订单已变更为${ORDER_STATUS[nextStatus]}`);
  }

  async function receive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!receiveOrder) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      const operationId = newOperationId("ui-order-receive");
      await erpJson(`/orders/${receiveOrder.id}/receive`, {
        method: "POST",
        headers: operationHeaders(operationId),
        body: JSON.stringify({ operationId, actualArrivalDate: form.get("actualArrivalDate") || null, warehouseLocation: form.get("warehouseLocation") || null, remark: form.get("remark") || null }),
      });
      setReceiveOrder(null);
      await load();
    }, "采购订单已确认收货，库存与流水已同步更新");
  }

  return (
    <RequireAuth permission="erp:order:read">
      <ManagementShell>
        <ErpPageHeader title="采购订单" description="维护待审核、已审核、采购中、已入库和已取消的采购状态闭环。" actions={canCreate ? <button onClick={() => setShowCreate((value) => !value)} className={primaryButtonClass}>{showCreate ? "收起建单" : "新建采购单"}</button> : undefined} />
        <div className="space-y-5 p-5 md:p-8">
          {error && <ErpAlert message={error} />}{notice && <ErpAlert message={notice} tone="success" />}
          {showCreate && <form onSubmit={createOrder} className="space-y-4 rounded-xl border bg-white p-5">
            <div className="grid gap-3 md:grid-cols-4"><input name="orderNumber" placeholder="订单号（留空自动生成）" className={fieldClass} /><input required name="supplierId" type="number" min="1" placeholder="供应商 ID" className={fieldClass} /><input name="expectedDeliveryDate" type="date" className={fieldClass} /><input name="remark" placeholder="订单备注" className={fieldClass} /></div>
            <div className="space-y-2"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">订单明细</h3><button type="button" onClick={() => setLines((current) => [...current, { partId: 0, quantity: 1, unitPrice: 0, remark: "" }])} className={secondaryButtonClass}>添加明细</button></div>
              {lines.map((line, index) => <div key={index} className="grid gap-2 rounded-lg bg-slate-50 p-3 md:grid-cols-[1fr_1fr_1fr_2fr_auto]"><input required value={line.partId || ""} onChange={(e) => updateLine(index, { partId: Number(e.target.value) })} type="number" min="1" placeholder="零件 ID" className={fieldClass} /><input required value={line.quantity} onChange={(e) => updateLine(index, { quantity: Number(e.target.value) })} type="number" min="1" placeholder="数量" className={fieldClass} /><input required value={line.unitPrice || ""} onChange={(e) => updateLine(index, { unitPrice: Number(e.target.value) })} type="number" min="0" step="0.01" placeholder="单价" className={fieldClass} /><input value={line.remark || ""} onChange={(e) => updateLine(index, { remark: e.target.value })} placeholder="明细备注" className={fieldClass} /><button disabled={lines.length === 1} type="button" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))} className="px-3 text-sm text-red-600 disabled:text-slate-300">移除</button></div>)}
            </div>
            <div className="flex items-center justify-between"><p className="text-sm text-slate-500">预计总额：<span className="font-semibold text-slate-900">{money(draftTotal)}</span></p><button className={primaryButtonClass}>创建待审核订单</button></div>
          </form>}

          {receiveOrder && <form onSubmit={receive} className="grid gap-3 rounded-xl border border-blue-200 bg-blue-50 p-5 md:grid-cols-4"><div className="md:col-span-4"><h3 className="font-semibold text-blue-950">确认收货：{receiveOrder.orderNumber}</h3><p className="mt-1 text-xs text-blue-700">整单入库，不支持部分收货；提交后库存、流水与订单状态在同一事务更新。</p></div><input required defaultValue={new Date().toISOString().slice(0, 10)} name="actualArrivalDate" type="date" className={fieldClass} /><input name="warehouseLocation" placeholder="仓位（可选）" className={fieldClass} /><input name="remark" placeholder="收货备注" className={fieldClass} /><div className="flex gap-2"><button className={primaryButtonClass}>确认整单收货</button><button type="button" onClick={() => setReceiveOrder(null)} className={secondaryButtonClass}>取消</button></div></form>}

          <form onSubmit={(event) => { event.preventDefault(); const next = { orderNumber, status }; setAppliedFilters(next); void run(() => fetchOrders(next)); }} className="flex flex-wrap gap-3 rounded-xl border bg-white p-4"><input value={orderNumber} onChange={(e) => setOrderNumber(e.target.value)} placeholder="订单编号" className={fieldClass} /><select value={status} onChange={(e) => setStatus(e.target.value)} className={fieldClass}><option value="">全部状态</option>{Object.entries(ORDER_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button className={secondaryButtonClass}>查询</button><span className="self-center text-sm text-slate-500">共 {data.total} 张订单</span></form>
          <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">订单</th><th className="p-3">供应商</th><th className="p-3">明细</th><th className="p-3">金额</th><th className="p-3">交期</th><th className="p-3">状态</th><th className="p-3">操作</th></tr></thead><tbody>
            {data.records.map((order) => <tr key={order.id} className="border-t align-top"><td className="p-3"><p className="font-medium">{order.orderNumber}</p><p className="mt-1 text-xs text-slate-400">#{order.id} · {order.orderTime || "—"}</p></td><td className="p-3">{order.supplierId ? `#${order.supplierId}` : "—"}</td><td className="p-3"><div className="space-y-1">{(order.orderDetail || []).slice(0, 3).map((line) => <p key={line.id || `${line.partId}-${line.quantity}`}><span className="font-medium">{line.partDetail?.name || `零件 #${line.partId}`}</span> × {line.quantity}</p>)}{(order.orderDetail?.length || 0) > 3 && <p className="text-xs text-slate-400">另 {Number(order.orderDetail?.length) - 3} 项</p>}</div></td><td className="p-3 font-medium">{money(order.totalAmount)}</td><td className="p-3"><p>{order.expectedDeliveryDate || "—"}</p>{order.actualDeliveryDate && <p className="mt-1 text-xs text-emerald-700">实到 {order.actualDeliveryDate}</p>}</td><td className="p-3"><StatusPill tone={statusTone(order.status)}>{ORDER_STATUS[order.status] || order.status}</StatusPill></td><td className="p-3"><div className="flex min-w-32 flex-wrap gap-x-3 gap-y-2">{canChangeStatus && order.status === 1 && <button onClick={() => changeStatus(order, 2)} className="text-blue-600">审核通过</button>}{canChangeStatus && order.status === 2 && <button onClick={() => changeStatus(order, 3)} className="text-blue-600">开始采购</button>}{canReceive && order.status === 3 && <button onClick={() => setReceiveOrder(order)} className="font-medium text-emerald-700">确认收货</button>}{canChangeStatus && [1, 2, 3].includes(order.status) && <button onClick={() => changeStatus(order, 5)} className="text-red-600">取消订单</button>}</div></td></tr>)}
            {!data.records.length && <EmptyRow colSpan={7} text="未找到采购订单" />}
          </tbody></table></div>
        </div>
      </ManagementShell>
    </RequireAuth>
  );
}

function statusTone(status: number): "slate" | "blue" | "green" | "amber" | "red" {
  if (status === 4) return "green";
  if (status === 5) return "red";
  if (status === 1) return "amber";
  return "blue";
}
