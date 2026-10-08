# AutoSupply Web

AutoSupply Agent 的 Next.js 前端，提供 SSE 流式对话、Harness 阶段展示、工具调用追踪、会话历史，以及 HITL 审批和信息补充交互。

## 本地开发

先按项目根目录 [README](../README.md) 启动 MongoDB、MCP Server 和 FastAPI 后端，再启动前端：

```bash
npm install
npm run dev
```

浏览器访问 [http://localhost:3000](http://localhost:3000)。前端默认连接 `http://localhost:8000/api`。

## 常用命令

```bash
npm run dev
npm run build
npm run start
```
