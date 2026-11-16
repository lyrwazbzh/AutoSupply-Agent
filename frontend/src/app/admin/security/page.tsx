"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import RequireAuth from "@/components/auth/RequireAuth";
import ManagementShell from "@/components/erp/ManagementShell";
import { useAuth } from "@/components/auth/AuthProvider";
import { erpJson } from "@/lib/auth";

interface UserRow {
  id: number;
  username: string;
  real_name?: string;
  status: number;
  authz_version: number;
}

interface RoleRow {
  id: number;
  code: string;
  name: string;
  description?: string;
  built_in: number;
  permission_count: number;
}

interface PermissionRow {
  code: string;
  name: string;
  resource: string;
}

export default function SecurityAdminPage() {
  const { hasPermission } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [permissions, setPermissions] = useState<PermissionRow[]>([]);
  const [selectedRole, setSelectedRole] = useState<RoleRow | null>(null);
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState<UserRow | null>(null);
  const [selectedUserRoles, setSelectedUserRoles] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [showCreateRole, setShowCreateRole] = useState(false);

  const canManageUsers = hasPermission("system:user:manage");
  const canManageRoles = hasPermission("system:role:manage");

  const load = useCallback(async () => {
    try {
      const [nextUsers, nextRoles, nextPermissions] = await Promise.all([
        erpJson<UserRow[]>("/admin/users"),
        erpJson<RoleRow[]>("/admin/roles"),
        erpJson<PermissionRow[]>("/admin/permissions"),
      ]);
      setUsers(nextUsers);
      setRoles(nextRoles);
      setPermissions(nextPermissions);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function run(action: () => Promise<void>, fallback: string) {
    try {
      setError("");
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    }
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      await erpJson("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          displayName: form.get("displayName"),
          password: form.get("password"),
          roles: [form.get("role")],
        }),
      });
      formElement.reset();
      setShowCreateUser(false);
      await load();
    }, "创建用户失败");
  }

  async function createRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await run(async () => {
      await erpJson("/admin/roles", {
        method: "POST",
        body: JSON.stringify({
          code: form.get("code"),
          name: form.get("name"),
          description: form.get("description"),
        }),
      });
      formElement.reset();
      setShowCreateRole(false);
      await load();
    }, "创建角色失败");
  }

  async function toggleUser(user: UserRow) {
    await run(async () => {
      await erpJson(`/admin/users/${user.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: user.status === 1 ? 2 : 1 }),
      });
      await load();
    }, "修改用户状态失败");
  }

  async function editUserRoles(user: UserRow) {
    await run(async () => {
      setSelectedUser(user);
      setSelectedUserRoles(await erpJson<string[]>(`/admin/users/${user.id}/roles`));
    }, "读取用户角色失败");
  }

  async function saveUserRoles() {
    if (!selectedUser) return;
    await run(async () => {
      await erpJson(`/admin/users/${selectedUser.id}/roles`, {
        method: "PUT",
        body: JSON.stringify({ codes: selectedUserRoles }),
      });
      setSelectedUser(null);
      await load();
    }, "保存用户角色失败");
  }

  async function resetPassword(user: UserRow) {
    const password = window.prompt(`为 ${user.username} 设置新密码（至少 10 位）`);
    if (!password) return;
    await run(async () => {
      await erpJson(`/admin/users/${user.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      window.alert("密码已重置，该用户的现有会话已失效。");
      await load();
    }, "重置密码失败");
  }

  async function editPermissions(role: RoleRow) {
    if (role.built_in) return;
    await run(async () => {
      setSelectedRole(role);
      setSelectedPermissions(await erpJson<string[]>(`/admin/roles/${role.id}/permissions`));
    }, "读取角色权限失败");
  }

  async function savePermissions() {
    if (!selectedRole) return;
    await run(async () => {
      await erpJson(`/admin/roles/${selectedRole.id}/permissions`, {
        method: "PUT",
        body: JSON.stringify({ codes: selectedPermissions }),
      });
      setSelectedRole(null);
      await load();
    }, "保存角色权限失败");
  }

  async function deleteRole(role: RoleRow) {
    if (role.built_in || !window.confirm(`确认删除自定义角色 ${role.name}？`)) return;
    await run(async () => {
      await erpJson(`/admin/roles/${role.id}`, { method: "DELETE" });
      await load();
    }, "删除角色失败");
  }

  return (
    <RequireAuth permission="system:user:read">
      <RequireAuth permission="system:role:read">
        <ManagementShell>
          <header className="flex items-center justify-between border-b bg-white px-8 py-5">
            <div>
              <h2 className="text-xl font-semibold">用户、角色与权限</h2>
              <p className="mt-1 text-sm text-slate-500">
                改权、停用和重置密码都会使该用户的现有会话立即失效。
              </p>
            </div>
            <div className="flex gap-2">
              {canManageRoles && <button onClick={() => setShowCreateRole((value) => !value)} className="rounded-lg border px-4 py-2 text-sm">新建角色</button>}
              {canManageUsers && <button onClick={() => setShowCreateUser((value) => !value)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">新建用户</button>}
            </div>
          </header>

          <div className="space-y-6 p-8">
            {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

            {showCreateUser && (
              <form onSubmit={createUser} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-5">
                <input required name="username" placeholder="用户名" className="rounded border px-3 py-2" />
                <input name="displayName" placeholder="姓名" className="rounded border px-3 py-2" />
                <input required minLength={10} type="password" name="password" placeholder="初始密码（至少 10 位）" className="rounded border px-3 py-2" />
                <select name="role" className="rounded border px-3 py-2">{roles.map((role) => <option key={role.code}>{role.code}</option>)}</select>
                <button className="rounded bg-slate-900 text-white">创建</button>
              </form>
            )}

            {showCreateRole && (
              <form onSubmit={createRole} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-4">
                <input required name="code" pattern="[A-Za-z][A-Za-z0-9_]{2,63}" placeholder="角色编码，如 AUDITOR" className="rounded border px-3 py-2" />
                <input required name="name" placeholder="角色名称" className="rounded border px-3 py-2" />
                <input name="description" placeholder="说明" className="rounded border px-3 py-2" />
                <button className="rounded bg-slate-900 text-white">创建后配置权限</button>
              </form>
            )}

            <section className="rounded-xl border bg-white">
              <div className="border-b px-5 py-4 font-semibold">用户</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">用户名</th><th className="p-3">姓名</th><th className="p-3">状态</th><th className="p-3">权限版本</th><th className="p-3">操作</th></tr></thead>
                  <tbody>{users.map((user) => (
                    <tr key={user.id} className="border-t">
                      <td className="p-3 font-medium">{user.username}</td><td className="p-3">{user.real_name || "—"}</td><td className="p-3">{user.status === 1 ? "启用" : "停用"}</td><td className="p-3">v{user.authz_version}</td>
                      <td className="p-3"><div className="flex gap-3">
                        {canManageUsers && <button onClick={() => void editUserRoles(user)} className="text-blue-600">角色</button>}
                        {canManageUsers && <button onClick={() => void resetPassword(user)} className="text-blue-600">重置密码</button>}
                        {canManageUsers && <button onClick={() => void toggleUser(user)} className="text-blue-600">{user.status === 1 ? "停用" : "启用"}</button>}
                      </div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </section>

            <section className="rounded-xl border bg-white">
              <div className="border-b px-5 py-4 font-semibold">角色</div>
              <div className="grid gap-3 p-5 md:grid-cols-2">{roles.map((role) => (
                <article key={role.id} className="flex items-center justify-between rounded-lg border p-4">
                  <div><p className="font-medium">{role.name} <span className="text-xs text-slate-400">{role.code}</span></p><p className="mt-1 text-xs text-slate-500">{role.permission_count} 项权限 · {role.built_in ? "内置" : "自定义"}</p></div>
                  <div className="flex gap-3">
                    <button disabled={Boolean(role.built_in) || !canManageRoles} onClick={() => void editPermissions(role)} className="text-sm text-blue-600 disabled:text-slate-400">{role.built_in ? "权限固定" : "配置权限"}</button>
                    {!role.built_in && canManageRoles && <button onClick={() => void deleteRole(role)} className="text-sm text-red-600">删除</button>}
                  </div>
                </article>
              ))}</div>
            </section>

            {selectedUser && (
              <Modal title={`配置 ${selectedUser.username} 的角色`} onClose={() => setSelectedUser(null)} onSave={() => void saveUserRoles()}>
                <div className="grid gap-2 md:grid-cols-2">{roles.map((role) => <CheckRow key={role.code} checked={selectedUserRoles.includes(role.code)} title={role.name} code={role.code} onChange={(checked) => setSelectedUserRoles((current) => checked ? [...current, role.code] : current.filter((code) => code !== role.code))} />)}</div>
              </Modal>
            )}

            {selectedRole && (
              <Modal title={`配置 ${selectedRole.name} 的权限`} onClose={() => setSelectedRole(null)} onSave={() => void savePermissions()}>
                <div className="grid gap-2 md:grid-cols-2">{permissions.map((permission) => <CheckRow key={permission.code} checked={selectedPermissions.includes(permission.code)} title={permission.name} code={permission.code} onChange={(checked) => setSelectedPermissions((current) => checked ? [...current, permission.code] : current.filter((code) => code !== permission.code))} />)}</div>
              </Modal>
            )}
          </div>
        </ManagementShell>
      </RequireAuth>
    </RequireAuth>
  );
}

function CheckRow({ checked, title, code, onChange }: { checked: boolean; title: string; code: string; onChange: (checked: boolean) => void }) {
  return <label className="flex gap-2 rounded border p-3 text-sm"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{title}<small className="block text-slate-400">{code}</small></span></label>;
}

function Modal({ title, children, onClose, onSave }: { title: string; children: React.ReactNode; onClose: () => void; onSave: () => void }) {
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-6"><section className="max-h-[80vh] w-full max-w-3xl overflow-auto rounded-xl bg-white p-6"><h3 className="text-lg font-semibold">{title}</h3><div className="mt-5">{children}</div><div className="mt-5 flex justify-end gap-3"><button onClick={onClose} className="rounded border px-4 py-2">取消</button><button onClick={onSave} className="rounded bg-blue-600 px-4 py-2 text-white">保存并使会话失效</button></div></section></div>;
}
