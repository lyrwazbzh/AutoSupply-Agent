"use client";

import { Conversation } from "@/lib/types";
import Logo from "./Logo";
import NewChatButton from "./NewChatButton";
import SearchBox from "./SearchBox";
import HistoryList from "./HistoryList";
import Link from "next/link";
import { LayoutDashboard, LogOut, ShieldCheck } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";

interface Props {
  conversations: Conversation[];
  activeThreadId: string;
  searchQuery: string;
  onSearchChange: (v: string) => void;
  onNewChat: () => void;
  onSelectThread: (id: string) => void;
  onDeleteThread: (id: string) => void;
}

export default function Sidebar({
  conversations,
  activeThreadId,
  searchQuery,
  onSearchChange,
  onNewChat,
  onSelectThread,
  onDeleteThread,
}: Props) {
  const { user, logout, hasPermission } = useAuth();
  return (
    <aside className="w-[280px] h-screen flex flex-col bg-[#F9FAFB] border-r border-gray-200 shrink-0">
      <Logo />
      <div className="px-3 pb-3 space-y-1">
        <Link href="/erp" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-200"><LayoutDashboard size={16}/>ERP 管理后台</Link>
        {hasPermission("system:user:read") && <Link href="/admin/security" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-200"><ShieldCheck size={16}/>用户与权限</Link>}
      </div>
      <NewChatButton onClick={onNewChat} />
      <SearchBox value={searchQuery} onChange={onSearchChange} />
      <HistoryList
        conversations={conversations}
        activeThreadId={activeThreadId}
        onSelect={onSelectThread}
        onDelete={onDeleteThread}
      />
      <div className="px-4 py-3 border-t border-gray-200">
        <p className="truncate text-xs font-medium text-slate-700">{user?.displayName || user?.username}</p>
        <div className="mt-1 flex items-center justify-between"><span className="text-[11px] text-gray-400">DeepAgent v1.0.0</span><button aria-label="退出登录" onClick={() => void logout()} className="text-slate-400 hover:text-slate-700"><LogOut size={14}/></button></div>
      </div>
    </aside>
  );
}
