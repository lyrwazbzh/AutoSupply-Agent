import { ToolCallInfo } from "./types";

export interface ChartPreview {
  title: string;
  url: string;
}

export function extractChartPreviews(
  toolCalls: ToolCallInfo[] | undefined
): ChartPreview[] {
  const previews: ChartPreview[] = [];
  const seen = new Set<string>();

  for (const toolCall of toolCalls ?? []) {
    if (toolCall.name !== "generate_chart" || !toolCall.result) continue;

    const link = toolCall.result.match(/下载链接:\s*(\S+)/)?.[1];
    if (!link) continue;

    let url = link;
    try {
      const parsed = new URL(link);
      // 下载接口与前端同源代理，转成相对地址后也能适配局域网和生产域名。
      if (parsed.pathname.startsWith("/api/download/")) {
        url = `${parsed.pathname}${parsed.search}`;
      }
    } catch {
      // 已经是相对地址时直接使用。
    }

    if (seen.has(url)) continue;
    seen.add(url);
    const title = toolCall.result.match(/标题:\s*(.+)/)?.[1]?.trim();
    previews.push({ title: title || "生成图表", url });
  }

  return previews;
}
