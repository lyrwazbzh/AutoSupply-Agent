"use client";

import LoginPage from "./LoginPage";
import { useAuth } from "./AuthProvider";

export default function RequireAuth({ children, permission }: { children: React.ReactNode; permission?: string }) {
  const { user, loading, hasPermission } = useAuth();
  if (loading) return <main className="min-h-screen grid place-items-center text-slate-500">正在恢复安全会话…</main>;
  if (!user) return <LoginPage />;
  if (permission && !hasPermission(permission)) {
    return <main className="min-h-screen grid place-items-center"><div className="text-center"><h1 className="text-xl font-semibold">无权访问</h1><p className="mt-2 text-slate-500">当前角色缺少 {permission} 权限。</p></div></main>;
  }
  return <>{children}</>;
}
