import { describe, expect, it } from "vitest";
import { extractChartPreviews } from "../chart-preview";

describe("extractChartPreviews", () => {
  it("从图表工具结果提取同源预览地址", () => {
    const previews = extractChartPreviews([
      {
        id: "chart-1",
        name: "generate_chart",
        args: "{}",
        status: "done",
        result:
          "✅ 图表生成成功!\n标题: 供应商评级\n下载链接: http://localhost:8000/api/download/chart_供应商.png\n",
      },
    ]);

    expect(previews).toEqual([
      {
        title: "供应商评级",
        url: "/api/download/chart_%E4%BE%9B%E5%BA%94%E5%95%86.png",
      },
    ]);
  });

  it("忽略非图表工具并按地址去重", () => {
    const chart = {
      id: "chart-1",
      name: "generate_chart",
      args: "{}",
      status: "done" as const,
      result: "下载链接: /api/download/chart.png",
    };
    expect(
      extractChartPreviews([
        chart,
        { ...chart, id: "chart-2" },
        { ...chart, id: "other", name: "web_search" },
      ])
    ).toEqual([{ title: "生成图表", url: "/api/download/chart.png" }]);
  });
});
