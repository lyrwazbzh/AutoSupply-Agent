"""
主入口：create_main_agent()
DeepAgent 核心组装 — 严格遵循 Harness Engineering 架构
"""
import fnmatch
import io
import tarfile
from pathlib import Path
from typing import Optional

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend, StoreBackend
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)

from .approval import approval_policy_registry
from .backends.sandbox_setup import SANDBOX_TRANSFER_DIR
from .config import (
    ALLOW_LOCAL_SHELL_FALLBACK,
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
    SANDBOX_HEALTH_CHECK_INTERVAL_SECONDS,
    get_llm,
    skills_store_namespace,
)
from .log_utils import agent_logger
from .memory.config import DEFAULT_MEMORY_CONFIG
from .memory.prompts import MAIN_SYSTEM_PROMPT, MEMORY_USAGE_PROMPT
from .schema import ProcurementContext

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "src" / "skills"
MEMORY_DIR = Path(__file__).parent / "memory"


def _upload_project_to_sandbox(sandbox) -> bool:
    """
    将项目文件上传到沙箱 /workspace/src/ 目录，搭建 1:1 开发环境。
    跳过 node_modules / .git / __pycache__ / .next 等无关目录。
    """
    skip_patterns = [
        ".git", "__pycache__", "node_modules", ".next", ".venv",
        ".env", ".env.*", "*.pem", "*.key",
        ".eggs", "*.pyc", "*.pyo", ".DS_Store", ".docker",
        "*.png", "*.jpg", "*.jpeg", "*.gif",  # 生成物不传
        # 生成物/临时目录：整棵树会被打包上传进沙箱一次，
        # 这里多一个字节就多传一次。
        "download", "tmp", "*.tar.gz", "*.tar",
    ]

    def _should_skip(rel_path: str) -> bool:
        for pattern in skip_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            parts = rel_path.replace("\\", "/").split("/")
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    remote_dir = "/workspace/src"
    try:
        sandbox.execute(f"mkdir -p '{remote_dir}'")

        tar_stream = io.BytesIO()
        skipped_errors = []
        with tarfile.open(fileobj=tar_stream, mode="w:gz") as tar:
            for file_path in sorted(PROJECT_ROOT.rglob("*")):
                if not file_path.is_file():
                    continue
                rel = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if _should_skip(rel):
                    continue
                # 单个文件不可读（如被进程锁定的 .lock）不应中断整个上传，
                # 跳过并记录，其余文件照常打包。
                try:
                    tar.add(str(file_path), arcname=rel)
                except (PermissionError, OSError) as e:
                    skipped_errors.append(f"{rel}: {e}")
        if skipped_errors:
            agent_logger.warning(
                f"Skipped {len(skipped_errors)} unreadable file(s) during "
                f"project upload: {skipped_errors[:3]}"
            )

        tar_stream.seek(0)
        data = tar_stream.read()

        # 仅使用 BaseSandbox 的公开协议上传；这样 SandboxBackendProxy 热替换
        # 底层容器后，项目上传仍能工作，且不会依赖 Docker 私有 _container。
        #
        # 落地点必须在 volume 上，不能放 /tmp：只读 rootfs 下 daemon 的 archive
        # 接口拒绝写 tmpfs（500 "container rootfs is marked read-only"），
        # 详见 SANDBOX_TRANSFER_DIR。解包目标仍是 tmpfs 的 /workspace/src，
        # 那是 exec 里的 tar 写的，不受这条限制。
        archive_path = f"{SANDBOX_TRANSFER_DIR}/erp-agent-project.tar.gz"
        responses = sandbox.upload_files([(archive_path, data)])
        errors = [getattr(item, "error", None) for item in responses]
        if not responses or any(errors):
            raise RuntimeError(f"archive upload failed: {errors or 'no response'}")

        unpack = sandbox.execute(
            f"tar -xzf '{archive_path}' -C '{remote_dir}' && rm -f '{archive_path}'"
        )
        if unpack.exit_code != 0:
            raise RuntimeError(f"archive extraction failed: {unpack.output}")

        # 获取文件数量和总大小
        count_result = sandbox.execute(
            f"find {remote_dir} -type f 2>/dev/null | wc -l"
        )
        size_result = sandbox.execute(
            f"du -sh {remote_dir} 2>/dev/null | cut -f1"
        )
        file_count = count_result.output.strip() if count_result.exit_code == 0 else "?"
        total_size = size_result.output.strip() if size_result.exit_code == 0 else "?"

        agent_logger.info(
            f"Project uploaded to sandbox: {remote_dir} "
            f"({file_count} files, {total_size})"
        )
        return True
    except Exception as e:
        agent_logger.warning(f"Project upload to sandbox failed (non-fatal): {e}")
        return False


