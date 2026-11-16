"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bike,
  Bot,
  Boxes,
  ClipboardList,
  ClipboardCheck,
  FileClock,
  LayoutDashboard,
  LogOut,
  PackageSearch,
  RotateCcw,
  ShieldCheck,
  ShoppingCart,
} from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { erpJson } from "@/lib/auth";

const groups = [
  {
    label: "工作台",
    items: [
      { href: "/erp", label: "经营概览", icon: LayoutDashboard, permission: "erp:statistics:read" },
      { href: "/", label: "智能助手", icon: Bot },
    ],
  },
  {
    label: "采购与库存",
    items: [
      { href: "/erp/catalog", label: "报价与车型适配", icon: Bike, permission: "erp:supplier-part:read" },
      { href: "/erp/orders", label: "采购订单", icon: ShoppingCart, permission: "erp:order:read" },
      { href: "/erp/replenishment", label: "补货任务", icon: PackageSearch, permission: "erp:replenishment:read" },
      { href: "/erp/inventory", label: "库存管理", icon: Boxes, permission: "erp:inventory:read" },
      { href: "/erp/inventory/transactions", label: "库存流水", icon: FileClock, permission: "erp:inventory:transaction:read" },
      { href: "/erp/returns", label: "采购退货", icon: RotateCcw, permission: "erp:order:read" },
    ],
  },
  {
    label: "治理",
    items: [
      { href: "/audit", label: "操作审计", icon: ClipboardList, permission: "audit:read:self" },
      { href: "/admin/approvals", label: "写操作审批", icon: ClipboardCheck, permission: "erp:order:approve" },
      { href: "/admin/security", label: "用户与权限", icon: ShieldCheck, permission: "system:user:read" },
    ],
  },
];

export default function ManagementShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout, hasPermission } = useAuth();
  async function changePassword() {
    const currentPassword = window.prompt("请输入当前密码");
    if (!currentPassword) return;
    const newPassword = window.prompt("请输入新密码（至少 10 位）");
    if (!newPassword) return;
    try {
      await erpJson("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      window.alert("密码已修改，请重新登录。");
      await logout();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "修改密码失败");
    }
  }
  return (
    <div className="flex min-h-screen bg-slate-100">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col bg-slate-950 text-slate-200">
        <div className="border-b border-slate-800 px-6 py-5">
          <p className="text-xs tracking-[0.2em] text-blue-400">MOTORPARTS</p>
          <h1 className="mt-1 font-semibold text-white">ERP 管理中心</h1>
        </div>
        <nav className="flex-1 space-y-5 overflow-y-auto p-3">
          {groups.map((group) => {
            const visibleItems = group.items.filter((item) => !item.permission || hasPermission(item.permission));
            if (!visibleItems.length) return null;
            return (
              <section key={group.label}>
                <p className="mb-1 px-3 text-[11px] font-medium tracking-wider text-slate-500">{group.label}</p>
                <div className="space-y-1">
                  {visibleItems.map(({ href, label, icon: Icon }) => {
                    const exactOnly = href === "/" || href === "/erp" || href === "/erp/inventory";
                    const active = exactOnly ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
                    return (
                      <Link key={href} href={href} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${active ? "bg-blue-600 text-white" : "hover:bg-slate-800"}`}>
                        <Icon size={17} />{label}
                      </Link>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </nav>
        <div className="border-t border-slate-800 p-4">
          <p className="truncate text-sm font-medium text-white">{user?.displayName || user?.username}</p>
          <p className="mt-1 truncate text-xs text-slate-400">{user?.roles.join(" · ")}</p>
          <button className="mt-3 flex items-center gap-2 text-xs text-slate-300 hover:text-white" onClick={() => void changePassword()}><ShieldCheck size={14} />修改密码</button>
          <button className="mt-3 flex items-center gap-2 text-xs text-slate-300 hover:text-white" onClick={() => void logout()}><LogOut size={14} />退出登录</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
