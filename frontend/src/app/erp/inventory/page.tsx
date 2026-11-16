"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { erpJson } from "@/lib/auth";
import { useAuth } from "@/components/auth/AuthProvider";

interface InventoryRow { id: number; partId: number; currentQuantity: number; safetyStock: number; warehouseLocation?: string; partDetail?: { partCode: string; name: string; unit?: string }; }
interface PageData { records: InventoryRow[]; total: number; }

export default function InventoryPage() {
  const { hasPermission } = useAuth();
  const [data, setData] = useState<PageData>({ records: [], total: 0 });
  const [error, setError] = useState("");
  const load = useCallback(() => erpJson<PageData>("/inventory/page?current=1&size=100").then(setData).catch((err) => setError(err instanceof Error ? err.message : "加载失败")), []);
  useEffect(() => { void load(); }, [load]);
  async function adjust(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const direction = String(form.get("direction"));
    const params = new URLSearchParams({ partId: String(form.get("partId")), quantity: String(form.get("quantity")), operationId: crypto.randomUUID() });
    if (direction === "inbound" && form.get("warehouseLocation")) params.set("warehouseLocation", String(form.get("warehouseLocation")));
    try { await erpJson(`/inventory/${direction}?${params}`, { method: "POST", headers: { "X-Operation-Id": params.get("operationId") || "" } }); await load(); event.currentTarget.reset(); }
    catch (err) { setError(err instanceof Error ? err.message : "操作失败"); }
  }
  return <RequireAuth permission="erp:inventory:read"><ManagementShell><header className="border-b bg-white px-8 py-5"><h2 className="text-xl font-semibold">库存管理</h2><p className="mt-1 text-sm text-slate-500">共 {data.total} 条库存记录，入出库操作自动生成幂等 operationId 并写入审计。</p></header><div className="p-8 space-y-5">{error && <p className="rounded bg-red-50 p-3 text-red-700">{error}</p>}{(hasPermission("erp:inventory:inbound") || hasPermission("erp:inventory:outbound")) && <form onSubmit={adjust} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-5"><select name="direction" className="rounded border px-3 py-2">{hasPermission("erp:inventory:inbound") && <option value="inbound">入库</option>}{hasPermission("erp:inventory:outbound") && <option value="outbound">出库</option>}</select><input required type="number" min="1" name="partId" placeholder="零件 ID" className="rounded border px-3 py-2"/><input required type="number" min="1" name="quantity" placeholder="数量" className="rounded border px-3 py-2"/><input name="warehouseLocation" placeholder="仓位（入库可选）" className="rounded border px-3 py-2"/><button className="rounded bg-blue-600 text-white">提交库存操作</button></form>}<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">零件</th><th className="p-3">编码</th><th className="p-3">当前库存</th><th className="p-3">安全库存</th><th className="p-3">仓位</th><th className="p-3">状态</th></tr></thead><tbody>{data.records.map((row) => <tr key={row.id} className="border-t"><td className="p-3 font-medium">{row.partDetail?.name || `零件 #${row.partId}`}</td><td className="p-3">{row.partDetail?.partCode || "—"}</td><td className="p-3">{row.currentQuantity} {row.partDetail?.unit}</td><td className="p-3">{row.safetyStock}</td><td className="p-3">{row.warehouseLocation || "—"}</td><td className={`p-3 ${row.currentQuantity <= row.safetyStock ? "text-amber-700" : "text-emerald-700"}`}>{row.currentQuantity <= row.safetyStock ? "预警" : "正常"}</td></tr>)}</tbody></table></div></div></ManagementShell></RequireAuth>;
}
