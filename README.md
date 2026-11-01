# ERP 智能采购助手 — Harness Engineering 架构

> 基于 DeepAgent + LangGraph + MCP 协议的摩托车零部件采购智能助手，严格遵循 **Harness Engineering** 架构思想（Planning → Executing → Review → Result）。

- 仓库：<https://github.com/farhub-wq/Agent-Harness>
- 上游：[wodrake/ERP-AGENT-open-source](https://github.com/wodrake/ERP-AGENT-open-source)（本项目在其基础上继续开发，改动范围见下方「相对上游的改动」）

---

## 项目简介

本项目是一个面向摩托车零部件采购管理场景的 **AI Agent 系统**。通过 DeepSeek 模型驱动的智能体，与已部署的 Java ERP 后端进行交互，实现：

- 供应商智能分析（信用评级、供货能力对比）
- 采购订单全生命周期管理（创建/修改/审批）
- 库存预警与出入库管理
- 零部件搜索与供应商关联查询
- 数据可视化图表生成（26 种图表类型）
- 结构化文档输出（Markdown/HTML/CSV/JSON）
- 人工审批流程（HITL — Human-in-the-Loop）

---

## 2026-10-08 更新

LLM 切换至 ChatAnywhere 网关，落地「本地直推生产」的日常发布链路，并修掉沙箱项目上传与 `/api` 容器代理问题。

- **直推发布（日常迭代）**：配置与用法见下文「[直推发布（日常迭代）](#直推发布日常迭代)」。本次补齐该链路的三个文件（**均不入库**，由本地与部署机各持一份）：`scripts/push-prod.ps1` / `scripts/push-prod.sh`（本地入口：断言工作区干净 → ruff + compileall + pytest 快速检查 → push GitHub 保持真相源 → push 服务器裸仓库）、`deploy/cloud/post-receive.hook`（只认 `refs/heads/main`，其余分支与 tag 仅存裸仓库不部署）、`deploy/cd/push-deploy.sh`（编排：构建 clone 里 checkout 刚推的 sha → `build.sh` 构建镜像 → `deploy.sh deploy production` 完整发布链）。三个实现细节值得记：① post-receive 环境里 `GIT_DIR=.` 指向裸仓库，不 `unset` 会劫持所有子进程的 `git -C`——「在构建 clone 里 checkout」变成「在裸仓库上 checkout」，报错很绕；② 直推与换版是**两把锁**：push-deploy 用 `/var/lock` 锁防两次 push 撞同一个构建 clone，换版互斥仍由 `deploy.sh` 自己的锁管；③ `build.sh` 要求版本参数是「本地存在且指向 HEAD」的 tag（它拿 `${VERSION}^` 算上一个 `v*` tag 得变更集），用只在构建 clone 里存在的移动 tag `push-head` 满足它，镜像打 `push-head` 与 `sha-<12>` 双 tag，发布只认不可变的后者。
- **LLM 切换至 ChatAnywhere**：DeepSeek → ChatAnywhere（OpenAI 兼容网关），主对话、grader、联网搜索共用 `CHATANYWHERE_API_KEY`（[config.py](src/agent/config.py)），`.env.example` 与 `deploy/.env.example` 同步换模板变量。顺带修正 [web_search.py](src/agent/tools/web_search.py) 的注释与测试：该工具是**基于 LLM 知识的回答，不是真实联网搜索**，避免能力被误判。
- **沙箱项目上传容错**：启动时 `_upload_project_to_sandbox` 打包项目树，遇到本地数据库遗留目录或被锁文件时跳过并记录 warning，不再让单个不可读文件拖垮整个上传（[main_agent.py](src/agent/main_agent.py)）。
- **`/api` 代理只在开发模式生效**：[next.config.ts](frontend/next.config.ts) 的 `/api → localhost:8000` rewrite 是给 `npm run dev` 用的，但它在 Docker 容器里同样生效——请求被 Next 接住、转发到容器内并不存在的 localhost:8000。改为仅 `NODE_ENV === "development"` 返回 rewrite，生产统一由 nginx 反代。
- **文档脱敏**：README 与 push-prod 脚本注释里的真实服务器 IP 换成 `<部署机IP>` 占位（仓库是 public，规则见「提交前检查」）；`.gitignore` 补上 `.trae/`（IDE 本地目录）与直推脚本（`scripts/`、`deploy/cd/push-deploy.sh`、`deploy/cloud/post-receive.hook`，不入库但本地与部署机各留一份）。

## 2026-10-06 更新

真机定位并修复「整站一登录就 500、/healthz 却 200」，转绿 CI 两个长期失败的集成门禁，走通 v1.0.2 发布全链路。

- **500 根因一：htpasswd 权限 600，worker 读不了**。nginx master(root) 只在加载期读证书；请求期打开 `auth_basic_user_file` 校验口令的是 **worker（nginx uid 101）**。生产 htpasswd 落成 600 root:root 后，每个**带凭据**请求都是 `[crit] open() .../htpasswd (13: Permission denied)` → 500；无凭据请求不打开该文件所以 401 正常、/healthz（auth_basic off）照常 200 —— 探活带不了凭据，健康检查永远发现不了。修复三处：[bootstrap.sh](deploy/cloud/bootstrap.sh) 生成后无条件 `chmod 644`（CI 的 prepare-stack.sh 早已按 644 处理并留过同款教训注释，生产路径漏对齐）；[deploy/cd/lib.sh](deploy/cd/lib.sh) 新增 `cd_ensure_nginx_auth_and_switch`，up 前对老实例幂等修正（正常发布与回滚两路复用）；[nginx.conf](deploy/nginx/nginx.conf) 显式 `user nginx;` 固化 worker 用户，不再依赖镜像编译默认。
- **500 根因二：envsubst 残留 → map 自引用 cycle**。nginx 镜像入口的 envsubst 只替换**已定义**的变量：nginx.env 缺 `TLS_ENABLED=` 行时容器内该变量未定义，`${TLS_ENABLED}` 原样残留进 tls.conf 的 map `default`，被 nginx 当变量引用、与 map 目标 `$tls_enabled` 自引用 → 每个请求 `cycle while evaluating variable "tls_enabled"` → 500。修复：bootstrap **无论开关与否**都显式写该行（值可空）；cd 兜底对缺行的老实例补空值；[tls.conf.template](deploy/nginx/templates/tls.conf.template) 加注释说明这个坑。
- **两个坑都极难排查**：都只在带凭据请求上爆（探活全绿）；`nginx -t` 只静态解析、不求值变量，抓不到 map cycle；隔离容器实验若不做 644 副本，权限错误会掩盖真实结论。因此 [test_static_config.py](src/test/test_static_config.py) 新增 `TestNginxAuthRuntimeFiles` 5 项结构断言在 PR 上秒级拦截（user 位置、chmod 644、恒写 TLS 空行、模板占位、cd 兜底存在且在 up 前调用）。
- **CI 集成栈两个 job 自 TLS 合入起长期红**：「认证与代理链路」「完整拓扑」每轮 PR 都失败——nginx.conf 的 :443 server **无条件**加载 `ssl_certificate /etc/nginx/tls/cert.pem`（该指令在 master 加载配置期解析路径，与开关无关），CI 只跑 [prepare-stack.sh](deploy/ci/prepare-stack.sh)、不跑 bootstrap/deploy，没人生成证书 → nginx 启动即 emerg、容器永久 restarting → 等 healthy 420s/600s 双双超时，**认证与沙箱断言一条都没跑过**。修复：prepare-stack 用与 `cd_ensure_nginx_tls_cert` 同一条 openssl（RSA2048 / 3650 天 / CN=localhost）自签占位——占位证书从此有三条生成路径（装机 / 老实例升级 / CI），静态断言钉死第三条。修复后 ci 八个 job 全绿，沙箱预热池断言（backend→dind 真建出容器）首次真正执行并通过。
- **v1.0.2 发布闭环**：release PR 门禁全绿合并 → tag `v1.0.2` → build workflow（同一份门禁 + 生产自托管 runner 构建镜像成功，产出 `v1.0.2` 与 `sha-<12>` 双 tag）→ 生产切到 v1.0.2，9 服务 healthy，认证矩阵复验通过（无凭据 401 / 错密 401 / healthz 200 / 正确凭据 200）。
- **发布正向冒烟打通**：部署机 `/etc/erp-agent/smoke.env` 的 `SMOKE_BASIC_PASSWORD` 已填（与 htpasswd 一致）。注意 htpasswd 是 apr1 哈希不可逆——装机时「只打印一次」的密码找不回的话，唯一路径是重设 htpasswd（原地截断重写保 inode，避免单文件 bind mount 换 inode 后容器读到旧文件的坑，免重启 nginx）。此后每次发布闸门自动执行认证后冒烟，不再告警「前端与 /api 链路未验证」。

## 2026-10-05 更新

本次补全 CI/CD 链路的最后几块拼图：构建失败通知、恢复演练自动化、箱外告警注册。

- **构建失败通知**：`build.yml` 末尾新增 `if: failure()` 的通知 step。`build.sh` 以 `ghrunner` 身份跑，读不到 root 600 的 `/etc/erp-agent/notify.env`，之前构建失败只在 Actions 页面可见。现在 webhook URL 从仓库 Secret `BUILD_NOTIFY_WEBHOOK` 注入（与 `RELEASE_PLEASE_TOKEN` 同级管理），不经过提权面、不读 root 文件。通知格式复用 `notify.sh` 的飞书/企微/钉钉 JSON payload 形状，按 URL host 自动选通道。`success` / `cancelled()` 不通知（避免噪声）。
- **恢复演练月度 timer**：新增 `deploy/monitor/erp-agent-drill.service` + `erp-agent-drill.timer`，每月 1 号 03:47 自动跑 `restore-drill.sh`。`install-monitor.sh` 一并安装。`Persistent=true` 避免漏跑，`TimeoutStartSec=7200`（2 小时），脚本自身跳过发布期（`cd_deploy_in_flight`）不与发布抢内存。之前这段是「先在真机上跑一次看耗时再决定频率」，现在按月频落地——备份保留 7 天，月频足够验证恢复链路。
- **箱外告警已注册**：阿里云云监控站点监控（探 `/healthz`，每 1 分钟，5 分钟无响应告警）与 healthchecks.io 死信 ping 均已在控制台注册，`HEARTBEAT_URL` 已填入 `notify.env`。机内巡检与箱外死信两条链路都通。
- **tag 前缀修复**：`release-please-config.json` 配了 `include-component-in-tag: false`，打出的 tag 是 `vX.Y.Z` 而非 `erp-agent-vX.Y.Z`，与 `build.yml` 的 `v[0-9]*.[0-9]*.[0-9]*` 触发条件匹配。

> 尚未实现：可观测（阶段 6），不在这次范围内。

## 2026-10-03 更新（阶段 5）

发布前的数据库关卡与机内巡检已落地，见 [deploy/dr/](deploy/dr/) 与 [deploy/monitor/](deploy/monitor/)。

- **数据库备份**：统一对 PostgreSQL 执行 custom-format dump、恢复结构校验、备份剪枝和异地归档；临时 Artifact 由 TTL 自动清理，不进入灾备。
- **自检是硬门槛**：把 dump 恢复进一次性 PostgreSQL，检查应用表、写审计表和备份清单。没过的备份不算备份，发布中止。
- **迁移**：只前进、无 down 迁移，按 sha256 记账（内容变了就停住）。跑在「备份之后、同步之前」，所以失败时生产一个字节都没动过 —— 退出码 **8**。
- **机内巡检**：每 10 分钟跑一次 `status.sh`，把结果压成 `(id, OK/FAIL)` 对与上一次比，**只在状态变迁时通知**（一天 144 次的提醒等于没有提醒，几天后就会被静音，而一套被静音的通知比没有通知更糟）。外加每日心跳与箱外死信 ping —— 那是「巡检 timer 被偷偷停掉」唯一能被发现的方式。

## 2026-10-02 更新

本次补上「发布与回滚」，并修掉一个会挡住前端镜像构建的错误。

- **发布 / 回滚工具**：新增 [deploy/cd/](deploy/cd/)（`deploy.sh` / `build.sh` / `status.sh` / `lib.sh` / `notify.sh` / `shadow_probe.py` / `package.filter`）。同步源码树走 `git archive <sha>` + `rsync --delete --filter`，取源是一个**裸镜像仓库**，所以既不依赖 GitHub 可达、也不依赖工作区干净——物理上只可能同步已提交的内容。回滚**同时还原镜像和源码树**（宿主源码树是部署产物的一部分，见下条），`state/production.env` 是「这台机器现在跑的是哪一版」的唯一真值源，记的是 **digest 而不是 tag**（tag 可以被重新指向，digest 不能）。
- **为什么回滚必须连源码树一起回**：四个 bind mount 把宿主文件直接喂进容器——`src/skills` → backend、`deploy/nginx/**` → nginx、`deploy/dind-daemon.json` → dind。只回滚镜像会让线上变成「镜像旧、配置新」。推论：`docker compose up -d` **不会**因为 bind 文件的内容变了而重建容器，改了 `deploy/nginx/**` 就必须显式 `--force-recreate nginx`（脚本用哈希比对自动做这件事）。
- **退出码语义**（CI 靠它区分处置方式）：`0` 成功 / `1` 前置失败 / `2` 备份失败 / `3` 同步失败 / `4` 影子启动失败 / `8` **迁移失败** —— 前四种加上 8，生产**完全没动过**；`5` 换版失败已回滚 / `6` 观察窗失败已回滚 / `7` **回滚也失败，需要人工介入**。注意**回滚成功是 5 不是 0**：回滚不算发布成功。8 是刻意新开的而不是并进 2：两者都「生产完全没动过」，但 2 的通知文案是「备份失败——多半是磁盘空间」，把迁移失败报成这个会把运维指到完全错误的方向。
- **真机实测的停机窗口**：正常换版 **44s**、坏版本自动回滚 **134s**（其中约 100s 是 compose 自己探测 `depends_on` 健康条件失败）、镜像没换时的同版本重发布只要 **4s**。`backend` 必须单副本（沙箱注册表与会话是进程内状态），所以每次换版必然停机，SSE 实断约 20s。
- **两条不能碰的死线**（写在 `lib.sh` 的 `cd_compose()` 里，是代码而不是注释）：`docker compose down` 会重建网络，破坏 `mcp-sandbox` 静态 IP 与沙箱内 `/etc/hosts` 的一致性，沙箱内所有 MCP 工具挂掉；`docker compose prune` / `rm` 会删掉未被运行容器引用的镜像，也就是**全部历史版本**，回滚能力瞬间归零且不可逆。同理，**永远不要在部署机上跑 `docker system prune -a`**。
- **修复前端镜像的构建阻塞**：`frontend/Dockerfile` 的 `COPY --from=build /app/public ./public` 在源路径不存在时会**直接让构建失败**（不是跳过、不是警告）。上一条 `Delete frontend/public directory` 把 `create-next-app` 的 5 个占位 svg 删掉、整个目录随之消失后，前端镜像就再也构建不出来。加一个 `RUN mkdir -p public` 兜住，仓库里有没有 `public/` 都能构建。

### CI 门禁：8 个 job，PR 上必过

`.github/workflows/ci.yml` 调 `_gates.yml`（可复用工作流——发布流水线调的是**同一份**，保证「PR 上验过的」和「发布时验的」是同一套判据）。**只监听 `pull_request`**：光推分支不触发任何检查，必须开 PR。

| job | 管什么 |
|------|--------|
| workflow 守卫 | PR 可达的 workflow 文件里不得出现自托管 runner 的标签（沿着 `uses:` 查传递闭包，不靠自觉）。唯一一条「做错了会丢机器」的规则，所以排在最前面 |
| 密钥扫描 | `deploy/cd/leak-check.sh --tree`（路径级）+ gitleaks（内容级，**扫全历史**） |
| Python 测试与 lint | ruff、`compileall`、6 条离线回归、pytest + 覆盖率**地板 36%**（真的会阻断） |
| 前端类型 / lint / 测试 / 构建 | typecheck、ESLint（只拦 error）、单测、镜像构建 + 「bundle 里没有硬编码后端地址」断言 |
| 后端镜像构建 | 顺带实测 Dockerfile 的 `PIP_INDEX_URL` ARG 挂点确实可用 |
| 备份恢复与迁移自检 | 三段纯逻辑桩测（不需要 Docker）+ **真跑**一遍 dump → 恢复自检 → 负向用例 → 保留策略，以及迁移的幂等与「内容被改 / 编号撞车」用例。护住的是最贵的东西，而且是这批里最便宜的一个 job |
| 集成栈（认证与代理链路） | **真起一套栈**（dind 与 loader 换 alpine 替身），13 条断言压认证边界、nginx→backend 共享密钥链路，以及绕过 nginx 直连后端的越权尝试 |
| 集成栈（完整拓扑，含沙箱链路） | 一个服务都不换，含 privileged 真 dind：验证 compose 起栈顺序、沙箱基础镜像灌入、backend 真的建出预热容器 |

后两个 job 存在的理由：**静态检查看得见「文件里有什么」，看不见「连起来能不能用」**。它们是拿一个真实的坏版本验收过的——把 `nginx.conf` 里 `/api/` 的 `set $backend http://backend:8000;` 改成 `:9999`：语法正确、`set` 在、`proxy_pass` 在、所有 `proxy_set_header` 都在原位，静态断言一条不红，而 **7 个 job 里只有「认证与代理链路」变红**（三条断言拿到 502，诊断日志直接打出 `upstream "http://<容器 IP>:9999/api/history"`）。

两条容易误判的：在上面那个坏版本下 `/healthz` 与 `/health` **仍然返回 200**（它们各自有自己的 `set`）——**探活全绿不足以说明代理链路是好的**；完整拓扑那个 job 也只探不经 `/api/` 的 `/healthz`，**它的绿同样不代表代理没事**。

断言全部写在 [deploy/ci/](deploy/ci/) 的脚本里而不是 YAML 的 `run:` 块里，所以每一步都能在本地命令行重跑（这也是能快速定位问题的原因——详见 [deploy/ci/README.md](deploy/ci/README.md)）。

### 发布流水线：版本 → 构建 → 审批 → 备份 → 迁移 → 影子 → 换版 → 观察窗

四个 workflow，**按触发点分工**而不是按功能分工，因为触发点就是安全边界：

| workflow | 触发点 | 干什么 |
|---|---|---|
| `release-please.yml` | `push: main` | conventional commits → 开一个 `chore(main): release X.Y.Z` 的 PR；合并后打 `vX.Y.Z` tag |
| `build.yml` | `v*` tag / 手工 | 先过 `_gates.yml`（同一份门禁），在**目标机本地**构建三个镜像，打 `sha-<12>` 与 `vX.Y.Z` 两个 tag |
| `deploy.yml` | **只有手工** | 经 `production` 环境**人工审批**后，调提权闸门换版：影子启动 → 换版 → 观察窗 → 通知 |
| `ci.yml` | `pull_request` | 上面那套门禁 |

三件必须说清楚的事：

- **没有镜像仓库。** 构建机就是运行机，镜像不推任何 registry，也就没有"推上去再拉下来"这条链路上的一切失败模式。代价是构建只能在这台机器上做（2 核），所以 `build.sh` 会按改动路径跳过没必要重建的镜像。
- **自托管 runner 只跑 push/tag 触发的 workflow。** 它装在生产机上、在 docker 组里（= 事实上的 root）。仓库是 public，fork PR 能改 workflow 文件的内容，所以「PR 门禁一律跑 GitHub 托管 runner」不是优化建议，它就是安全模型本身——由 `deploy/ci/lint-workflows.sh` 强制（沿 `uses:` 查传递闭包），由 PR 门禁自己运行。
- **换版前的影子启动是"生产一秒都不停"的那一层。** 用新镜像起一个一次性容器（同网络同环境变量），验 `/health`、MCP 可达、`/api` 带令牌 200 而**去掉令牌 401**、以及一次真实 LLM 调用。它刻意不接 sandbox 网络、不挂 docker socket——否则它启动时的 `prune_orphans()` 会清空生产的沙箱预热池，自己把自己变成一次故障。

失败处置由退出码决定（`0` 成功 / `1`–`4` 与 `8` **生产完全没动过** / `5`、`6` 已自动回滚 / `7` 回滚也失败需要人上机），`deploy.yml` 会把每个码翻译成一句处置建议。装 runner、提权设计、回滚能力巡检见 [deploy/runner/README.md](deploy/runner/README.md)；备份、迁移、恢复演练与巡检见 [deploy/dr/README.md](deploy/dr/README.md)。

## 2026-09-26 更新

本次把整个栈容器化（一条 `docker compose up -d` 起全栈），并修掉沙箱加固暴露出来的一批真问题。

- **整栈容器编排**：新增 `Dockerfile`、`docker-compose.yml`、[deploy/](deploy/)。nginx 做统一入口 `:80`，后端 / 前端 / PostgreSQL / MCP / mock ERP 全部由 compose 管；沙箱改用 **`docker:dind` sidecar**，backend 通过 `DOCKER_HOST=tcp://dind:2375` 驱动它。部署、运维、排错见 [deploy/README.md](deploy/README.md)。
- **一键云部署**：新增 [deploy/cloud/](deploy/cloud/)，`pack.sh` 本机打包 → `bootstrap.sh` 在全新云主机上装 Docker、配镜像加速、建 swap、生成配置、构建、起服务并等 healthy。**只能是真虚拟机**，dind 需要 privileged，免费 PaaS 全部会在创建 dind 那步失败。
- **认证与多用户隔离**：新增 `src/api_view/auth.py`。整个服务在 nginx 的 HTTP Basic Auth 后面，backend 用 nginx 注入的 `X-Authenticated-User` 派生 `user_id`，并丢弃请求体/查询串里客户端自带的 `user_id`。改造前 `user_id` 是前端硬编码的 `user-001`，所有浏览器共享同一份历史和同一个沙箱，且会话读写删接口不校验归属。
- **挡住沙箱伪造身份**：沙箱容器跑在 dind 里、与 backend 同处一张 Docker 网络，因此沙箱中模型生成的代码可以绕过 nginx 直连 backend 冒充任意用户。修法是 nginx ↔ backend 共享密钥 `INTERNAL_AUTH_TOKEN`（`deploy/set_internal_token.sh` 一次写入两处，backend 用 `secrets.compare_digest` 校验）。留空 = 不校验，启动时打 WARNING。
- **沙箱加固的三个真坑**（都是"加固配置本身没生效"导致长期没被发现，详见 `src/agent/backends/` 里的注释）：① 该 daemon 上容器内 tmpfs 被强制挂成 `noexec`，依赖目录必须挂匿名 volume，否则 numpy 的 `.so` 装得进去、import 就炸；② `seccomp.json` 原先缺 `arch_prctl`，且旧代码把**路径**传给了 `seccomp=` 参数，daemon 解析失败后静默降级 basic 模式 —— 这个白名单从来没真正生效过；③ 只读 rootfs 下 Docker daemon 的 archive 接口拒绝往任何 tmpfs 写（报 `container rootfs is marked read-only`），而 bootstrap 原本是"tar 传到 `/tmp` 再解开"，所以在加固沙箱上这步从来没成功过，宿主进程上只是静默降级成 LocalShell。解法是新增 `SANDBOX_TRANSFER_DIR`（挂匿名 volume）当上传落地点。
- **grader 终于能看到工具调用**：SDK 只把最近 30 条消息交给 grader，而一次任务轻松 30+ 次工具调用，开头的 ERP 查询被挤出窗口后会被判成"无工具证据、疑似编造"。新增 `src/agent/middlewares/grader_transcript.py`，在窗口截断**之前**把原始需求和全量工具调用台账写进去。
- **自建 mock ERP**：上游开源版只有 Agent 侧，MCP 的 23 个工具指向的 Java ERP 后端**没有开源**。新增 [deploy/mock-erp/](deploy/mock-erp/) —— 一个 FastAPI 替身，同样返回 `{code,message,data}` 信封，种子数据固定（`random.Random(42)`），让项目能独立跑起来。
- **其它修复**：`prune_orphans` 不再误删用户沙箱容器；>73KB 的沙箱文件下载不再被截断（改走 `exec_run` 直跑 `base64 -w0`）；tmpfs 总量按 `mem_limit` 等比缩放，避免 OOM 而不是干净的 ENOSPC；docker 客户端 socket 超时提到 `DOCKER_TIMEOUT_SECONDS`（默认 1200s）并先于容器内 `timeout(1)` 触发。

> **密钥管理**：`.env`、`deploy/.env`、`deploy/nginx.env`、`deploy/nginx/htpasswd` 一律在 `.gitignore` 里，仓库只保留 `*.example` 模板。这些文件里的值请填成你自己的，不要把真实密码/Key 提交上来。

## 2026-09-19 更新

本次发布混合式按需审查，并完善本地前端启动兼容性。

- **规则与模型协同路由**：明确的简单请求直接跳过 Grader，明确业务请求由规则触发；模糊请求结合最近对话、计划和待办，调用模型返回结构化审查决定。路由关闭思考、限制输出和等待时间，超时或无效结果保守进入审查。
- **执行信号升级审查**：在 Grader 运行前检查本轮工具记录，根据工具错误、多工具或多来源调用、写操作及子 Agent 委派等信号升级审查，并保存决策来源和原因。
- **防止评审驱动的重复执行**：调用写入、执行类工具或委派子任务后采用单轮评审，失败不自动重放整轮任务；只读任务保留有限次修改重审，订单写操作继续受双层 HITL 约束。
- **输出与配置**：内部路由模型内容不进入用户回答流；统一采用规则优先、LLM 兜底的 Hybrid 路由，`review.mode` 支持 `auto/always/never`，任务检查项不再一律要求图表或报告。
- **前端兼容与启动说明**：兼容浏览器扩展在根 HTML 上注入属性引发的 hydration 警告；补充 Turbopack 对跨项目 `node_modules` 软链接的限制及在前端目录安装本地依赖的说明。
- **验证**：混合审查的 17 项回归测试通过，覆盖路由、异常降级、执行升级、状态清理与写操作防重放。

配置及工作原理见下方“混合审查路由”，本机启动步骤见 [WSL_START.md](WSL_START.md)。

## 2026-09-17 更新

本次新增三层记忆并修复其主链路集成问题，保留原有按需 Grader、用户级沙箱、Skills 恢复及双层 HITL 能力。

- **三层记忆**：HOT 使用会话状态与 checkpoint；WARM 在每次请求或 HITL resume 时读取一次当前用户的偏好和近期情节摘要，并在本次执行中复用；COLD 由 `read_memory` 按需检索。新增 `remember` 显式写入工具。
- **记忆治理**：统一 `MemoryKeeper` 管理语义、情节、程序记忆，支持偏好合并、版本失效标记、TTL 清理和数量淘汰。统一入口不等同于数据库事务或分布式并发保证。
- **任务级情节归档**：Harness 为每个新用户任务生成稳定 `task_id`，审批恢复和评审返工沿用同一 ID；Episodic 以 `thread_id + task_id` 幂等归档，同一会话的多个采购任务互不覆盖。
- **修复记忆不刷新**：新增 `WarmMemoryMiddleware`，即使 Agent Session 已缓存也会刷新记忆，单次注入摘要最多 4000 字符（不是 token）。异步调用通过线程执行同步 Store 读取。
- **修复配置及抽取**：加载 `.env` 中的记忆配置，接通可选 LLM 抽取与规则回退；默认仍关闭额外模型抽取。只处理最新用户轮次，并跳过规则能识别的否定、明确临时表达，减少旧消息反复覆盖偏好。
- **其他兼容修复**：子 Agent 工具匹配改为精确优先、下划线前缀其次、子串兜底，未匹配时告警。子串兜底仍有权限误匹配风险。
- **验证**：36 项记忆基础测试和 8 项真实 LangGraph 离线集成测试通过。

本机 WSL 启动与回退见 [WSL_START.md](WSL_START.md)。修复前标签为 `memory-before-fixes-20260917`，核心修复标签为 `memory-fixed-20260917`；文档更新可能晚于该标签。版本回退不回滚数据库内容，旧 `ep_unknown` 已覆盖的数据也不会自动恢复。

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **LLM** | ChatAnywhere (gpt-4o-mini) | OpenAI 兼容网关，对话、grader、联网搜索共用 |
| **Agent 框架** | DeepAgent + LangGraph | 状态图引擎，支持中断/恢复/子Agent |
| **MCP 协议** | FastMCP + SSE | Agent ↔ ERP 的工具桥接层 |
| **Web 框架** | FastAPI + Uvicorn | SSE 流式响应 |
| **前端** | Next.js 16 + React 19 + TailwindCSS 4 | 流式对话 UI + 中断交互 |
| **数据库** | PostgreSQL + pgvector + zhparser | Checkpoint、Store、业务数据、向量与全文检索 |
| **沙箱** | Docker SDK + 7 层安全防护 | 隔离代码执行环境 |
| **图表** | Matplotlib + Pandas | 26 种图表生成 |
| **语言** | Python 3.11+ / TypeScript | 后端 Python，前端 TypeScript |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js :3000)                       │
│              SSE 流式对话 + HITL 中断交互 + 历史管理              │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────┐
│              Backend API (FastAPI :8000)                          │
│   chat.py (SSE流) + history.py (会话CRUD) + agent_loader.py      │
│   PostgresStore + AsyncPostgresSaver（生产级持久化）              │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Agent Core (DeepAgent)                               │
│  ┌──────────┐ ┌───────────────┐ ┌─────────────┐ ┌────────────┐ │
│  │ LLM      │ │ Composite     │ │ 中间件栈     │ │ 2 子Agent  │ │
│  │ DeepSeek │ │ Backend       │ │ (自定义 +    │ │ analyst    │ │
│  │          │ │ (Docker+Store)│ │ 框架内置)    │ │ order      │ │
│  └──────────┘ └───────────────┘ └─────────────┘ └────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Tools: 23 MCP + 12 Custom = 35 个显式工具（默认）             ││
│  │ chart(26种) + web_search + web_fetch + install_skill         ││
│  │ + hitl_tools + download_sandbox_file + document_generator    ││
│  └─────────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────────┘
                             │ MCP (SSE)
┌────────────────────────────▼────────────────────────────────────┐
│              MCP Server (FastMCP :9000)                           │
│   suppliers(5) + parts(5) + orders(7) + inventory(6) = 23 tools │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST
┌────────────────────────────▼────────────────────────────────────┐
│              Java ERP 后端 (:8081)                                │
│              http://localhost:8081（可替换为你的 ERP 地址）         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心功能

### 1. Harness 工作流（Planning → Executing → Review → Result）
Agent 严格遵循四阶段工作流：
- **Planning**：分析用户意图，生成任务规划（前端展示 TodoList）
- **Executing**：调用 MCP 工具 / 沙箱执行代码 / 委派子Agent
- **Review**：按需审查执行结果，验证数据完整性（问候、感谢和纯概念问答默认跳过 grader；查询、分析、下单等业务任务自动启用）
- **Result**：结构化输出最终结果

审查策略配置在 `src/agent/harness_config.yaml`。`review.mode` 支持 `auto`（默认）、`always` 和 `never`；`auto` 只有一个统一入口：确定性规则先返回 `review/skip/uncertain`，仅 `uncertain` 调用 Router LLM。

#### 混合审查路由

- `ReviewPolicy` 是唯一的评审路由入口：只判断是否需要审查、评审范围和固定检查项，不负责业务意图或工具/子 Agent 分流。明确问候、单一概念定义且没有待办任务时直接跳过；高风险、缺料、明确复核和业务处理由规则触发。
- 模糊请求使用独立 DeepSeek 路由调用，输入最近 6 条截断消息及计划、待办摘要，输出 `skip/review/uncertain`、任务类型、简短理由和受限检查项。与主对话共用现有 Key，关闭思考，最多输出 400 token，不自动重试；异步总等待默认 8 秒，HTTP 请求也设置超时。
- 每次图调用只在入口路由一次，不因 Grader 重做重复路由；超时、格式不合法或 uncertain 保守进入评审。此调用有额外成本，不计入主 Agent 的 ModelCallLimit，单独以次数、超时及输出上限约束。
- 执行结束、Grader 运行前再次检查本轮工具记录：工具错误、多工具/多来源调用、写操作与子任务委派可以升级原先的免审决定。当前是保守信号规则，不宣称能够自动识别所有事实冲突。
- 固定业务底线不可由路由模型改写，模型只选择预定义的计算、来源、约束、比较、产物检查项。图表和完整报告不再作为所有分析任务的强制交付物。
- 调用写入、执行类工具，或委派可能隐藏写操作的子任务后，只进行单轮 Grader 评审，失败不自动重放整轮任务。只读任务保留有限次修改重审。这是评审循环防重放，不代替业务幂等和执行前 HITL。
- `never` 明确关闭自动评审（执行信号也不升级），但不关闭 HITL；调用方显式传入 rubric 时保留其评审标准。
- `review_decision` 保存判断来源和升级信号，写入 Harness trace；内部路由模型输出不作为前端回答流发送。

修改配置后重启后端。Rules 不再是独立模式，而是 Hybrid 内部的第一层；执行信号升级仍保留。

```bash
python -m unittest src.test.test_hybrid_review -v
```

17 项回归测试覆盖模型路由、超时降级、执行升级、跨轮状态清理、HITL 恢复、写操作防重放和只读任务有限重审。

### 2. Docker 安全沙箱（7 层防护）
```
1. --read-only          文件系统只读
2. --tmpfs /tmp         临时目录内存挂载（限制大小）
3. --memory="512m"      内存上限
4. --cpus="1.0"         CPU 上限
5. --network bridge     网络隔离/受限
6. --cap-drop ALL       移除所有 Linux Capability
7. --security-opt       seccomp 系统调用白名单
```
支持可扩展多语言运行时：Python / Go / Node.js

### 3. 沙箱五态生命周期管理
```
预热池(WARM) → 认领(CLAIMED) → PostgreSQL租约(CACHED)
     ↑                              │
     │ 补充预热                      │ 故障/超时
     │                              ↓
  新建(CREATE) ←────────────── 销毁(DESTROY)
```

### 4. HITL 人工审批
- 订单创建/更新触发 `interrupt_on` 中断
- 前端展示审批卡片，用户批准后恢复执行
- 缺少字段时触发信息补充中断

### 5. 子Agent 委派
- **procurement-analyst**：采购分析师（数据分析 + 图表生成）
- **procurement-order**：订单专家（订单 CRUD + 审批流程）

### 6. 项目显式注册的中间件栈
| # | 中间件 | 职责 |
|---|--------|------|
| 1 | SandboxHealthMiddleware | 沙箱健康检查 + 自动重连 |
| 2 | HarnessPhaseMiddleware | 阶段状态机 + 规则与模型混合路由 |
| 3 | ContextInjectionMiddleware | 用户上下文注入（工厂模式隔离） |
| 3.5 | WarmMemoryMiddleware | 每次请求或 HITL resume 加载一次用户记忆，摘要上限 4000 字符 |
| 4 | SkillsSyncMiddleware | 技能文件夹级增量同步 |
| 5 | UserSkillsRestoreMiddleware | 用户自定义技能恢复 |
| 6 | ToolsSummarizationMiddleware | 工具调用摘要监控 |
| 7 | MemoryUpdateMiddleware | 用户偏好自动提取与合并（WARM 层） |
| 8 | MemoryConsolidationMiddleware | 情节归档 + 遗忘扫描（COLD 层） |
| 9 | SandboxCircuitBreakerMiddleware | 沙箱熔断器（三态模型） |
| 10 | SafeRubricMiddleware | 基于框架 RubricMiddleware 审查；写操作后禁止自动重放 |
| 10.5 | ReviewExecutionGate | 根据本轮工具记录升级评审，after_agent 逆序下先于 Grader 执行 |
| 11 | ModelCallLimitMiddleware | 模型调用次数限制 |
| 12 | ToolCallLimitMiddleware | 工具调用次数限制 |

### 7. 显式注册工具
- **23 个 MCP 工具**：供应商(5) + 零部件(5) + 订单(7) + 库存(6)
- **10 个自定义工具**：chart_generator, web_search, web_fetch, install_skill, list_user_skills, request_order_info, download_sandbox_file, list_sandbox_files, generate_document, generate_table_report
- **2 个记忆工具**：`read_memory`、`remember`；`MEMORY_TOOLS_ENABLED=false` 时不注册。

以上不包含 DeepAgents 自动提供的文件、执行、规划和委派工具，实际可用工具还取决于 MCP 连接与框架配置。

---

## 三层记忆架构（HOT / WARM / COLD）

三层按访问方式与上下文用途划分，不是三个独立数据库，也不是严格的缓存逐级淘汰协议：

| 层 | 内容 | 介质 | 体积目标 | 策略 |
|---|---|---|---|---|
| **HOT** | 当前会话消息、工具结果、活跃 todo | LangGraph 状态及 PostgreSQL Checkpointer | 由框架管理 | checkpoint 用于恢复；归档不会自动删除原消息 |
| **WARM** | 有效语义记忆、近 7 天情节摘要（默认最多 5 条） | PostgreSQL Store 中的记录，请求级注入 system prompt | 摘要最多 4000 字符 | 新请求或 HITL resume 加载一次，本次模型调用与委派共同复用 |
| **COLD** | 持久化历史情节、程序记忆等 | PostgreSQL Store，按需检索 | 情节默认最多 200 条，保留 90 天 | PostgreSQL 关键词与 pgvector 召回，经 RRF 和有限辅助加权后返回 top-k |

### 记忆类型

记忆内容按用途分为三类：

- **语义记忆 semantic**：用户偏好等稳定事实；同一 key 的新值会使旧值失效，并保留有限历史。
- **情节记忆 episodic**：每个业务任务按 `ep_<thread_id>_<task_id>` 幂等归档；默认 90 天后清理，近 7 天进入 WARM。
- **程序记忆 procedural**：经验与流程，按需检索，不自动注入全部内容。

`MemoryItem` 的 `source` 保存 `thread_id`、`task_id` 和 `task_type`，`idempotency_key` 标识幂等写入。
工厂、车型、计算 ID、零件、供应商、订单和 operation ID 不重复抽取，直接保留在真实工具参数或结果中。
任务级 Episodic 的 `goal`、`outcome`、`tool_results`
是直接字段，其中工具参数、执行状态和返回结果来自真实 `ToolMessage`，状态不从最终回答推断。

### 命名空间规范

```
("memories", <user_id>, "semantic")     用户级稳定事实
("memories", <user_id>, "episodic")     用户级情节归档
("memories", <user_id>, "procedural")   用户级经验/流程
("memories", "org",     "policies")     预留组织策略命名空间，未接入主链路
("user-preferences", <user_id>)          WARM 投影（偏好字典缓存，供提示词注入）
```

`user-preferences` 是兼容投影，不是另一套记忆本体。动态 WARM 注入以三类记忆本体为准。

### 关键实现

| 文件 | 职责 |
|---|---|
| `src/agent/memory/types.py` | 记忆条目模型（版本、溯源、访问统计和生命周期） |
| `src/agent/memory/keeper.py` | 唯一读写入口：合并、冲突失效、检索、归档和遗忘 |
| `src/agent/memory/postgres_search.py` | COLD 的 PostgreSQL 关键词、pgvector、RRF 与访问统计 |
| `src/agent/memory/scoring.py` | 时间、频次辅助评分及非 PostgreSQL Store 的 BM25 回退 |
| `src/agent/memory/extractor.py` | 偏好抽取与情节摘要（默认零 LLM 调用） |
| `src/agent/middlewares/memory_update.py` | WARM 层偏好写入 |
| `src/agent/middlewares/memory_consolidation.py` | 情节归档 + 遗忘扫描（按间隔节流） |
| `src/agent/middlewares/warm_memory.py` | 动态加载 WARM 摘要及长度限制 |
| `src/agent/tools/memory_tools.py` | `read_memory` / `remember`，COLD 层按需取用 |

记忆读写集中在 `MemoryKeeper`。情节归档采用规则截取，遗忘由执行结束时的中间件按节流规则触发，
不是独立后台任务；当前按用户命名空间隔离，没有额外建立采购领域的第二套记忆模型。

### 验证

```bash
python -m src.test.test_memory_layer
python -m unittest src.test.test_memory_integration -v
```

两套测试覆盖记忆条目、用户隔离、偏好冲突失效、情节幂等归档、WARM 注入、COLD 检索和失败降级。

---

## 项目结构

```
ERP-AGENT/
├── frontend/                          # Next.js 前端
│   ├── src/
│   │   ├── app/                       # App Router
│   │   ├── components/                # UI 组件
│   │   │   ├── chat/                  # 对话区（消息/输入/工具调用/思考动画）
│   │   │   ├── interrupt/             # HITL 中断交互（审批/补充信息）
│   │   │   ├── sidebar/              # 侧边栏（历史/搜索）
│   │   │   └── common/               # 通用组件
│   │   ├── hooks/                     # useChat / useSSE / useHistory
│   │   └── lib/                       # API / SSE解析 / 类型定义
│   └── package.json
│
├── src/                               # Python 后端
│   ├── agent/                         # Agent 核心
│   │   ├── main_agent.py              # 主入口：create_main_agent() 7步组装
│   │   ├── config.py                  # 全局配置
│   │   ├── middleware_config.py       # 子Agent中间件工厂
│   │   ├── backends/                  # Docker 沙箱后端
│   │   │   ├── docker_client.py       # daemon 连接与超时（dind / 本机 socket）
│   │   │   ├── custom_opensandbox.py  # Docker SDK 封装（30+ 方法）
│   │   │   ├── sandbox_setup.py       # 安全沙箱创建 + 多语言运行时
│   │   │   ├── sandbox_manager.py     # 五态生命周期管理
│   │   │   ├── sandbox_proxy.py       # 代理层（热替换）
│   │   │   └── seccomp.json           # seccomp 安全策略
│   │   ├── middlewares/               # 自定义中间件
│   │   │   └── grader_transcript.py   # 把全量工具调用台账喂给 grader
│   │   ├── tools/                     # 基础自定义工具
│   │   │   ├── document_generator.py  # 文档生成（MD/HTML/CSV/JSON）
│   │   │   ├── download_sandbox_file.py # 沙箱文件下载
│   │   │   ├── chart_generator.py     # 26 种图表
│   │   │   ├── web_fetch.py           # URL抓取 + Skill安装
│   │   │   └── hitl_tools.py          # HITL 人工介入
│   │   ├── subagents/                 # 子Agent（YAML声明式）
│   │   └── memory/                    # semantic / episodic / procedural 三类记忆
│   │       ├── types.py               #   记忆条目模型
│   │       ├── keeper.py              #   统一读写、合并、检索和遗忘
│   │       ├── postgres_search.py      #   PostgreSQL 关键词 + pgvector + RRF
│   │       ├── scoring.py             #   时间/频次评分与轻量回退
│   │       ├── extractor.py           #   偏好抽取与情节摘要
│   │       └── namespaces.py          #   用户与组织命名空间
│   ├── api_view/                      # FastAPI Web 层
│   │   ├── web_main.py                # 应用入口
│   │   ├── auth.py                    # Basic Auth 用户解析 + 共享密钥校验
│   │   ├── agent_loader.py            # 用户 Agent 会话与 PostgreSQL 资源
│   │   └── api/                       # 路由（chat + history）
│   ├── mcp_server/                    # MCP 网关（23个ERP工具）
│   ├── skills/                        # 技能文件（文件夹级）
├── .runtime/artifacts/                # 用户隔离的临时生成文件（TTL 清理）
│
├── deploy/                            # 容器化部署
│   ├── README.md                      # 架构 / 运维 / 排错（认证、沙箱网络都在这）
│   ├── .env.example                   # 容器部署配置模板（复制为 deploy/.env）
│   ├── nginx.env.example              # nginx↔backend 共享密钥模板（同理不入库）
│   ├── set_internal_token.sh          # 一次写入 deploy/.env 与 deploy/nginx.env
│   ├── nginx/                         # nginx.conf + 注入共享密钥的模板
│   ├── mock-erp/                      # 自建 FastAPI 替身（上游的 Java ERP 未开源）
│   ├── cd/                            # 发布与回滚（deploy.sh / status.sh / lib.sh）
│   └── cloud/                         # 整机一键部署（pack.sh + bootstrap.sh）
│
├── Dockerfile                         # 后端镜像
├── docker-compose.yml                 # nginx/backend/frontend/postgres/mcp/mock-erp/dind
├── .dockerignore
├── .env.example                       # 环境变量模板（复制为 .env）
├── requirements.txt                   # Python 依赖
├── WSL_START.md                       # WSL 本机启动说明
└── README.md                          # 项目说明与启动指南
```

---

## 相对上游的改动

本仓库 fork 自 [wodrake/ERP-AGENT-open-source](https://github.com/wodrake/ERP-AGENT-open-source)，在其基础上补齐了「能真正部署出去」所需的全部部分：

| 方向 | 上游 | 本仓库 |
|------|------|--------|
| 部署方式 | 手动按文档起 5 个进程 | `docker compose up -d` 起全栈，nginx 统一入口 |
| 沙箱 | 手动 `docker run` 一个容器 | `docker:dind` sidecar + 五态生命周期 + 预热池 |
| 认证 | 无，前端硬编码 `user-001` | nginx Basic Auth + 按用户隔离的 `user_id` + 共享密钥 |
| 多租户越权 | 会话读写删不校验归属 | 一律校验归属，跨用户 403 |
| ERP 依赖 | 指向未开源的 Java 服务，跑不起来 | `deploy/mock-erp/` 自建替身，可独立运行 |
| grader 证据 | 只看最近 30 条消息，长任务误判编造 | 全量工具调用台账先于截断注入 |
| 发布与回滚 | 无（手工传文件 + 重建容器） | `deploy/cd/` 一条命令发布，失败自动回滚（镜像 + 源码树 + 状态文件三方一致） |
| 质量门禁 | 无 | GitHub Actions 8 个 job：静态检查 + **真起一套栈**的集成冒烟（认证与代理链路、完整拓扑含沙箱） |

上游的开源代码本身没有密钥泄漏，本仓库也没有；**所有密码类配置一律不入库**，仓库里只有 `*.example` 模板。

---

## Docker 部署（推荐用于服务器）

```bash
cp deploy/.env.example deploy/.env   # 填 CHATANYWHERE_API_KEY 和 PUBLIC_BASE_URL
# 创建登录账号，否则 nginx 起不来（htpasswd 的三种生成方式见 deploy/README.md）
docker run --rm httpd:2.4-alpine htpasswd -nbB 张三 '你的密码' > deploy/nginx/htpasswd
# 生成 nginx ↔ backend 的共享密钥（对公网部署必配，原因见 deploy/README.md）
cp deploy/nginx.env.example deploy/nginx.env
sh deploy/set_internal_token.sh
docker compose up -d --build
```

nginx 统一入口 `:80`，后端 / 前端 / PostgreSQL / MCP / 沙箱 dind 全部由 compose 编排，
沙箱不再需要手动 `docker run`。完整说明、运维命令、已知限制与故障排查见
[deploy/README.md](deploy/README.md)。

想在一台全新的云主机上从零跑起来（含 Docker 安装、镜像加速、swap、配置生成），
用 [deploy/cloud/README.md](deploy/cloud/README.md) 里的一键脚本：

```bash
bash deploy/cloud/pack.sh /tmp/erp-agent-deploy.tar.gz   # 本机打包
CHATANYWHERE_API_KEY=sk-xxxx bash deploy/cloud/bootstrap.sh <服务器IP>   # 服务器上
```

整个服务在 nginx 的 HTTP Basic Auth 后面，backend 用 nginx 注入的用户名决定
`user_id`（会话、历史、沙箱按人隔离）。本机开发 `AUTH_MODE=none` 时不启用。

> 容器部署**只能单副本**：沙箱生命周期与用户会话都是进程内状态。

下面的裸机步骤适合本机开发调试。

---

## 本地开发 vs 服务器生产：两套配置，互不干涉

| | 本地开发 | 服务器生产 |
|---|---|---|
| 配置文件 | 项目根 `.env`（gitignore + dockerignore，不进库不进镜像） | `deploy/.env` + `deploy/nginx.env` + `htpasswd`（package.filter 保护，同步永不覆盖） |
| 地址 | localhost / 127.0.0.1 | 容器服务名（postgres / mcp / backend…） |
| 加载方式 | [env_utils.py](src/agent/env_utils.py) 读根 `.env`，`override=False` | compose `env_file` 注入，优先级高于根 `.env` |
| 运行形态 | 进程直跑（下面「快速启动」） | docker compose 容器（上面「Docker 部署」） |

两条不要越界的规则：

- **本地不要跑 `docker compose up`** —— 那是服务器形态：compose 会把根 `.env` 当插值源，且缺 `deploy/.env` 直接报错。
- **服务器上没有也不该有根 `.env`** —— 生产树由 `git archive` + rsync 同步，根 `.env` 在排除清单里，物理上到不了服务器。

## 直推发布（日常迭代）

tag 发布流水线（release-please → build.yml → deploy.yml 人工审批）之外，还有一条
**本地直推**路径用于日常迭代：一条命令把当前分支发上生产，运行时安全链
（备份/迁移/影子/观察窗/自动回滚）与正式发布完全相同，只是免去了 PR 与人工审批。

> 该链路的三个脚本（`scripts/push-prod.ps1|.sh`、`deploy/cloud/post-receive.hook`、
> `deploy/cd/push-deploy.sh`）**不入库**，由本地与部署机各自维护。注意部署机生产树
> 由 `git archive` + rsync 同步：deploy 侧两个脚本必须放在**同步范围之外**（如
> `/etc/erp-agent/`，hook 里用 `PUSH_DEPLOY_SCRIPT` 指过去），否则会被 `rsync --delete` 清掉。

```powershell
# 本地（Windows；Git Bash 用 scripts/push-prod.sh）
powershell -File scripts\push-prod.ps1
```

它做的事：断言工作区干净（只发布已提交内容）→ 本地快速检查（ruff + compileall + pytest）→
push GitHub（保持真相源）→ push 服务器裸仓库 → 服务器 hook 自动构建镜像并走 deploy.sh
完整发布链，输出以 `remote:` 前缀实时回显，全程约 6-8 分钟（含 300s 观察窗）。

> 注意：post-receive 的退出码不影响 push 本身 —— **push 成功 ≠ 部署成功**。
> 部署失败会以 `remote:  !!` 开头的行出现在输出里，此时生产已自动回滚，修复后再推即可。

**一次性配置**：

```bash
# 本地
git remote add server ssh://root@<部署机IP>/srv/erp-agent.git
# ~/.ssh/config：Host <部署机IP> 配 IdentityFile 指向服务器私钥

# 服务器（root，一次性）
git clone /srv/erp-agent.git /srv/erp-agent-build
cp /root/erp-agent/deploy/cloud/post-receive.hook /srv/erp-agent.git/hooks/post-receive
chmod 755 /srv/erp-agent.git/hooks/post-receive
```

只推 `main` 会触发部署；推其他分支到 server 只是存一份服务器侧备份，不部署。

---

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 16+（需要 pgvector 与 zhparser；推荐使用 `deploy/postgres` 镜像）
- Docker Desktop（已启动）
- ChatAnywhere API Key（对话、grader、联网搜索共用）

### 1. 克隆项目 & 安装依赖

```bash
# 克隆项目
git clone https://github.com/farhub-wq/Agent-Harness.git
cd Agent-Harness

# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
cd ..
```

### 2. 配置环境变量

编辑项目根目录 `.env` 文件：

```bash
# ChatAnywhere API Key（主对话、grader、联网搜索共用）
# 获取地址: https://chatanywhere.apifox.cn
CHATANYWHERE_API_KEY=sk-xxxx
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.chatanywhere.tech/v1
WEB_SEARCH_MODEL=gpt-4o-mini

# PostgreSQL 连接
DATABASE_URL=postgresql://erp_agent:erp_agent@localhost:5432/erp_agent

# Java ERP 后端地址
# 若没有自己的 ERP 服务，可先保留占位地址，联网搜索和基础对话仍可启动
ERP_BASE_URL=http://localhost:8081

# MCP Server 地址（本地）
MCP_SERVER_URL=http://localhost:9000

# 沙箱 Docker 镜像
SANDBOX_IMAGE=python:3.11-slim
```

### 3. 启动 PostgreSQL

```bash
# 使用项目内置的 pgvector + zhparser 镜像
docker compose up -d --build postgres
```

### 4. 启动 Docker 沙箱容器

```bash
docker run -d \
  --name erp-sandbox \
  -w /workspace \
  python:3.11-slim \
  sleep infinity
```

### 5. 启动 MCP Server（端口 9000）

```bash
python -m src.mcp_server.server_main
```

看到以下输出表示成功：
```
🚀 Starting MCP Server on 0.0.0.0:9000 (SSE transport)
Uvicorn running on http://0.0.0.0:9000
```

### 6. 启动后端 API（端口 8000）

```bash
python -m src.api_view.web_main
```

看到以下输出表示成功：
```
AgentLoader initialized
Starting ERP Agent Web Server...
Uvicorn running on http://0.0.0.0:8000
```

### 7. 启动前端（端口 3000）

```bash
cd frontend
npm run dev
```

### 8. 访问应用

浏览器打开 http://localhost:3000 即可使用。

---

## 启动顺序总结

```
PostgreSQL → Docker沙箱 → MCP Server(:9000) → Backend API(:8000) → Frontend(:3000)
```

> 注意：MCP Server 必须在 Backend API 之前启动，因为 Agent 初始化时会连接 MCP Server 加载 23 个 ERP 工具。

---

## 项目亮点

### 1. 真正的 Harness Engineering 架构
不是简单的 ChatBot，而是严格遵循 **Planning → Executing → Review → Result** 四阶段工作流。前端实时展示每个阶段的状态变化（Phase Bar + TodoList），用户可清晰看到 Agent 的思考和执行过程。

### 2. 生产级 Docker 安全沙箱
7 层安全防护（只读文件系统 + tmpfs + 资源限制 + 网络隔离 + Capability 移除 + seccomp 白名单 + PID 限制），不是玩具级沙箱。支持多语言运行时扩展（Python/Go/Node.js），项目文件完整同步到沙箱实现真正隔离测试。

### 3. 五态沙箱生命周期
预热池 → 认领 → PostgreSQL 租约 → 新建 → 销毁。服务重启不丢失用户绑定关系，健康检查负责热替换故障容器。

### 4. 完整的 HITL 审批流程
订单创建/更新需人工审批，缺少字段时触发信息补充中断。基于 LangGraph 的 interrupt/resume 机制，前端展示审批卡片和信息补充表单。

### 5. 中间件栈
沙箱健康检查、用户上下文注入（请求级 `configurable` 隔离）、技能增量同步、用户技能恢复、工具摘要监控、偏好自动提取、熔断器保护、调用限制。每个中间件都有明确的职责边界。

### 6. MCP 协议解耦
Agent 不直接调用 ERP API，而是通过 MCP Server 提供的 23 个标准化工具交互。MCP 层可独立部署、独立扩展，Agent 侧无需关心 ERP 接口细节。

### 7. PostgreSQL + pgvector 全链路持久化
- **PostgresSaver**：LangGraph Checkpointer（会话与 HOT 状态）
- **PostgresStore**：semantic / episodic / procedural 记忆、用户 Skills、CalcRecord 等框架/运行对象
- **app/audit schema**：展示消息、会话、写审计及持久化补偿任务

### 8. 子Agent 委派 + YAML 声明式配置
采购分析师和订单专家两个子Agent，通过 YAML 文件声明式配置（工具集、系统提示词、委派规则），主Agent 根据任务类型自动委派。

### 9. SSE 流式协议
完整的 SSE 事件协议：`thinking` → `token` → `tool_start` → `tool_result` → `phase` → `todo_update` → `interrupt` → `done`。前端逐 token 渲染，实时展示工具调用和阶段变化。

### 10. 技能系统（Skills）
文件夹级技能管理（SKILL.md + 脚本 + 依赖），支持安装/同步/恢复。SkillsSyncMiddleware 实现增量同步（SHA256 哈希比对），保留完整目录结构。

### 11. 三层记忆治理（HOT / WARM / COLD）
语义、情节、程序记忆分别建模，通过用户命名空间隔离。`MemoryKeeper` 集中处理偏好合并、
旧版本失效、情节幂等归档、TTL、容量与访问频次治理。

### 12. 上下文经济
WARM 摘要在每次请求或 HITL resume 时刷新，最多 4000 字符；本次执行中的模型调用和子 Agent 委派共同复用。更早的情节与程序记忆由 `read_memory`
按需检索，采用 PostgreSQL 关键词与 pgvector 两路召回、RRF 融合，并以时间、引用频次和
置信度作有限增益。关键词召回由 zhparser 对中英文采购术语统一分词，并通过 GIN 索引查询；
库存、价格、订单状态和供应商
当前状态始终回源 ERP。

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/stream` | SSE 流式对话 |
| POST | `/api/chat/{thread_id}/resume` | 中断恢复 |
| GET | `/api/chat/{thread_id}/state` | 获取中断状态 |
| GET | `/api/chat/{thread_id}/history` | 获取消息历史 |
| GET | `/api/history/{user_id}` | 获取会话列表 |
| DELETE | `/api/history/{thread_id}` | 删除会话 |
| GET | `/api/download/{file_id}/{filename}` | 下载当前用户的临时生成文件 |
| GET | `/health` | 健康检查（后端就绪） |
| GET | `/healthz` | 存活探针（仅经 nginx，不认证） |

容器部署下 `/api/*` 由 nginx 反代并注入 `X-Authenticated-User` 与 `X-Internal-Auth`，
backend 在 `AUTH_MODE=proxy` 下按它们派生 `user_id` 并校验共享密钥；请求头缺失返回
401。本机开发 `AUTH_MODE=none`，行为与改造前一致。详见 [deploy/README.md](deploy/README.md)。

---

## 开发说明

- 修改 Agent 行为：编辑 `src/agent/memory/prompts.py`（系统提示词）
- 添加新工具：在 `src/agent/tools/` 创建工具文件，在 `main_agent.py` 注册
- 添加新中间件：在 `src/agent/middlewares/` 创建，在 `main_agent.py` 中间件栈中添加
- 修改子Agent：编辑 `src/agent/subagents/configs/*.yaml`
- 改部署拓扑 / 排查容器问题：[deploy/README.md](deploy/README.md)
- 发布 / 回滚：[deploy/cd/README.md](deploy/cd/README.md)
- 备份 / 恢复 / 迁移 / 恢复演练 / 巡检与告警：[deploy/dr/README.md](deploy/dr/README.md)
- 改 CI 门禁 / 集成冒烟：[deploy/ci/README.md](deploy/ci/README.md)

---

## 提交前检查

仓库里**不应该**出现真实凭据。`.gitignore` 已经挡住这几个文件，改动它们之后
`git status` 不应把它们列为可提交：

| 文件 | 内容 |
|------|------|
| `.env` | ChatAnywhere API Key、本地 PostgreSQL 连接串 |
| `deploy/.env` | 容器部署的 PostgreSQL 密码、API Key |
| `deploy/nginx.env` | nginx ↔ backend 共享密钥 |
| `deploy/nginx/htpasswd` | Basic Auth 密码哈希 |

模板（`*.example`）里一律写占位值 `xxxx`。提交前自查：

```bash
git status --short                # 上面四个文件不应出现在列表里
git grep -nIE 'sk-[A-Za-z0-9]{20,}'   # 应当没有输出
```

同一条规则在 CI 上由 `secret-scan` job 强制：`leak-check.sh --tree` 查**路径**（哪些文件绝不该入库、`deploy/cd/package.filter` 有没有退化），gitleaks 查**内容与全历史**（删掉文件不等于删掉——历史里还在）。本地改完 `.gitignore` 或 `package.filter` 后先自己跑一遍：

```bash
bash deploy/cd/leak-check.sh --tree
```

同理，**文档里也不要写真实的公网 IP / 主机名**（这个仓库是 public）：需要指代部署机时
写「部署机」，真实地址留在不入库的 `deploy/.env` 里。这条是踩过的坑——`deploy/cd/README.md`
曾经把生产 IP 写进了正文。

---

## 来源与致谢

- 上游项目：[wodrake/ERP-AGENT-open-source](https://github.com/wodrake/ERP-AGENT-open-source)（Agent 侧开源实现，本项目在其之上继续开发）
- Agent 框架：[DeepAgent](https://github.com/langchain-ai/deepagents) + [LangGraph](https://github.com/langchain-ai/langgraph)
- 工具协议：[Model Context Protocol](https://modelcontextprotocol.io/)
- 模型：ChatAnywhere（OpenAI 兼容网关，支持 gpt-4o / claude / deepseek 等）

本项目仓库未附 License 文件，如需商用请先确认上游的授权条款。
