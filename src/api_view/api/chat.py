"""
核心 SSE 流式对话 + 中断检测 + 中断恢复 + 展示消息持久化

关键设计：
- 双模式流: stream_mode=["messages", "values"], subgraphs=True
- 输出格式: (namespace, mode, data) 三元组
- 中断检测在 messages 处理之前（values 流优先）
- display_messages 实时累积（用户消息 + 助手回复 + 工具调用）
- SSE 事件协议: token / tool_start / tool_args / tool_result / tool_end / interrupt / done
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from ...agent.log_utils import web_logger
from ...agent.schema import ChatRequest, ResumeRequest
from ..agent_loader import agent_loader
from ..auth import assert_thread_owner, current_user_id, resolve_user_id

router = APIRouter(prefix="/api/chat", tags=["chat"])

# SSE 客户端断开后，Agent 任务仍需继续运行并把最终结果写入数据库。
# 保留强引用，避免后台任务在完成前被垃圾回收。
_background_stream_tasks: set[asyncio.Task[None]] = set()


def sse_event(event: str, data: dict) -> str:
    """格式化 SSE 事件（严格遵循 event:/data: 协议）"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Harness 阶段 → 前端展示文案
PHASE_LABELS = {
    "planning": "📝 规划中",
    "executing": "⚙️ 执行中",
    "reviewing": "🔍 审查中",
    "result": "📊 已完成",
    "thinking": "💭 思考中",
}


def _format_interrupt_data(interrupt_value: object) -> dict | None:
    """把 LangGraph interrupt 载荷转换成稳定的前端协议。"""
    if not isinstance(interrupt_value, dict):
        return None

    if interrupt_value.get("type") == "order_info_request":
        return {
            "interrupt_type": "order_info_supplement",
            "missing_fields": interrupt_value.get("missing_fields", []),
            "message": interrupt_value.get("message", ""),
            "extracted_data": interrupt_value.get("current_data", {}),
        }

    if "action_requests" in interrupt_value:
        requests_list = interrupt_value.get("action_requests", [])
        tool_names = [
            request.get("name", "")
            for request in requests_list
            if isinstance(request, dict)
        ]
        order_args = {}
        operation_ids = []
        for request in requests_list:
            if isinstance(request, dict) and isinstance(request.get("args"), dict):
                order_args.update(request["args"])
                if request["args"].get("operation_id"):
                    operation_ids.append(str(request["args"]["operation_id"]))
        return {
            "interrupt_type": "hitl_approval",
            "tool_name": ", ".join(name for name in tool_names if name),
            "tool_args": order_args,
            "order_data": order_args,
            "operation_ids": operation_ids,
        }

    tool_args = interrupt_value.get("tool_args", interrupt_value)
    operation_ids = []
    if isinstance(tool_args, dict) and tool_args.get("operation_id"):
        operation_ids.append(str(tool_args["operation_id"]))
    return {
        "interrupt_type": "hitl_approval",
        "tool_name": interrupt_value.get("tool_name", ""),
        "tool_args": tool_args,
        "order_data": tool_args,
        "operation_ids": operation_ids,
    }


