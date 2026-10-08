// ===== SSE 事件类型 =====
export interface SSETokenEvent {
  type: "token";
  content: string;
  source: "main" | "analyst" | "order";
}

export interface SSEToolStartEvent {
  type: "tool_start";
  name: string;
  id: string;
}

export interface SSEToolArgsEvent {
  type: "tool_args";
  args: string;
}

export interface SSEToolResultEvent {
  type: "tool_result";
  name: string;
  content: string;
}

export interface SSEToolEndEvent {
  type: "tool_end";
  id: string;
}

export interface SSEInterruptEvent {
  type: "interrupt";
  interrupt_type: "hitl_approval" | "order_info_supplement";
  data: InterruptData;
}

export interface SSEDoneEvent {
  type: "done";
  thread_id: string;
  interrupted: boolean;
}

export interface SSEThinkingEvent {
  type: "thinking";
  status: "start" | "end";
}

export interface SSETodoUpdateEvent {
  type: "todo_update";
  phase?: string;
  todos?: { id: string; content: string; status: string }[];
  status_change?: string;
  // legacy fields
  tool?: string;
  args?: string;
  result?: string;
}

export interface SSEPhaseEvent {
  type: "phase";
  phase: "thinking" | "planning" | "executing" | "reviewing" | "done";
  label: string;
}

export interface SSEAgentDispatchEvent {
  type: "agent_dispatch";
  phase: "start" | "end";
  call_id: string;
  agent?: string;
  started_at?: string;
  finished_at?: string;
  elapsed_ms?: number;
  status?: string;
  error?: string | null;
  missing_sections?: string[];
  evidence_gaps?: string[];
  filled_fields?: string[];
  active_parallel?: number;
  max_parallel?: number;
  timeout_s?: number;
  description_chars?: number;
}

export type SSEEvent =
  | SSETokenEvent
  | SSEToolStartEvent
  | SSEToolArgsEvent
  | SSEToolResultEvent
  | SSEToolEndEvent
  | SSEInterruptEvent
  | SSEDoneEvent
  | SSEThinkingEvent
  | SSETodoUpdateEvent
  | SSEPhaseEvent
  | SSEAgentDispatchEvent;

// ===== 中断数据 =====
export interface InterruptData {
  interrupt_type: string;
  // order_info_supplement
  extracted_data?: Record<string, unknown>;
  missing_fields?: string[];
  message?: string;
  // hitl_approval
  order_data?: Record<string, unknown>;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  // 制造供应链审批：RFQ、定点、订单或交付计划等
  business_type?: string;
  approval_summary?: Record<string, unknown>;
  risk_items?: { level: "low" | "medium" | "high"; message: string }[];
}

// ===== 消息类型 =====
export interface ToolCallInfo {
  id: string;
  name: string;
  args: string;
  result?: string;
  status: "running" | "done" | "error";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source?: string;
  toolCalls?: ToolCallInfo[];
  timestamp: number;
}

// ===== TODO 任务列表 =====
export interface TodoItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "complete" | "cancelled";
}

export interface TodoState {
  items: TodoItem[];
  visible: boolean;
}

// ===== 会话历史 =====
export interface Conversation {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

// ===== 请求/响应 =====
export interface ChatRequest {
  message: string;
  thread_id: string;
  user_id: string;
  username: string;
}

export interface ResumeRequest {
  thread_id: string;
  resume_data: Record<string, unknown>;
}

// ===== 功能卡片 =====
export interface CapabilityCard {
  icon: string;
  title: string;
  description: string;
  prompt: string;
}
