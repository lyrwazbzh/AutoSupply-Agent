import { beforeEach, describe, expect, it, vi } from "vitest";

const { erpJson } = vi.hoisted(() => ({ erpJson: vi.fn() }));
vi.mock("../auth", () => ({ erpJson }));

import { loadCatalogQuickAccess } from "../catalog";

describe("loadCatalogQuickAccess", () => {
  beforeEach(() => erpJson.mockReset());

  it("loads all four per-user quick access lists", async () => {
    erpJson
      .mockResolvedValueOnce([{ id: 1, partCode: "P-1", name: "火花塞" }])
      .mockResolvedValueOnce([{ id: 2, partCode: "P-2", name: "刹车片" }])
      .mockResolvedValueOnce([{ id: 3, supplierCode: "S-1", name: "华东配件" }])
      .mockResolvedValueOnce([{ id: 4, supplierCode: "S-2", name: "北方供应" }]);

    const result = await loadCatalogQuickAccess(8);

    expect(erpJson.mock.calls.map(([path]) => path)).toEqual([
      "/parts/recent?limit=8",
      "/parts/frequent?limit=8",
      "/suppliers/recent?limit=8",
      "/suppliers/frequent?limit=8",
    ]);
    expect(result.recentParts[0].name).toBe("火花塞");
    expect(result.frequentSuppliers[0].name).toBe("北方供应");
  });

  it("does not reuse stale data when one endpoint fails", async () => {
    erpJson
      .mockRejectedValueOnce(new Error("redis unavailable"))
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([]);

    const result = await loadCatalogQuickAccess();

    expect(result.recentParts).toEqual([]);
  });
});
