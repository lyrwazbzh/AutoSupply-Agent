"use client";

import { useCallback, useEffect, useRef } from "react";
import Sidebar from "@/components/sidebar/Sidebar";
import ChatArea from "@/components/chat/ChatArea";
import { useChat } from "@/hooks/useChat";
import { useHistory } from "@/hooks/useHistory";
import { getChatState, getMessages } from "@/lib/api";
import { ChatMessage } from "@/lib/types";

export default function Home() {
  const chat = useChat();
  const history = useHistory();
  const wasStreaming = useRef(false);
  const refreshHistory = history.refresh;

  // 聊天结束后自动刷新历史列表
  useEffect(() => {
    const justFinished = wasStreaming.current && !chat.streaming;
    wasStreaming.current = chat.streaming;
    if (justFinished) {
      // 延迟 500ms 等待后端保存完成
      const timer = setTimeout(() => refreshHistory(), 500);
      return () => clearTimeout(timer);
    }
  }, [chat.streaming, refreshHistory]);

  const handleSelectThread = useCallback(
    async (threadId: string) => {
      // 当前回答期间，侧栏会因为会话已在后端登记而立刻出现同一个 thread。
      // 点击它不应 abort 正在运行的 SSE；切换其他历史也等当前轮结束再做。
      if (chat.streaming || threadId === chat.threadId) return;
      try {
        const [data, state] = await Promise.all([
          getMessages(threadId),
          getChatState(threadId).catch(() => null),
        ]);
        const msgs: ChatMessage[] = (data.messages || data || []).map(
          (m: Record<string, unknown>, idx: number) => ({
            id: (m.id as string) || `msg-${idx}`,
            role: (m.role as "user" | "assistant") || "assistant",
            content: (m.content as string) || "",
            source: m.source as string | undefined,
            toolCalls: m.toolCalls as ChatMessage["toolCalls"],
            timestamp: (m.timestamp as number) || Date.now(),
          })
        );
        chat.loadThread(
          threadId,
          msgs,
          state?.interrupted ? state.interrupt_data ?? null : null
        );
      } catch {
        // 加载失败静默处理
      }
    },
    [chat]
  );

  const handleDeleteThread = useCallback(
    (threadId: string) => {
      history.remove(threadId);
      if (threadId === chat.threadId) {
        chat.newChat();
      }
    },
    [history, chat]
  );

  const handleSupplement = useCallback(
    (text: string) => {
      chat.resumeWith({ supplement: text });
    },
    [chat]
  );

  const handleApprove = useCallback(() => {
    const operationIds = chat.interruptData?.operation_ids ?? [];
    chat.resumeWith({
      decisions: operationIds.map((operation_id) => ({ operation_id, type: "approve" })),
    });
  }, [chat]);

  const handleReject = useCallback(() => {
    const operationIds = chat.interruptData?.operation_ids ?? [];
    chat.resumeWith({
      decisions: operationIds.map((operation_id) => ({ operation_id, type: "reject" })),
    });
  }, [chat]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        conversations={history.conversations}
        activeThreadId={chat.threadId}
        searchQuery={history.searchQuery}
        onSearchChange={history.setSearchQuery}
        onNewChat={chat.newChat}
        onSelectThread={handleSelectThread}
        onDeleteThread={handleDeleteThread}
      />
      <ChatArea
        messages={chat.messages}
        streaming={chat.streaming}
        thinking={chat.thinking}
        interrupted={chat.interrupted}
        interruptData={chat.interruptData}
        todoItems={chat.todoItems}
        todoVisible={chat.todoVisible}
        pendingQueue={chat.pendingQueue}
        phase={chat.phase}
        phaseLabel={chat.phaseLabel}
        error={chat.error}
        onSend={chat.sendMessage}
        onSupplement={handleSupplement}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </div>
  );
}
