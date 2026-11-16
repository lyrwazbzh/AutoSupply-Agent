"use client";

import { FormEvent, useCallback, useState } from "react";
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
import { money, PartFitment, SupplierOption, VehicleModel } from "@/lib/erp";

interface QuoteDraft {
  supplierId: string;
  supplierPartCode: string;
  purchasePrice: string;
  minimumOrderQuantity: string;
  leadTimeDays: string;
  qualityRating: string;
  enabled: boolean;
  defaultSupplier: boolean;
}

const EMPTY_QUOTE: QuoteDraft = {
  supplierId: "",
  supplierPartCode: "",
  purchasePrice: "",
  minimumOrderQuantity: "1",
  leadTimeDays: "",
  qualityRating: "",
  enabled: true,
  defaultSupplier: false,
};

export default function ProcurementCatalogPage() {
  const { hasPermission } = useAuth();
  const canWriteQuote = hasPermission("erp:supplier-part:write");
  const canWriteFitment = hasPermission("erp:fitment:write");
  const canWriteVehicle = hasPermission("erp:vehicle:write");
  const [partId, setPartId] = useState("");
  const [quotes, setQuotes] = useState<SupplierOption[]>([]);
  const [fitments, setFitments] = useState<PartFitment[]>([]);
  const [quoteDraft, setQuoteDraft] = useState<QuoteDraft>(EMPTY_QUOTE);
  const [editingSupplierId, setEditingSupplierId] = useState<number | null>(null);
  const [vehicleKeyword, setVehicleKeyword] = useState("");
  const [vehicles, setVehicles] = useState<VehicleModel[]>([]);
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const parsedPartId = Number(partId);

  const loadCatalog = useCallback(async (id: number) => {
    if (!Number.isInteger(id) || id <= 0) throw new Error("请输入有效的零件 ID");
    const [nextQuotes, nextFitments] = await Promise.all([
      erpJson<SupplierOption[]>(`/parts/${id}/supplier-options`),
      erpJson<PartFitment[]>(`/parts/${id}/fitments`),
    ]);
    setQuotes(nextQuotes);
    setFitments(nextFitments);
  }, []);

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

  function searchPart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(() => loadCatalog(parsedPartId));
  }

  function editQuote(option: SupplierOption) {
    setEditingSupplierId(option.supplierId);
    setQuoteDraft({
      supplierId: String(option.supplierId),
      supplierPartCode: option.supplierPartCode || "",
      purchasePrice: String(option.purchasePrice),
      minimumOrderQuantity: String(option.minimumOrderQuantity),
      leadTimeDays: option.leadTimeDays === undefined ? "" : String(option.leadTimeDays),
      qualityRating: option.qualityRating === undefined ? "" : String(option.qualityRating),
      enabled: option.enabled,
      defaultSupplier: option.defaultSupplier,
    });
  }

  async function saveQuote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => {
      if (!Number.isInteger(parsedPartId) || parsedPartId <= 0) throw new Error("请先加载一个零件");
      const payload = {
        ...(!editingSupplierId ? { supplierId: Number(quoteDraft.supplierId) } : {}),
        supplierPartCode: quoteDraft.supplierPartCode || null,
        purchasePrice: Number(quoteDraft.purchasePrice),
        minimumOrderQuantity: Number(quoteDraft.minimumOrderQuantity),
        leadTimeDays: quoteDraft.leadTimeDays ? Number(quoteDraft.leadTimeDays) : null,
        qualityRating: quoteDraft.qualityRating ? Number(quoteDraft.qualityRating) : null,
        enabled: quoteDraft.enabled,
        defaultSupplier: quoteDraft.defaultSupplier,
      };
      await erpJson(
        editingSupplierId
          ? `/parts/${parsedPartId}/supplier-options/${editingSupplierId}`
          : `/parts/${parsedPartId}/supplier-options`,
        { method: editingSupplierId ? "PUT" : "POST", body: JSON.stringify(payload) },
      );
      setQuoteDraft(EMPTY_QUOTE);
      setEditingSupplierId(null);
      await loadCatalog(parsedPartId);
    }, editingSupplierId ? "供应商报价已更新" : "供应商报价已创建");
  }

  function deleteQuote(option: SupplierOption) {
    if (!window.confirm(`确认删除 ${option.supplierName || `供应商 #${option.supplierId}`} 的报价？`)) return;
    void run(async () => {
      await erpJson(`/parts/${parsedPartId}/supplier-options/${option.supplierId}`, { method: "DELETE" });
      await loadCatalog(parsedPartId);
    }, "供应商报价已删除");
  }

  async function searchVehicles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(async () => {
      const params = new URLSearchParams({ limit: "50" });
      if (vehicleKeyword.trim()) params.set("keyword", vehicleKeyword.trim());
      setVehicles(await erpJson<VehicleModel[]>(`/vehicle-models/search?${params}`));
    });
  }

  async function createVehicle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      const vehicle = await erpJson<VehicleModel>("/vehicle-models", {
        method: "POST",
        body: JSON.stringify({
          brand: form.get("brand"),
          series: form.get("series") || null,
          model: form.get("model"),
          modelYearStart: form.get("modelYearStart") ? Number(form.get("modelYearStart")) : null,
          modelYearEnd: form.get("modelYearEnd") ? Number(form.get("modelYearEnd")) : null,
          displacement: form.get("displacement") ? Number(form.get("displacement")) : null,
          engineCode: form.get("engineCode") || null,
        }),
      });
      setVehicles((current) => [vehicle, ...current.filter((item) => item.id !== vehicle.id)]);
      setSelectedVehicleId(String(vehicle.id));
      formElement.reset();
    }, "车型档案已创建并选中");
  }

  async function addFitment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      if (!Number.isInteger(parsedPartId) || parsedPartId <= 0) throw new Error("请先加载一个零件");
      await erpJson(`/parts/${parsedPartId}/fitments`, {
        method: "POST",
        body: JSON.stringify({
          vehicleModelId: Number(selectedVehicleId),
          fitmentNote: form.get("fitmentNote") || null,
          verified: form.get("verified") === "on",
        }),
      });
      formElement.reset();
      setSelectedVehicleId("");
      await loadCatalog(parsedPartId);
    }, "车型适配关系已创建");
  }

  function deleteFitment(fitment: PartFitment) {
    if (!window.confirm("确认删除这条车型适配关系？")) return;
    void run(async () => {
      await erpJson(`/parts/${parsedPartId}/fitments/${fitment.vehicleModelId}`, { method: "DELETE" });
      await loadCatalog(parsedPartId);
    }, "车型适配关系已删除");
  }

  return (
    <RequireAuth permission="erp:supplier-part:read">
      <ManagementShell>
        <ErpPageHeader title="供应商报价与车型适配" description="围绕零件维护可采购供应商、价格交期，以及摩托车车型适配关系。" />
        <div className="space-y-6 p-5 md:p-8">
          {error && <ErpAlert message={error} />}
          {notice && <ErpAlert message={notice} tone="success" />}
          <form onSubmit={searchPart} className="flex flex-wrap items-end gap-3 rounded-xl border bg-white p-5">
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              零件 ID
              <input value={partId} onChange={(event) => setPartId(event.target.value)} required min="1" type="number" className={fieldClass} placeholder="例如 12" />
            </label>
            <button className={primaryButtonClass}>加载采购目录</button>
            <p className="pb-2 text-xs text-slate-500">报价和适配关系均以零件为主档，不复制零件基础数据。</p>
          </form>

          <section className="rounded-xl border bg-white">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div><h3 className="font-semibold">供应商报价</h3><p className="mt-1 text-xs text-slate-500">默认报价会同步零件默认供应商和采购价。</p></div>
              <span className="text-sm text-slate-500">{quotes.length} 条</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">供应商</th><th className="p-3">供应商料号</th><th className="p-3">采购价</th><th className="p-3">MOQ</th><th className="p-3">交期</th><th className="p-3">质量</th><th className="p-3">状态</th><th className="p-3">操作</th></tr></thead>
                <tbody>
                  {quotes.map((option) => <tr key={option.id} className="border-t">
                    <td className="p-3"><p className="font-medium">{option.supplierName || `供应商 #${option.supplierId}`}</p><p className="text-xs text-slate-400">{option.supplierCode || `ID ${option.supplierId}`}</p></td>
                    <td className="p-3">{option.supplierPartCode || "—"}</td><td className="p-3 font-medium">{money(option.purchasePrice)}</td><td className="p-3">{option.minimumOrderQuantity}</td><td className="p-3">{option.leadTimeDays === undefined ? "—" : `${option.leadTimeDays} 天`}</td><td className="p-3">{option.qualityRating === undefined ? "—" : `${option.qualityRating}/5`}</td>
                    <td className="p-3"><div className="flex flex-wrap gap-1">{option.defaultSupplier && <StatusPill tone="blue">默认</StatusPill>}<StatusPill tone={option.enabled ? "green" : "slate"}>{option.enabled ? "启用" : "停用"}</StatusPill></div></td>
                    <td className="p-3"><div className="flex gap-3">{canWriteQuote && <button onClick={() => editQuote(option)} className="text-blue-600">编辑</button>}{canWriteQuote && !option.defaultSupplier && <button onClick={() => deleteQuote(option)} className="text-red-600">删除</button>}</div></td>
                  </tr>)}
                  {!quotes.length && <EmptyRow colSpan={8} text={partId ? "未找到供应商报价" : "请先加载零件"} />}
                </tbody>
              </table>
            </div>
            {canWriteQuote && parsedPartId > 0 && <form onSubmit={saveQuote} className="grid gap-3 border-t bg-slate-50 p-5 md:grid-cols-4">
              <input disabled={editingSupplierId !== null} required value={quoteDraft.supplierId} onChange={(e) => setQuoteDraft({ ...quoteDraft, supplierId: e.target.value })} type="number" min="1" placeholder="供应商 ID" className={fieldClass} />
              <input value={quoteDraft.supplierPartCode} onChange={(e) => setQuoteDraft({ ...quoteDraft, supplierPartCode: e.target.value })} placeholder="供应商料号" className={fieldClass} />
              <input required value={quoteDraft.purchasePrice} onChange={(e) => setQuoteDraft({ ...quoteDraft, purchasePrice: e.target.value })} type="number" min="0" step="0.01" placeholder="采购价" className={fieldClass} />
              <input required value={quoteDraft.minimumOrderQuantity} onChange={(e) => setQuoteDraft({ ...quoteDraft, minimumOrderQuantity: e.target.value })} type="number" min="1" placeholder="最小采购量" className={fieldClass} />
              <input value={quoteDraft.leadTimeDays} onChange={(e) => setQuoteDraft({ ...quoteDraft, leadTimeDays: e.target.value })} type="number" min="0" placeholder="交期（天）" className={fieldClass} />
              <input value={quoteDraft.qualityRating} onChange={(e) => setQuoteDraft({ ...quoteDraft, qualityRating: e.target.value })} type="number" min="0" max="5" step="0.1" placeholder="质量评分 0-5" className={fieldClass} />
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={quoteDraft.enabled} onChange={(e) => setQuoteDraft({ ...quoteDraft, enabled: e.target.checked })} />启用报价</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={quoteDraft.defaultSupplier} onChange={(e) => setQuoteDraft({ ...quoteDraft, defaultSupplier: e.target.checked })} />设为默认供应商</label>
              <div className="flex gap-2 md:col-span-4"><button className={primaryButtonClass}>{editingSupplierId ? "保存报价" : "新增报价"}</button>{editingSupplierId && <button type="button" onClick={() => { setEditingSupplierId(null); setQuoteDraft(EMPTY_QUOTE); }} className={secondaryButtonClass}>取消编辑</button>}</div>
            </form>}
          </section>

          <section className="rounded-xl border bg-white">
            <div className="border-b px-5 py-4"><h3 className="font-semibold">车型适配</h3><p className="mt-1 text-xs text-slate-500">先检索车型，再把车型绑定到当前零件。</p></div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">品牌 / 车型</th><th className="p-3">年款</th><th className="p-3">排量</th><th className="p-3">发动机</th><th className="p-3">说明</th><th className="p-3">验证</th><th className="p-3">操作</th></tr></thead><tbody>
                {fitments.map((fitment) => <tr key={fitment.id} className="border-t"><td className="p-3 font-medium">{fitment.vehicleModel.brand} {fitment.vehicleModel.series} {fitment.vehicleModel.model}</td><td className="p-3">{fitment.vehicleModel.modelYearStart || "—"} - {fitment.vehicleModel.modelYearEnd || "—"}</td><td className="p-3">{fitment.vehicleModel.displacement ? `${fitment.vehicleModel.displacement} cc` : "—"}</td><td className="p-3">{fitment.vehicleModel.engineCode || "—"}</td><td className="p-3">{fitment.fitmentNote || "—"}</td><td className="p-3"><StatusPill tone={fitment.verified ? "green" : "amber"}>{fitment.verified ? "已验证" : "待验证"}</StatusPill></td><td className="p-3">{canWriteFitment && <button onClick={() => deleteFitment(fitment)} className="text-red-600">删除</button>}</td></tr>)}
                {!fitments.length && <EmptyRow colSpan={7} text={partId ? "未维护车型适配" : "请先加载零件"} />}
              </tbody></table>
            </div>
            {canWriteFitment && parsedPartId > 0 && <div className="grid gap-5 border-t p-5 lg:grid-cols-2">
              <div className="space-y-3">
                <form onSubmit={searchVehicles} className="flex gap-2"><input value={vehicleKeyword} onChange={(e) => setVehicleKeyword(e.target.value)} placeholder="品牌、车系或车型" className={`${fieldClass} min-w-0 flex-1`} /><button className={secondaryButtonClass}>检索车型</button></form>
                <form onSubmit={addFitment} className="grid gap-3 rounded-lg bg-slate-50 p-4">
                  <select required value={selectedVehicleId} onChange={(e) => setSelectedVehicleId(e.target.value)} className={fieldClass}><option value="">选择车型</option>{vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.brand} {vehicle.series} {vehicle.model} {vehicle.displacement ? `${vehicle.displacement}cc` : ""}</option>)}</select>
                  <input name="fitmentNote" placeholder="适配说明（可选）" className={fieldClass} />
                  <label className="flex items-center gap-2 text-sm"><input name="verified" type="checkbox" />已完成实车/资料验证</label>
                  <button className={primaryButtonClass}>绑定到当前零件</button>
                </form>
              </div>
              {canWriteVehicle && <form onSubmit={createVehicle} className="grid gap-3 rounded-lg border p-4 md:grid-cols-2">
                <p className="font-medium md:col-span-2">快速创建车型档案</p>
                <input required name="brand" placeholder="品牌" className={fieldClass} /><input name="series" placeholder="车系" className={fieldClass} /><input required name="model" placeholder="车型" className={fieldClass} /><input name="displacement" type="number" min="1" placeholder="排量 cc" className={fieldClass} /><input name="modelYearStart" type="number" min="1885" placeholder="起始年款" className={fieldClass} /><input name="modelYearEnd" type="number" min="1885" placeholder="结束年款" className={fieldClass} /><input name="engineCode" placeholder="发动机代码" className={fieldClass} /><button className={primaryButtonClass}>创建并选中</button>
              </form>}
            </div>}
          </section>
        </div>
      </ManagementShell>
    </RequireAuth>
  );
}
