"use client";

import ReactMarkdown from "react-markdown";
import { Bot, User } from "lucide-react";
import { ChatMessage } from "@/lib/types";
import { extractChartPreviews } from "@/lib/chart-preview";
import ToolCallDisplay from "./ToolCallDisplay";
import StreamingText from "./StreamingText";

interface Props {
  message: ChatMessage;
  isStreaming?: boolean;
  showToolCalls?: boolean;
}

export default function MessageBubble({
  message,
  isStreaming,
  showToolCalls = true,
}: Props) {
  const isUser = message.role === "user";
  const chartPreviews = isUser ? [] : extractChartPreviews(message.toolCalls);

  return (
    <div
      className={`flex gap-3 animate-fade-in ${isUser ? "justify-end" : "justify-start"}`}
    >
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0 mt-1">
          <Bot size={16} className="text-blue-600" />
        </div>
      )}

      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-[#2563EB] text-white rounded-br-md"
            : "bg-white border border-gray-200 text-gray-800 rounded-bl-md shadow-sm"
        }`}
      >
        {/* 工具调用展示 */}
        {!isUser && showToolCalls && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2">
            {message.toolCalls.map((tc) => (
              <ToolCallDisplay key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}

        {chartPreviews.length > 0 && (
          <div className="mb-3 grid grid-cols-1 gap-3">
            {chartPreviews.map((preview) => (
              <a
                key={preview.url}
                href={preview.url}
                target="_blank"
                rel="noreferrer"
                className="block overflow-hidden rounded-lg border border-gray-200 bg-gray-50"
              >
                {/* 原生 img 可展示运行时动态生成、无需预先配置域名的图片。 */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={preview.url}
                  alt={preview.title}
                  loading="lazy"
                  className="w-full h-auto object-contain"
                />
                <span className="block px-3 py-2 text-xs text-gray-600">
                  {preview.title}
                </span>
              </a>
            ))}
          </div>
        )}

        {/* 消息内容 */}
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        ) : isStreaming && !message.content ? (
          <StreamingText text="" />
        ) : isStreaming ? (
          <div className="text-sm markdown-body">
            <StreamingText text={message.content} />
          </div>
        ) : (
          <div className="text-sm markdown-body">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}

        {/* 来源标识 */}
        {!isUser && message.source && message.source !== "main" && (
          <div className="mt-2 pt-1.5 border-t border-gray-100">
            <span className="text-[10px] text-gray-400">
              来自: {message.source === "analyst" ? "采购分析专家" : "采购订单专家"}
            </span>
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center shrink-0 mt-1">
          <User size={16} className="text-gray-600" />
        </div>
      )}
    </div>
  );
}
