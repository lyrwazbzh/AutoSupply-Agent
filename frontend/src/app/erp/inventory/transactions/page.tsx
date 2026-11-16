"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { EmptyRow, ErpAlert, ErpPageHeader, fieldClass, secondaryButtonClass, StatusPill } from "@/components/erp/ErpUi";
import { erpJson } from "@/lib/auth";
import { buildQuery, InventoryTransaction, PageResult, TRANSACTION_TYPE } from "@/lib/erp";

export default function InventoryTransactionsPage() {
  const [data, setData] = useState<PageResult<InventoryTransaction>>({ records: [], total: 0, pages: 0, current: 1, size: 100 });
  const [filters, setFilters] = useState({ partId: "", transactionType: "", sourceType: "", operationId: "" });
  const [appliedFilters, setAppliedFilters] = useState({ partId: "", transactionType: "", sourceType: "", operationId: "" });
  const [error, setError] = useState("");

  const fetchTransactions = useCallback(async (nextFilters: typeof filters) => {
    setData(await erpJson<PageResult<InventoryTransaction>>(`/inventory/transactions/page${buildQuery({ current: 1, size: 100, ...nextFilters })}`));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void fetchTransactions({ partId: "", transactionType: "", sourceType: "", operationId: "" }).catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败")), 0);
    return () => window.clearTimeout(timer);
  }, [fetchTransactions]);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAppliedFilters(filters);
    void fetchTransactions(filters).catch((reason) => setError(reason instanceof Error ? reason.message : "查询失败"));
  }

  return <RequireAuth permission="erp:inventory:transaction:read"><ManagementShell>
    <ErpPageHeader title="库存流水" description="追踪每次库存变化的前后数量、来源单据、操作者和 operationId。" />
    <div className="space-y-5 p-5 md:p-8">
      {error && <ErpAlert message={error} />}
      <form onSubmit={search} className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-5"><input value={filters.partId} onChange={(e) => setFilters({ ...filters, partId: e.target.value })} type="number" min="1" placeholder="零件 ID" className={fieldClass} /><select value={filters.transactionType} onChange={(e) => setFilters({ ...filters, transactionType: e.target.value })} className={fieldClass}><option value="">全部流水类型</option>{Object.entries(TRANSACTION_TYPE).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={filters.sourceType} onChange={(e) => setFilters({ ...filters, sourceType: e.target.value })} placeholder="来源类型" className={fieldClass} /><input value={filters.operationId} onChange={(e) => setFilters({ ...filters, operationId: e.target.value })} placeholder="operationId" className={fieldClass} /><button className={secondaryButtonClass}>查询流水</button></form>
      <div className="flex justify-between text-sm text-slate-500"><span>共 {data.total} 条库存流水{Object.values(appliedFilters).some(Boolean) ? "（已筛选）" : ""}</span><span>流水只读，不允许前端修改</span></div>
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">流水号 / 时间</th><th className="p-3">零件</th><th className="p-3">类型</th><th className="p-3">数量</th><th className="p-3">变动</th><th className="p-3">来源</th><th className="p-3">仓位</th><th className="p-3">操作证据</th></tr></thead><tbody>
        {data.records.map((row) => <tr key={row.id} className="border-t"><td className="p-3"><p className="font-medium">{row.transactionNo}</p><p className="text-xs text-slate-400">{row.occurredAt || "—"}</p></td><td className="p-3">#{row.partId}</td><td className="p-3"><StatusPill tone={row.quantity < 0 || row.transactionType.includes("OUTBOUND") || row.transactionType === "PURCHASE_RETURN" ? "amber" : "green"}>{TRANSACTION_TYPE[row.transactionType] || row.transactionType}</StatusPill></td><td className={`p-3 font-semibold ${row.afterQuantity < row.beforeQuantity ? "text-amber-700" : "text-emerald-700"}`}>{row.afterQuantity < row.beforeQuantity ? "−" : "+"}{Math.abs(row.quantity)}</td><td className="p-3">{row.beforeQuantity} → {row.afterQuantity}</td><td className="p-3">{row.sourceType || "—"}{row.sourceId ? ` #${row.sourceId}` : ""}</td><td className="p-3">{row.warehouseLocation || "—"}</td><td className="p-3"><p className="max-w-52 truncate font-mono text-xs" title={row.operationId}>{row.operationId || "—"}</p><p className="mt-1 text-xs text-slate-400">操作者 {row.operatorId ? `#${row.operatorId}` : "system"}</p></td></tr>)}
        {!data.records.length && <EmptyRow colSpan={8} text="没有符合条件的库存流水" />}
      </tbody></table></div>
    </div>
  </ManagementShell></RequireAuth>;
}
