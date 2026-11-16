"use client";

import { useEffect, useState } from "react";
import {
  CatalogQuickAccess,
  PartQuickItem,
  SupplierQuickItem,
  loadCatalogQuickAccess,
} from "@/lib/catalog";

const EMPTY: CatalogQuickAccess = {
  recentParts: [],
  frequentParts: [],
  recentSuppliers: [],
  frequentSuppliers: [],
};

interface Props {
  onPromptClick: (prompt: string) => void;
}

export default function QuickAccess({ onPromptClick }: Props) {
  const [data, setData] = useState<CatalogQuickAccess>(EMPTY);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    loadCatalogQuickAccess()
      .then((result) => {
        if (active) setData(result);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="mt-8 text-left" aria-label="快捷访问">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-800">快捷访问</h2>
          <p className="text-xs text-gray-400">根据你的最近访问与使用频率生成</p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <QuickGroup title="最近零件" loading={loading}>
          {data.recentParts.map((item) => (
            <PartButton key={item.id} item={item} onPromptClick={onPromptClick} />
          ))}
        </QuickGroup>
        <QuickGroup title="常用零件" loading={loading}>
          {data.frequentParts.map((item) => (
            <PartButton key={item.id} item={item} onPromptClick={onPromptClick} />
          ))}
        </QuickGroup>
        <QuickGroup title="最近供应商" loading={loading}>
          {data.recentSuppliers.map((item) => (
            <SupplierButton key={item.id} item={item} onPromptClick={onPromptClick} />
          ))}
        </QuickGroup>
        <QuickGroup title="常用供应商" loading={loading}>
          {data.frequentSuppliers.map((item) => (
            <SupplierButton key={item.id} item={item} onPromptClick={onPromptClick} />
          ))}
        </QuickGroup>
      </div>
    </section>
  );
}

function QuickGroup({ title, loading, children }: { title: string; loading: boolean; children: React.ReactNode }) {
  const hasItems = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <div className="min-h-28 rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold text-gray-600">{title}</h3>
      {loading ? (
        <p className="py-5 text-center text-xs text-gray-400">加载中…</p>
      ) : hasItems ? (
        <div className="space-y-1.5">{children}</div>
      ) : (
        <p className="py-5 text-center text-xs text-gray-400">暂无记录</p>
      )}
    </div>
  );
}

function PartButton({ item, onPromptClick }: { item: PartQuickItem; onPromptClick: Props["onPromptClick"] }) {
  return (
    <button
      type="button"
      className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-blue-50"
      onClick={() => onPromptClick(`查询零件“${item.name}”（编码 ${item.partCode}，ID ${item.id}）的详细信息`)}
    >
      <span className="block truncate text-xs font-medium text-gray-700">{item.name}</span>
      <span className="block truncate text-[11px] text-gray-400">{item.partCode}{item.model ? ` · ${item.model}` : ""}</span>
    </button>
  );
}

function SupplierButton({ item, onPromptClick }: { item: SupplierQuickItem; onPromptClick: Props["onPromptClick"] }) {
  return (
    <button
      type="button"
      className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-blue-50"
      onClick={() => onPromptClick(`查询供应商“${item.name}”（编码 ${item.supplierCode}，ID ${item.id}）的详细信息`)}
    >
      <span className="block truncate text-xs font-medium text-gray-700">{item.name}</span>
      <span className="block truncate text-[11px] text-gray-400">{item.supplierCode}{item.creditRating ? ` · ${item.creditRating}级` : ""}</span>
    </button>
  );
}