async def stream_chat_response(
    message: str,
    thread_id: str,
    user_id: str = "default_user",
    username: str = "用户",
    resume_data: dict = None,
) -> AsyncGenerator[str, None]:
    """
    核心流式响应生成器

    双流模式（subgraphs=True 时输出为 3-tuple）：
    - (namespace, "values", data): 检测中断（interrupts 字段）
    - (namespace, "messages", data): 逐 token 输出 + 工具调用事件

    消息累积：
    - 实时将 assistant 回复追加到 display_messages
    - 流结束后持久化到 PostgreSQL
    """
    # 每个用户有独立 Agent（含 Proxy、中间件缓存和 SandboxManager 映射）。
    session = await agent_loader.get_session(user_id, username)

    # 当前助手消息累积缓冲
    assistant_content = ""
    tool_calls_buffer = []
    thinking_emitted = False
    phase = "thinking"  # 当前阶段: thinking → planning → executing → reviewing → result
    last_phase = "thinking"  # 上次已发射的阶段（去重）
    last_todos_sig = None  # 上次已发射的 todo 列表签名（去重）
    last_review_sig = None
    harness_trace: list = []  # Harness 阶段流转 trace（P3 可观测）

    # 同一用户的整个流串行运行，避免两个会话同时覆盖 /tmp、/workspace 中的文件。
    # ContextVar 让图表、文档、Skill 工具在并发用户之间取到正确的稳定 Proxy。
    from ...agent.backends.sandbox_holder import bind_sandbox, reset_sandbox
    from ...agent.backends.sandbox_manager import sandbox_manager
    from ...agent.runtime_context import bind_runtime, reset_runtime

    await session.run_lock.acquire()
    lease_acquired = sandbox_manager.acquire_lease(user_id)
    sandbox_token = bind_sandbox(user_id)
    runtime_tokens = bind_runtime(user_id, agent_loader.store)

    try:
        # 每个新请求和 HITL resume 都刷新同一个 ProcurementContext.warm_memory；
        # 后续模型调用与子 Agent 委派只复用该值，不再查询 Store。
        await session.warm_memory_middleware.arefresh()
        # task 子图自动继承父运行的 configurable；在 WARM 刷新后生成快照，
        # 主 Agent 无需把身份和记忆拼接进委派 description。
        config = agent_loader.create_config(thread_id, user_id)

        # 必须在会话锁内读取展示历史。快速追问可能在上一条 SSE 刚结束时
        # 立即到达；若提前读取，后一个请求会拿到旧快照，并在结束时覆盖
        # 上一轮刚保存的消息。
        display_messages = await agent_loader.get_display_messages(thread_id)
        if resume_data:
            current_input = Command(resume=resume_data)
        else:
            message_id = str(uuid.uuid4())
            display_messages.append({
                "id": message_id,
                "role": "user",
                "content": message,
                "timestamp": datetime.now().isoformat(),
            })
            current_input = {
                "messages": [{"role": "user", "content": message, "id": message_id}],
            }
            # 请求一开始就持久化用户消息。浏览器刷新、切换页面或主动取消时，
            # 至少不会留下“有 checkpoint、但历史消息为空”的幽灵会话。
            await agent_loader.save_display_messages(thread_id, display_messages)

        # 发射“深度思考”事件（前端展示思考动画）
        yield sse_event("thinking", {"status": "start"})

        async for namespace, chunk_type, chunk in session.agent.astream(
            input=current_input,
            config=config,
            stream_mode=["messages", "values", "custom"],
            subgraphs=True,
        ):
            # ===== 中断检测 + 结构化 Harness 状态读取（必须在 messages 处理之前）=====
            if chunk_type == "values":
                if isinstance(chunk, dict):
                    if not namespace and chunk.get("review_decision"):
                        decision = chunk["review_decision"]
                        signature = json.dumps(decision, ensure_ascii=False, sort_keys=True)
                        if signature != last_review_sig:
                            last_review_sig = signature
                            harness_trace.append({"type": "review_decision", **decision,
                                                  "timestamp": datetime.now().isoformat()})
                    # --- 结构化阶段流转（来自 HarnessPhaseMiddleware 写入的 state.phase）---
                    new_phase = chunk.get("phase")
                    if new_phase and new_phase != last_phase:
                        last_phase = new_phase
                        phase = new_phase
                        label = PHASE_LABELS.get(new_phase, new_phase)
                        harness_trace.append({
                            "type": "phase",
                            "phase": new_phase,
                            "label": label,
                            "timestamp": datetime.now().isoformat(),
                        })
                        yield sse_event("phase", {
                            "phase": new_phase,
                            "label": label,
                        })

                    # --- 结构化 todo 列表（来自 TodoListMiddleware 的 write_todos 状态）---
                    todos = chunk.get("todos")
                    if todos is not None:
                        todos_sig = json.dumps(todos, ensure_ascii=False, sort_keys=True)
                        if todos_sig != last_todos_sig:
                            last_todos_sig = todos_sig
                            plan_items = [
                                {
                                    "id": f"todo-{i}",
                                    "content": t.get("content", ""),
                                    "status": t.get("status", "pending"),
                                }
                                for i, t in enumerate(todos)
                            ]
                            if plan_items:
                                yield sse_event("todo_update", {
                                    "phase": "planning",
                                    "todos": plan_items,
                                })

                    # --- 中断检测（langgraph>=0.2 中断键名为 __interrupt__，兼容旧键 interrupts）---
                    interrupt_items = chunk.get("__interrupt__") or chunk.get("interrupts")
                    if interrupt_items:
                        for interrupt_item in interrupt_items:
                            interrupt_value = (
                                interrupt_item.value
                                if hasattr(interrupt_item, "value")
                                else interrupt_item
                            )
                            interrupt_data = _format_interrupt_data(interrupt_value)
                            if interrupt_data:
                                yield sse_event("interrupt", interrupt_data)

                        # 保存当前累积的消息
                        if assistant_content:
                            display_messages.append({
                                "id": str(uuid.uuid4()),
                                "role": "assistant",
                                "content": assistant_content,
                                "toolCalls": tool_calls_buffer,
                                "timestamp": datetime.now().isoformat(),
                            })
                        await agent_loader.save_display_messages(thread_id, display_messages)
                        await agent_loader.save_harness_trace(thread_id, harness_trace)
                        yield sse_event("done", {"thread_id": thread_id, "interrupted": True})
                        return
                continue

            # ===== Custom 流处理（评审器等中间件的结构化事件）=====
            if chunk_type == "custom":
                if isinstance(chunk, dict):
                    ev_type = chunk.get("type", "")
                    if ev_type == "rubric_evaluation_start":
                        # 评审器开始 grading → 进入审查阶段
                        if phase != "reviewing":
                            phase = "reviewing"
                            last_phase = "reviewing"
                            yield sse_event("phase", {"phase": "reviewing", "label": "🔍 审查中"})
                    elif ev_type == "rubric_evaluation_end":
                        # 评审器产出结构化判定 → 发射 review_result 事件
                        review_data = {
                            "verdict": chunk.get("result", ""),
                            "explanation": chunk.get("explanation", ""),
                            "criteria": chunk.get("criteria", []),
                            "iteration": chunk.get("iteration", 0),
                        }
                        harness_trace.append({
                            "type": "review",
                            **review_data,
                            "timestamp": datetime.now().isoformat(),
                        })
                        yield sse_event("review_result", review_data)
                continue

            # ===== Messages 流处理 =====
            if chunk_type == "messages":
                # Routing output is internal control data, never assistant text
                # or a user-visible tool invocation.
                metadata = chunk[1] if isinstance(chunk, (tuple, list)) and len(chunk) > 1 else {}
                if isinstance(metadata, dict) and "review_router" in (metadata.get("tags") or []):
                    continue
                # chunk 格式: (message_chunk, metadata_dict)
                if isinstance(chunk, (list, tuple)) and len(chunk) >= 1:
                    token = chunk[0]
                else:
                    token = chunk

                if token is None:
                    continue

                token_type = getattr(token, "type", "")
                content = getattr(token, "content", "")
                tool_call_chunks = getattr(token, "tool_call_chunks", None)

                # AIMessage with tool_call_chunks → tool_start / tool_args
                if tool_call_chunks:
                    # 首次收到工具调用时结束 thinking 状态
                    if not thinking_emitted:
                        yield sse_event("thinking", {"status": "end"})
                        thinking_emitted = True
                    for tc in tool_call_chunks:
                        if isinstance(tc, dict):
                            if tc.get("name"):
                                tool_calls_buffer.append({
                                    "id": tc.get("id", str(uuid.uuid4())),
                                    "name": tc["name"],
                                    "args": "",
                                    "status": "running",
                                })
                                yield sse_event("tool_start", {
                                    "name": tc["name"],
                                    "id": tc.get("id", ""),
                                })
                            if tc.get("args"):
                                # 追加到最近的 tool_call
                                if tool_calls_buffer:
                                    tool_calls_buffer[-1]["args"] += tc["args"]
                                yield sse_event("tool_args", {"args": tc["args"]})
                    continue

                # ToolMessage → tool_result / tool_end
                if token_type == "tool":
                    tool_name = getattr(token, "name", "unknown")
                    tool_content = content if isinstance(content, str) else str(content)
                    tool_call_id = getattr(token, "tool_call_id", "")
                    # 并行调用多个同名工具时必须按 tool_call_id 对应结果；仅在旧
                    # 模型未返回 id 时才按名称回退，否则图表标题和图片会互相串位。
                    matched_call = next(
                        (
                            tc
                            for tc in tool_calls_buffer
                            if tool_call_id and tc["id"] == tool_call_id
                        ),
                        None,
                    )
                    if matched_call is None:
                        matched_call = next(
                            (
                                tc
                                for tc in tool_calls_buffer
                                if tc["name"] == tool_name and tc["status"] == "running"
                            ),
                            None,
                        )
                    if matched_call is not None:
                        matched_call["result"] = tool_content[:1000]
                        matched_call["status"] = "done"

                    # 检测 TODO 工具调用，发射任务列表更新事件
                    if "todo" in tool_name.lower() or "task" in tool_name.lower():
                        try:
                            # 尝试从工具参数中提取 todo 列表
                            todo_args = None
                            for tc in tool_calls_buffer:
                                if tc["name"] == tool_name and tc.get("args"):
                                    todo_args = tc["args"]
                                    break
                            if todo_args:
                                yield sse_event("todo_update", {
                                    "tool": tool_name,
                                    "args": todo_args[:2000],
                                    "result": tool_content[:500],
                                })
                        except Exception:
                            pass

                    yield sse_event("tool_result", {
                        "name": tool_name,
                        "content": tool_content[:2000],
                    })
                    yield sse_event("tool_end", {
                        "id": getattr(token, "tool_call_id", ""),
                    })
                    continue

                # AIMessage 纯文本 → token 事件
                if content and isinstance(content, str) and content.strip():
                    # 首次收到 token 时结束 thinking
                    if not thinking_emitted:
                        yield sse_event("thinking", {"status": "end"})
                        thinking_emitted = True
                    assistant_content += content

                    # 判断来源（通过 namespace 元组）
                    source = "main"
                    if namespace:
                        ns_str = str(namespace)
                        if "analyst" in ns_str:
                            source = "analyst"
                        elif "order" in ns_str:
                            source = "order"
                    yield sse_event("token", {"content": content, "source": source})

        # ===== 流正常结束 =====
        if assistant_content:
            display_messages.append({
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": assistant_content,
                "toolCalls": tool_calls_buffer if tool_calls_buffer else None,
                "timestamp": datetime.now().isoformat(),
            })

        await agent_loader.save_display_messages(thread_id, display_messages)
        await agent_loader.save_harness_trace(thread_id, harness_trace)

        # 自动生成会话标题（首条消息前20字）
        if message:
            title = message[:20] + "..." if len(message) > 20 else message
            await agent_loader.save_conversation(thread_id, user_id, title)

        yield sse_event("done", {"thread_id": thread_id, "interrupted": False})

    except Exception as e:
        web_logger.error(f"Stream error for thread {thread_id}: {e}", exc_info=True)
        yield sse_event("error", {"message": f"服务内部错误: {str(e)[:200]}"})
        yield sse_event("done", {"thread_id": thread_id, "interrupted": False})
    finally:
        reset_runtime(runtime_tokens)
        reset_sandbox(sandbox_token)
        if lease_acquired:
            sandbox_manager.release_lease(user_id)
        session.run_lock.release()


