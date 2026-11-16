import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 产出 .next/standalone（自带最小 node_modules），运行镜像不必带完整依赖树。
  output: "standalone",

  // 本地开发时保持与 Nginx 相同的路由边界：ERP 登录与业务 API 走 Java，
  // 对话、历史和评测等其余 /api/* 仍走 Python Backend。
  // 生产（Docker）环境下由 nginx 统一反代，rewrite 必须关闭——否则
  // Next 会把 /api 请求转发到容器内不存在的 localhost:8000。
  async rewrites() {
    if (process.env.NODE_ENV === "development") {
      const erpBaseUrl = process.env.ERP_DEV_BASE_URL || "http://localhost:8080";
      return [
        {
          source: "/api/auth/:path*",
          destination: `${erpBaseUrl}/api/auth/:path*`,
        },
        {
          source: "/api/erp/:path*",
          destination: `${erpBaseUrl}/api/:path*`,
        },
        {
          source: "/api/:path*",
          destination: "http://localhost:8000/api/:path*",
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