def bootstrap_sandbox(sandbox) -> None:
    """填充一个新领取或重建后的沙箱，使其可立即继续 Agent 工作。

    这个函数只使用稳定 Proxy 暴露的公开能力，因此健康检查重建后的同一个
    Agent、CompositeBackend 和工具对象都能继续复用。
    """
    setup = sandbox.execute(
        "mkdir -p /workspace/charts /workspace/output /workspace/data "
        "/workspace/python-packages /skills"
    )
    if setup.exit_code != 0:
        raise RuntimeError(f"sandbox directory setup failed: {setup.output}")

    if not _upload_project_to_sandbox(sandbox):
        raise RuntimeError("project bootstrap upload failed")

    skills_copy = sandbox.execute(
        "mkdir -p /skills && "
        "cp -r /workspace/src/src/skills/. /skills/ 2>/dev/null || true"
    )
    if skills_copy.exit_code != 0:
        raise RuntimeError(f"core Skills bootstrap failed: {skills_copy.output}")

    agent_logger.info("Sandbox bootstrap complete: project + core Skills restored")


def _load_skills_index(skills_dir: Path) -> str:
    """只注入 Skill 索引；具体说明按需从沙箱读取，避免常驻提示词膨胀。"""
    if not skills_dir.exists():
        return ""

    import re

    import yaml

    entries: list[str] = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        try:
            content = skill_md.read_text(encoding="utf-8").strip()
            match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
            metadata = yaml.safe_load(match.group(1)) if match else {}
            if not isinstance(metadata, dict):
                metadata = {}
            name = str(metadata.get("name") or skill_md.parent.name).strip()
            description = str(metadata.get("description") or "").strip()
            rel_path = skill_md.relative_to(skills_dir).as_posix()
            entries.append(f"- **{name}** — {description}（`/skills/{rel_path}`）")
        except Exception as e:
            agent_logger.warning(f"Failed to load skill {skill_md}: {e}")

    if not entries:
        return ""
    return (
        "\n\n## Skills 索引\n"
        "仅当任务明确匹配某项技能时，先读取列出的 `SKILL.md` 再执行；"
        "不要凭索引描述猜测细节。用户技能位于 `/skills/custom/`，用 "
        "`list_user_skills` 发现。\n"
        + "\n".join(entries)
    )


def _load_behavior_policy() -> str:
    """读取唯一的全局行为策略；动态身份和记忆仍由模板注入。"""
    policy_path = MEMORY_DIR / "AGENTS.md"
    try:
        return policy_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Cannot load canonical agent policy: {policy_path}") from exc


def _main_tool_surface(tool_catalog: list) -> list:
    """主 Agent 保留当前身份可见的完整工具集。

    子 Agent 的 YAML 白名单用于专业分工和最小权限隔离，但不能反向限制总控
    Agent。知识写入、Skill 安装等身份权限过滤应在构建 ``tool_catalog`` 时完成；
    ERP 写工具仍由审批策略和 ERPWriteMiddleware 执行纵深校验。
    """
    return list(tool_catalog)


