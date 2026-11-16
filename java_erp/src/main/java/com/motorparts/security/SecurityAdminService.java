package com.motorparts.security;

import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class SecurityAdminService {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder passwordEncoder;

    public List<Map<String, Object>> listUsers() {
        return jdbc.queryForList("SELECT id,auth_subject,username,real_name,department,email,status,authz_version,last_login_at,locked_until,create_time FROM `user` WHERE deleted=0 ORDER BY id");
    }

    public List<Map<String, Object>> listRoles() {
        return jdbc.queryForList("SELECT r.id,r.code,r.name,r.description,r.built_in,r.status,COUNT(DISTINCT rp.permission_id) permission_count FROM security_role r LEFT JOIN security_role_permission rp ON rp.role_id=r.id GROUP BY r.id ORDER BY r.built_in DESC,r.code");
    }

    public List<Map<String, Object>> listPermissions() {
        return jdbc.queryForList("SELECT id,code,name,resource,action,description FROM security_permission ORDER BY resource,action");
    }

    public List<String> rolesForUser(long userId) {
        return jdbc.queryForList("SELECT r.code FROM security_role r JOIN security_user_role ur ON ur.role_id=r.id WHERE ur.user_id=? ORDER BY r.code", String.class, userId);
    }

    public List<String> permissionsForRole(long roleId) {
        return jdbc.queryForList("SELECT p.code FROM security_permission p JOIN security_role_permission rp ON rp.permission_id=p.id WHERE rp.role_id=? ORDER BY p.code", String.class, roleId);
    }

    @Transactional
    public long createUser(String username, String displayName, String password, List<String> roles) {
        String subject = "usr_" + UUID.randomUUID().toString().replace("-", "");
        try {
            jdbc.update("INSERT INTO `user`(auth_subject,username,password,password_hash,real_name,role,status,deleted) VALUES(?,?,?, ?,?,'viewer',1,0)",
                    subject, username.trim(), "!", passwordEncoder.encode(password), displayName);
        } catch (DuplicateKeyException ex) {
            throw new IllegalArgumentException("用户名已经存在");
        }
        long userId = jdbc.queryForObject("SELECT id FROM `user` WHERE auth_subject=?", Long.class, subject);
        assignRoles(userId, roles == null || roles.isEmpty() ? List.of("VIEWER") : roles);
        return userId;
    }

    @Transactional
    public void assignRoles(long userId, List<String> roleCodes) {
        if (roleCodes == null || roleCodes.isEmpty()) throw new IllegalArgumentException("用户至少需要一个角色");
        Integer userExists = jdbc.queryForObject("SELECT COUNT(*) FROM `user` WHERE id=? AND deleted=0", Integer.class, userId);
        if (userExists == null || userExists != 1) throw new IllegalArgumentException("用户不存在");
        List<String> normalized = roleCodes.stream().filter(Objects::nonNull)
                .map(s -> s.trim().toUpperCase(Locale.ROOT)).filter(s -> !s.isEmpty()).distinct().toList();
        if (normalized.isEmpty()) throw new IllegalArgumentException("用户至少需要一个角色");
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM security_role WHERE code IN (" + placeholders(normalized.size()) + ") AND status=1", Integer.class, normalized.toArray());
        if (count == null || count != normalized.size()) throw new IllegalArgumentException("包含不存在或已禁用的角色");
        if (!normalized.contains("ADMIN") && isAdmin(userId) && activeAdminCount() <= 1)
            throw new IllegalArgumentException("不能移除最后一个可用管理员的 ADMIN 角色");
        jdbc.update("DELETE FROM security_user_role WHERE user_id=?", userId);
        for (String code : normalized) {
            jdbc.update("INSERT INTO security_user_role(user_id,role_id) SELECT ?,id FROM security_role WHERE code=?", userId, code);
        }
        invalidateUser(userId);
    }

    @Transactional
    public void setUserStatus(long userId, int status) {
        if (status != 1 && status != 2) throw new IllegalArgumentException("status 只能为 1 或 2");
        if (status == 2 && isAdmin(userId) && activeAdminCount() <= 1)
            throw new IllegalArgumentException("不能停用最后一个可用管理员");
        if (jdbc.update("UPDATE `user` SET status=?,authz_version=authz_version+1 WHERE id=? AND deleted=0", status, userId) != 1)
            throw new IllegalArgumentException("用户不存在");
        revokeSessions(userId);
    }

    @Transactional
    public void resetPassword(long userId, String password) {
        if (password == null || password.length() < 10) throw new IllegalArgumentException("密码至少 10 位");
        if (jdbc.update("UPDATE `user` SET password='!',password_hash=?,password_changed_at=NOW(),failed_login_count=0,locked_until=NULL,authz_version=authz_version+1 WHERE id=? AND deleted=0", passwordEncoder.encode(password), userId) != 1)
            throw new IllegalArgumentException("用户不存在");
        revokeSessions(userId);
    }

    @Transactional
    public long createRole(String code, String name, String description) {
        String normalized = code == null ? "" : code.trim().toUpperCase(Locale.ROOT);
        if (!normalized.matches("[A-Z][A-Z0-9_]{2,63}")) throw new IllegalArgumentException("角色编码格式无效");
        try {
            jdbc.update("INSERT INTO security_role(code,name,description,built_in,status) VALUES(?,?,?,0,1)", normalized, name, description);
        } catch (DuplicateKeyException ex) {
            throw new IllegalArgumentException("角色编码已经存在");
        }
        return jdbc.queryForObject("SELECT id FROM security_role WHERE code=?", Long.class, normalized);
    }

    @Transactional
    public void assignPermissions(long roleId, List<String> permissionCodes) {
        List<Integer> roleFlags = jdbc.queryForList("SELECT built_in FROM security_role WHERE id=?", Integer.class, roleId);
        if (roleFlags.isEmpty()) throw new IllegalArgumentException("角色不存在");
        Integer builtIn = roleFlags.get(0);
        if (builtIn == 1) throw new IllegalArgumentException("内置角色权限固定，请创建自定义角色");
        List<String> normalized = permissionCodes == null ? List.of() : permissionCodes.stream()
                .filter(Objects::nonNull).map(String::trim).filter(s -> !s.isEmpty()).distinct().toList();
        if (!normalized.isEmpty()) {
            Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM security_permission WHERE code IN (" + placeholders(normalized.size()) + ")", Integer.class, normalized.toArray());
            if (count == null || count != normalized.size()) throw new IllegalArgumentException("包含不存在的权限");
        }
        jdbc.update("DELETE FROM security_role_permission WHERE role_id=?", roleId);
        for (String code : normalized) jdbc.update("INSERT INTO security_role_permission(role_id,permission_id) SELECT ?,id FROM security_permission WHERE code=?", roleId, code);
        jdbc.update("UPDATE `user` u JOIN security_user_role ur ON ur.user_id=u.id SET u.authz_version=u.authz_version+1 WHERE ur.role_id=?", roleId);
        jdbc.update("UPDATE security_refresh_session s JOIN security_user_role ur ON ur.user_id=s.user_id SET s.revoked_at=COALESCE(s.revoked_at,NOW()) WHERE ur.role_id=?", roleId);
    }

    @Transactional
    public void deleteRole(long roleId) {
        List<Integer> roleFlags = jdbc.queryForList("SELECT built_in FROM security_role WHERE id=?", Integer.class, roleId);
        if (roleFlags.isEmpty()) throw new IllegalArgumentException("角色不存在");
        Integer builtIn = roleFlags.get(0);
        if (builtIn == 1) throw new IllegalArgumentException("内置角色不能删除");
        Integer users = jdbc.queryForObject("SELECT COUNT(*) FROM security_user_role WHERE role_id=?", Integer.class, roleId);
        if (users != null && users > 0) throw new IllegalArgumentException("角色仍被用户使用");
        jdbc.update("DELETE FROM security_role WHERE id=?", roleId);
    }

    private void invalidateUser(long userId) {
        jdbc.update("UPDATE `user` SET authz_version=authz_version+1 WHERE id=?", userId);
        revokeSessions(userId);
    }

    private void revokeSessions(long userId) {
        jdbc.update("UPDATE security_refresh_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=?", userId);
    }

    private boolean isAdmin(long userId) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM security_user_role ur JOIN security_role r ON r.id=ur.role_id WHERE ur.user_id=? AND r.code='ADMIN'", Integer.class, userId);
        return count != null && count > 0;
    }

    private int activeAdminCount() {
        Integer count = jdbc.queryForObject("SELECT COUNT(DISTINCT u.id) FROM `user` u JOIN security_user_role ur ON ur.user_id=u.id JOIN security_role r ON r.id=ur.role_id WHERE r.code='ADMIN' AND u.status=1 AND u.deleted=0 AND COALESCE(u.password_hash,'')<>''", Integer.class);
        return count == null ? 0 : count;
    }

    private static String placeholders(int count) { return String.join(",", java.util.Collections.nCopies(count, "?")); }
}