def _remove_background_stream_task(task: asyncio.Task[None]) -> None:
    """回收已完成的后台流任务，并记录生成器之外的意外异常。"""
    _background_stream_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        web_logger.error("Detached chat stream failed", exc_info=error)


async def resilient_stream_chat_response(**kwargs) -> AsyncGenerator[str, None]:
    """让 Agent 的生命周期独立于浏览器 SSE 连接。

    Starlette 会在刷新页面、切换会话或网络抖动时关闭响应生成器。若直接把
    ``stream_chat_response`` 交给 StreamingResponse，这个取消信号会沿调用链
    终止 LangGraph。这里由独立任务执行 Agent，当前连接只负责消费事件；连接
    断开后停止排队 SSE 数据，但后台任务继续运行并持久化最终展示消息。
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    client_connected = asyncio.Event()
    client_connected.set()

    async def produce() -> None:
        try:
            async for chunk in stream_chat_response(**kwargs):
                if client_connected.is_set():
                    queue.put_nowait(chunk)
        finally:
            if client_connected.is_set():
                queue.put_nowait(None)

    producer = asyncio.create_task(produce())
    _background_stream_tasks.add(producer)
    producer.add_done_callback(_remove_background_stream_task)
    stream_finished = False

    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                stream_finished = True
                break
            yield chunk
    finally:
        client_connected.clear()
        if not stream_finished and not producer.done():
            web_logger.warning(
                "SSE client disconnected for thread %s; Agent continues in background",
                kwargs.get("thread_id", "unknown"),
            )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    authenticated: str | None = Depends(current_user_id),
):
    """SSE 流式对话端点"""
    await agent_loader.initialize()

    # 认证身份优先；request.user_id 只在 AUTH_MODE=none 时生效。
    user_id = resolve_user_id(authenticated, request.user_id)

    thread_id = request.thread_id or agent_loader.generate_thread_id()
    existing_owner = await agent_loader.get_conversation_user_id(thread_id)
    if existing_owner and existing_owner != user_id:
        raise HTTPException(status_code=403, detail="该会话不属于当前用户")
    if existing_owner is None:
        # 归属记录为空时不能再像以前那样直接放行。这里是唯一允许"认领"新
        # thread 的端点（其余四个 resume / state / history / delete 都走
        # assert_thread_owner，owner 为空一律 403），所以漏在这里等于给出一条
        # 认领通道：会话记录与展示消息是两张表，删除会话或某一侧写入失败都会
        # 留下「有消息但没有归属」的孤儿 thread，任何知道该 thread_id 的人 POST
        # 一次就能把归属改成自己，并让 checkpoint 里上一位用户的历史进入自己的
        # 上下文。全新 thread 不会有展示消息，据此区分。
        if await agent_loader.get_display_messages(thread_id):
            web_logger.warning(
                f"Denied claiming orphaned thread {thread_id}: messages exist but "
                f"no conversation owner record (requester={user_id!r})"
            )
            raise HTTPException(status_code=403, detail="该会话不属于当前用户")

    # 在流开始时就记录归属，确保在中断后 resume 能找到同一个用户沙箱。
    title = request.message[:20] + "..." if len(request.message) > 20 else request.message
    await agent_loader.save_conversation(thread_id, user_id, title)

    return StreamingResponse(
        resilient_stream_chat_response(
            message=request.message,
            thread_id=thread_id,
            user_id=user_id,
            username=request.username,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Thread-Id": thread_id,
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{thread_id}/resume")
async def chat_resume(
    thread_id: str,
    request: ResumeRequest,
    authenticated: str | None = Depends(current_user_id),
):
    """中断恢复端点"""
    await agent_loader.initialize()
    owner = await agent_loader.get_conversation_user_id(thread_id)
    assert_thread_owner(thread_id, owner, authenticated)
    user_id = authenticated or owner or "default_user"

    decisions = request.resume.get("decisions")
    if isinstance(decisions, list):
        try:
            await asyncio.to_thread(
                agent_loader.write_audit_repository.mark_thread_decisions,
                thread_id,
                decisions=decisions,
                actor_id=user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            web_logger.error("Failed to persist approval decision: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="审批审计保存失败，写操作未恢复",
            ) from exc

    return StreamingResponse(
        resilient_stream_chat_response(
            message="",
            thread_id=thread_id,
            user_id=user_id,
            resume_data=request.resume,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Thread-Id": thread_id,
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{thread_id}/state")
async def chat_state(
    thread_id: str,
    authenticated: str | None = Depends(current_user_id),
):
    """获取 Agent 状态（是否处于中断中）"""
    await agent_loader.initialize()
    owner = await agent_loader.get_conversation_user_id(thread_id)
    assert_thread_owner(thread_id, owner, authenticated)
    user_id = authenticated or owner or "default_user"
    session = await agent_loader.get_session(user_id)
    config = agent_loader.create_config(thread_id, user_id)
    try:
        state = await session.agent.aget_state(config)
        interrupt_data = None
        if state:
            for task in getattr(state, "tasks", ()):
                for interrupt_item in getattr(task, "interrupts", ()):
                    interrupt_value = (
                        interrupt_item.value
                        if hasattr(interrupt_item, "value")
                        else interrupt_item
                    )
                    interrupt_data = _format_interrupt_data(interrupt_value)
                    if interrupt_data:
                        break
                if interrupt_data:
                    break
        return {
            "thread_id": thread_id,
            "interrupted": interrupt_data is not None,
            "interrupt_data": interrupt_data,
            "pending": bool(state.next) if state else False,
        }
    except Exception:
        return {
            "thread_id": thread_id,
            "interrupted": False,
            "interrupt_data": None,
            "pending": False,
        }


@router.get("/{thread_id}/history")
async def chat_history(
    thread_id: str,
    authenticated: str | None = Depends(current_user_id),
):
    """获取对话消息历史"""
    owner = await agent_loader.get_conversation_user_id(thread_id)
    assert_thread_owner(thread_id, owner, authenticated)
    messages = await agent_loader.get_display_messages(thread_id)
    return {"thread_id": thread_id, "messages": messages}