def create_main_agent(
    user_context: Optional[ProcurementContext] = None,
    checkpointer=None,
    store=None,
    write_audit_repository=None,
    warm_memory_middleware=None,
    mcp_auth_token: str = "",
    permissions: frozenset[str] | None = None,
):
    """
    创建主 Agent 实例

    组装顺序（严格遵循文档）：
    1. LLM（ChatAnywhere 网关，OpenAI 兼容）
    2. CompositeBackend 三层路由（default=sandbox, /memories/=Store, /persisted-skills/=Store）
    3. 工具加载（MCP + chart + web_search + hitl）
    4. 子Agent配置（YAML声明式）
    5. 中间件栈（7自定义 + 框架内置）
    6. 创建 Agent

    Args:
        user_context: 用户上下文（含偏好）
        checkpointer: LangGraph checkpointer（会话持久化）
        store: LangGraph store（跨会话存储）
        write_audit_repository: PostgreSQL 写操作审计仓储

    Returns:
        CompiledStateGraph - 可执行的 Agent 图
    """
    if user_context is None:
        user_context = ProcurementContext()

    agent_logger.info(f"Creating main agent for user: {user_context.user_id}")

    # ===== 1. LLM =====
    llm = get_llm()
    grader_llm = get_llm(thinking=False)

    # ===== 2. Backend - Manager + Stable Proxy + CompositeBackend =====
    # Manager 负责用户级领取/恢复/重建；Proxy 保持 Agent 已持有的后端引用稳定。
    sandbox_manager_instance = None
    managed_sandbox = False
    try:
        from .backends.sandbox_holder import set_sandbox
        from .backends.sandbox_manager import sandbox_manager
        from .backends.sandbox_proxy import SandboxBackendProxy

        raw_sandbox = sandbox_manager.get_sandbox(user_context.user_id)
        sandbox_backend = SandboxBackendProxy(raw_sandbox)
        bootstrap_sandbox(sandbox_backend)
        sandbox_manager_instance = sandbox_manager
        managed_sandbox = True
        # 注册的是稳定 Proxy，而不是会在重建后失效的原始 Docker 连接。
        set_sandbox(sandbox_backend, user_context.user_id)
        agent_logger.info(
            f"Using managed Docker sandbox for {user_context.user_id}: "
            f"{sandbox_backend.container_name}"
        )
    except Exception as e:
        if not ALLOW_LOCAL_SHELL_FALLBACK:
            # LocalShellBackend 在 backend 进程自身的工作目录里执行模型生成的
            # 代码 —— 那里有 CHATANYWHERE_API_KEY、可写的 skills 挂载和整个 /app。
            # 容器部署下宁可直接失败，也不要静默把沙箱换成裸进程。
            agent_logger.error(
                f"Managed Docker sandbox unavailable ({e}); LocalShell fallback "
                f"disabled (ALLOW_LOCAL_SHELL_FALLBACK=false)"
            )
            raise
        agent_logger.warning(
            f"Managed Docker sandbox unavailable ({e}), falling back to LocalShell"
        )
        sandbox_backend = LocalShellBackend(virtual_mode=True)
        from .backends.sandbox_holder import set_sandbox
        set_sandbox(None, user_context.user_id)

    # deepagents >= 0.7 要求传入已初始化的 Backend 实例，
    # 不再接受旧版的 backend factory。
    backend_routes = {}
    if store is not None:
        backend_routes["/memories/"] = StoreBackend(
            namespace=lambda _rt: (user_context.user_id,),
        )
        backend_routes["/persisted-skills/"] = StoreBackend(
            namespace=lambda _rt: skills_store_namespace(user_context.user_id),
        )
    composite_backend = CompositeBackend(
        default=sandbox_backend,
        routes=backend_routes,
    )

    # ===== 3. 加载工具 =====
    from .tools.chart_generator import generate_chart
    from .tools.document_generator import generate_document, generate_table_report
    from .tools.download_sandbox_file import download_sandbox_file, list_sandbox_files
    from .tools.hitl_tools import request_order_info
    from .tools.knowledge_tools import (
        ingest_business_knowledge,
        ingest_pdf_knowledge,
        search_business_knowledge,
    )
    from .tools.mcp_client import load_mcp_tools_sync
    from .tools.skill_management import list_user_skills
    from .tools.web_fetch import install_skill, web_fetch
    from .tools.web_search import web_search

    mcp_tools = load_mcp_tools_sync(auth_token=mcp_auth_token)
    tool_catalog = mcp_tools + [
        generate_chart, web_search, web_fetch, list_user_skills, request_order_info,
        search_business_knowledge, download_sandbox_file, list_sandbox_files,
        generate_document, generate_table_report,
    ]

    # 全局知识写入与运行时 Skill 安装仅对显式授权主体可见；工具内部还有第二层校验。
    if permissions is None or "assistant:knowledge:write" in permissions:
        tool_catalog.extend([ingest_business_knowledge, ingest_pdf_knowledge])
    if permissions is None or "assistant:skill:install" in permissions:
        tool_catalog.append(install_skill)

    # 三层记忆：COLD 层按需检索 + 显式写入（WARM 层已在系统提示词里常驻注入）
    if DEFAULT_MEMORY_CONFIG.memory_tools_enabled:
        from .tools.memory_tools import read_memory, remember

        tool_catalog.extend([read_memory, remember])

    # 主 Agent 是总控，使用经过当前身份过滤后的完整工具集；两个子 Agent 再通过
    # 各自 YAML 中的精确工具名白名单划分能力边界。
    main_tools = _main_tool_surface(tool_catalog)

    from .audit.repository import WriteAuditRepository
    from .middlewares.erp_write import ERPWriteMiddleware

    if write_audit_repository is None:
        write_audit_repository = WriteAuditRepository()

    agent_logger.info(
        f"Tools loaded: main={len(main_tools)}, catalog={len(tool_catalog)} "
        f"(MCP discovered={len(mcp_tools)})"
    )

    # ===== 4. 加载子Agent配置 =====
    from .middleware_config import get_all_subagent_middlewares
    from .subagents.loader import (
        get_delegation_context_prompt,
        load_subagent_configs,
        resolve_subagent_tools,
    )
    subagent_configs = load_subagent_configs()
    subagent_middlewares = get_all_subagent_middlewares(
        sandbox_backend=sandbox_backend,
        user_context=user_context,
        model=llm,
        compaction_backend=composite_backend,
    )
    for config in subagent_configs:
        subagent_middlewares.setdefault(config["name"], []).append(
            ERPWriteMiddleware(
                repository=write_audit_repository,
                user_id=user_context.user_id,
                agent_name=config["name"],
                store=store,
                permissions=permissions,
            )
        )
    subagents = resolve_subagent_tools(
        subagent_configs,
        tool_catalog,
        middleware_by_agent=subagent_middlewares,
        approval_policy=approval_policy_registry,
    )
    # 主 Agent 直调和子 Agent 委派都从同一策略中心投影审批规则。
    # create_deep_agent 负责主路径 HITL 注册，避免再叠加显式 Middleware。
    compiled_main_policy = approval_policy_registry.subset_for_tools(
        getattr(tool, "name", "") for tool in main_tools
    )
    # 生成委派上下文协议（注入主 Agent 提示词）
    delegation_prompt = get_delegation_context_prompt(subagent_configs)

    # ===== 5. 组装中间件栈 =====
    # 自定义中间件
    # Harness 阶段状态机 + 评审器（真 Harness 架构核心）
    from .harness import HarnessPhaseMiddleware, load_harness_config
    from .middlewares.grader_transcript import build_grader_messages
    from .middlewares.memory_lifecycle import MemoryLifecycleMiddleware
    from .middlewares.result_audit import ResultAuditMiddleware
    from .middlewares.review_gate import ReviewExecutionGate, SafeRubricMiddleware
    from .middlewares.sandbox_breaker import SandboxCircuitBreakerMiddleware
    from .middlewares.sandbox_health import SandboxHealthMiddleware
    from .middlewares.skills_lifecycle import SkillsLifecycleMiddleware
    from .middlewares.warm_memory import WARM_MEMORY_SLOT, WarmMemoryMiddleware

    # 读取 Harness DSL 配置中的评审迭代上限
    _harness_config = load_harness_config()
    _review_cfg = _harness_config.get("review", {}) if isinstance(_harness_config, dict) else {}
    _review_max_iterations = _review_cfg.get("max_iterations", 3)
    router_llm = get_llm(thinking=False, timeout=_review_cfg.get("router_timeout_seconds", 8),
                         max_retries=0, max_tokens=400)

    # create_deep_agent 内部会添加通用 SummarizationMiddleware；下面传入的
    # 同名采购摘要器会原位替换它。当前不注册手动 compact_conversation 工具。
    # create_deep_agent 还会自动添加：
    # - FilesystemMiddleware, SkillsMiddleware, SubAgentMiddleware
    # - TodoListMiddleware, PatchToolCallsMiddleware, MemoryMiddleware
    # 我们只需添加自定义中间件 + 调用限制
    # 沙箱重建后替换 Proxy 底层并重填项目 / 基础 Skills / 用户 Skills。
    skills_lifecycle_middleware = SkillsLifecycleMiddleware(
        skills_dir=SKILLS_DIR,
        sandbox_backend=sandbox_backend if managed_sandbox else None,
        store=store,
        user_id=user_context.user_id,
    )

    def _prepare_sandbox_replacement(replacement) -> None:
        # 核心环境在新 generation 对外发布前完成初始化。
        bootstrap_sandbox(replacement)

    def _rehydrate_after_sandbox_rebuild(_replacement) -> None:
        skills_lifecycle_middleware.invalidate()
        # 基础 Skills 已由 bootstrap 恢复；增量同步及用户 Skills 属于可降级能力。
        try:
            skills_lifecycle_middleware.sync_now()
        except Exception as exc:
            agent_logger.warning(f"Incremental core Skill sync degraded: {exc}")
        try:
            skills_lifecycle_middleware.restore_now()
        except Exception as exc:
            agent_logger.warning(f"User Skill restore degraded: {exc}")

    warm_memory_middleware = warm_memory_middleware or WarmMemoryMiddleware(
        store=store, user_id=user_context.user_id, user_context=user_context
    )

    sandbox_breaker_middleware = SandboxCircuitBreakerMiddleware(
        sandbox_backend=sandbox_backend,
        failure_threshold=3,
        recovery_timeout=60,
    )
    sandbox_health_middleware = SandboxHealthMiddleware(
        sandbox_manager=sandbox_manager_instance,
        user_id=user_context.user_id,
        sandbox_backend=sandbox_backend if managed_sandbox else None,
        prepare_replacement=(
            _prepare_sandbox_replacement if managed_sandbox else None
        ),
        on_rebuild=_rehydrate_after_sandbox_rebuild if managed_sandbox else None,
        on_recovered=(
            sandbox_breaker_middleware.record_recovered_generation
            if managed_sandbox else None
        ),
        check_interval=SANDBOX_HEALTH_CHECK_INTERVAL_SECONDS,
    )
    sandbox_breaker_middleware.set_on_open(
        sandbox_health_middleware.mark_unhealthy
    )

    from .context_compaction import create_context_compaction_middleware

    middlewares = [
        create_context_compaction_middleware(
            model=llm,
            backend=composite_backend,
        ),
        sandbox_health_middleware,                      # 沙箱探活 / 重建
        HarnessPhaseMiddleware(router_model=router_llm),  # 是否评审 + task_type + rubric
        warm_memory_middleware,                         # 请求级 WARM 快照
        skills_lifecycle_middleware,                    # 基础 Skills 同步 + 用户 Skills 恢复
        MemoryLifecycleMiddleware(store=store, user_id=user_context.user_id),
        sandbox_breaker_middleware,                     # 沙箱工具熔断
        ResultAuditMiddleware(store=store, user_id=user_context.user_id),
        SafeRubricMiddleware(
            model=grader_llm,
            max_iterations=_review_max_iterations,
            prepare_messages_for_grader=build_grader_messages,
        ),
        ReviewExecutionGate(_harness_config),           # after 逆序：先升级再审查
        ERPWriteMiddleware(
            repository=write_audit_repository,
            user_id=user_context.user_id,
            agent_name="main",
            store=store,
            permissions=permissions,
        ),
        ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS),
        ToolCallLimitMiddleware(run_limit=MAX_TOOL_CALLS),
    ]

    # ===== 6. 构建系统提示词 =====
    system_prompt = MAIN_SYSTEM_PROMPT.format(
        user_id=user_context.user_id,
        username=user_context.username,
        preferences="以本次动态加载的记忆为准",
        warm_memory=WARM_MEMORY_SLOT,
        behavior_policy=_load_behavior_policy(),
    )
    if DEFAULT_MEMORY_CONFIG.memory_tools_enabled:
        system_prompt += MEMORY_USAGE_PROMPT
    # 注入子Agent委派上下文协议
    if delegation_prompt:
        system_prompt += delegation_prompt

    # ===== 6.5 仅注入 Skill 索引，细节由 Agent 在命中任务时按需读取 =====
    skills_prompt = _load_skills_index(SKILLS_DIR)
    if skills_prompt:
        system_prompt += skills_prompt
        agent_logger.info(f"Skills loaded into prompt from {SKILLS_DIR}")

    # ===== 7. 创建 Agent =====
    # ❌ 不传 skills 参数（框架内置 SkillsMiddleware 无法处理含中文路径）
    # ✅ Skills 通过索引注入 system_prompt，并由唯一的 SkillsLifecycleMiddleware
    #    负责核心 Skill 同步与当前用户自定义 Skill 恢复。
    agent = create_deep_agent(
        model=llm,
        tools=main_tools,
        system_prompt=system_prompt,
        middleware=middlewares,
        subagents=subagents if subagents else None,
        skills=None,
        memory=None,
        backend=composite_backend,
        interrupt_on=compiled_main_policy,
        checkpointer=checkpointer,
        store=store,
        name="procurement-main-agent",
    )

    agent_logger.info(
        f"Main agent created: {len(main_tools)} main tools, "
        f"{len(subagents)} subagents, {len(middlewares)} middlewares"
    )
    return agent
