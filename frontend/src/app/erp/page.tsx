"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { erpJson } from "@/lib/auth";

interface Dashboard {
  supplierCount: number;
  partCount: number;
  lowStockCount: number;
  inventoryCount: number;
  monthPurchase?: { orderCount: number; totalAmount: number; completedCount: number };
}

export default function ErpDashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    erpJson<Dashboard>("/statistics/dashboard").then(setData).catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);
  const cards = [
    ["供应商", data?.supplierCount ?? "—"], ["零件档案", data?.partCount ?? "—"],
    ["低库存零件", data?.lowStockCount ?? "—"], ["库存记录", data?.inventoryCount ?? "—"],
  ];
  const quickLinks = [
    ["报价与车型适配", "/erp/catalog", "维护多供应商采购条件与摩托车适配关系"],
    ["采购订单", "/erp/orders", "审核、采购、确认收货并自动入库"],
    ["补货任务", "/erp/replenishment", "处理低库存巡检产生的补货建议"],
    ["库存流水", "/erp/inventory/transactions", "追溯库存变动来源和 operationId"],
    ["采购退货", "/erp/returns", "创建和确认已入库订单的采购退货"],
  ];
  return <RequireAuth permission="erp:statistics:read"><ManagementShell>
    <header className="border-b bg-white px-8 py-5"><h2 className="text-xl font-semibold">经营概览</h2><p className="mt-1 text-sm text-slate-500">传统 ERP 工作台与对话式智能助手共享同一账号和权限。</p></header>
    <div className="p-8 space-y-6">
      {error && <p className="rounded-lg bg-red-50 p-3 text-red-700">{error}</p>}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-4">{cards.map(([label, value]) => <article key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm text-slate-500">{label}</p><p className="mt-3 text-3xl font-semibold text-slate-900">{value}</p></article>)}</section>
      <section className="grid gap-5 lg:grid-cols-2">
        <article className="rounded-xl border border-slate-200 bg-white p-6"><h3 className="font-semibold">本月采购</h3><div className="mt-5 grid grid-cols-3 gap-4 text-center"><div><p className="text-2xl font-semibold">{data?.monthPurchase?.orderCount ?? "—"}</p><p className="text-xs text-slate-500">订单数</p></div><div><p className="text-2xl font-semibold">{data?.monthPurchase?.completedCount ?? "—"}</p><p className="text-xs text-slate-500">已完成</p></div><div><p className="text-2xl font-semibold">{data?.monthPurchase?.totalAmount ?? "—"}</p><p className="text-xs text-slate-500">采购额</p></div></div></article>
        <article className="rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 p-6 text-white"><h3 className="font-semibold">对话式智能助手</h3><p className="mt-2 text-sm text-blue-100">用自然语言查询供应商、创建采购单或完成库存操作；所有写入继续受 RBAC 与审计约束。</p><Link href="/" className="mt-6 inline-block rounded-lg bg-white px-4 py-2 text-sm font-medium text-blue-700">打开助手</Link></article>
      </section>
      <section className="rounded-xl border border-slate-200 bg-white p-6"><h3 className="font-semibold">采购与库存工作台</h3><p className="mt-1 text-sm text-slate-500">直接处理结构化业务，也可以回到助手用自然语言完成同一套操作。</p><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">{quickLinks.map(([label, href, description]) => <Link key={href} href={href} className="rounded-lg border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50"><p className="text-sm font-medium text-slate-900">{label}</p><p className="mt-2 text-xs leading-5 text-slate-500">{description}</p></Link>)}</div></section>
    </div>
  </ManagementShell></RequireAuth>;
}
