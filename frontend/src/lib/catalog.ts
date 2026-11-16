import { erpJson } from "./auth";

export interface PartQuickItem {
  id: number;
  partCode: string;
  name: string;
  model?: string;
}

export interface SupplierQuickItem {
  id: number;
  supplierCode: string;
  name: string;
  creditRating?: string;
}

export interface CatalogQuickAccess {
  recentParts: PartQuickItem[];
  frequentParts: PartQuickItem[];
  recentSuppliers: SupplierQuickItem[];
  frequentSuppliers: SupplierQuickItem[];
}

const EMPTY: CatalogQuickAccess = {
  recentParts: [],
  frequentParts: [],
  recentSuppliers: [],
  frequentSuppliers: [],
};

export async function loadCatalogQuickAccess(limit = 5): Promise<CatalogQuickAccess> {
  const safeLimit = Math.max(1, Math.min(20, Math.trunc(limit)));
  const paths = [
    `/parts/recent?limit=${safeLimit}`,
    `/parts/frequent?limit=${safeLimit}`,
    `/suppliers/recent?limit=${safeLimit}`,
    `/suppliers/frequent?limit=${safeLimit}`,
  ] as const;
  const results = await Promise.allSettled([
    erpJson<PartQuickItem[]>(paths[0]),
    erpJson<PartQuickItem[]>(paths[1]),
    erpJson<SupplierQuickItem[]>(paths[2]),
    erpJson<SupplierQuickItem[]>(paths[3]),
  ]);
  return {
    recentParts: results[0].status === "fulfilled" ? results[0].value : EMPTY.recentParts,
    frequentParts: results[1].status === "fulfilled" ? results[1].value : EMPTY.frequentParts,
    recentSuppliers: results[2].status === "fulfilled" ? results[2].value : EMPTY.recentSuppliers,
    frequentSuppliers: results[3].status === "fulfilled" ? results[3].value : EMPTY.frequentSuppliers,
  };
}
