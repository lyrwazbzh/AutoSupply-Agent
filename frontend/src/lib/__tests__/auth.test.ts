import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { login } from "../auth";

describe("login", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("surfaces the server rate-limit message for HTTP 429", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      code: 429,
      message: "登录尝试过于频繁，请稍后再试",
      data: null,
    }), { status: 429, headers: { "Content-Type": "application/json" } }));

    await expect(login("buyer", "password"))
      .rejects.toThrow("登录尝试过于频繁，请稍后再试");
  });
});
