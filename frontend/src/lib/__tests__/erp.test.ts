import { afterEach, describe, expect, it, vi } from "vitest";
import { buildQuery, money, newOperationId, operationHeaders } from "../erp";

describe("ERP request helpers", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("omits empty filters while preserving zero values", () => {
    expect(buildQuery({ current: 1, keyword: "", status: null, quantity: 0, partId: undefined }))
      .toBe("?current=1&quantity=0");
  });

  it("generates a scoped operation id and matching idempotency headers", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "fixed-uuid" });
    const operationId = newOperationId("ui-order-receive");

    expect(operationId).toBe("ui-order-receive-fixed-uuid");
    expect(operationHeaders(operationId)).toEqual({
      "X-Operation-Id": operationId,
      "Idempotency-Key": operationId,
    });
  });

  it("formats purchase amounts without inventing values", () => {
    expect(money(undefined)).toBe("—");
    expect(money(12.5)).toContain("12.50");
  });
});
