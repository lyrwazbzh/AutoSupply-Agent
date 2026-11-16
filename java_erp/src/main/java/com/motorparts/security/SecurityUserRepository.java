package com.motorparts.security;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

@Repository
@RequiredArgsConstructor
public class SecurityUserRepository {

    private final JdbcTemplate jdbc;

    public Optional<SecurityPrincipal> findByUsername(String username) {
        List<SecurityPrincipal> users = jdbc.query(baseUserSql() + " WHERE u.username = ? AND u.deleted = 0", this::mapUser, username);
        return users.stream().findFirst().map(this::withAuthorities);
    }

    public Optional<SecurityPrincipal> findBySubject(String subject) {
        List<SecurityPrincipal> users = jdbc.query(baseUserSql() + " WHERE u.auth_subject = ? AND u.deleted = 0", this::mapUser, subject);
        return users.stream().findFirst().map(this::withAuthorities);
    }

    public Optional<SecurityPrincipal> findById(long id) {
        List<SecurityPrincipal> users = jdbc.query(baseUserSql() + " WHERE u.id = ? AND u.deleted = 0", this::mapUser, id);
        return users.stream().findFirst().map(this::withAuthorities);
    }

    public void recordLoginSuccess(long userId) {
        jdbc.update("UPDATE `user` SET failed_login_count=0, locked_until=NULL, last_login_at=NOW() WHERE id=?", userId);
    }

    public void recordLoginFailure(long userId, int nextFailureCount) {
        if (nextFailureCount >= 5) {
            jdbc.update("UPDATE `user` SET failed_login_count=?, locked_until=DATE_ADD(NOW(), INTERVAL 15 MINUTE) WHERE id=?", nextFailureCount, userId);
        } else {
            jdbc.update("UPDATE `user` SET failed_login_count=? WHERE id=?", nextFailureCount, userId);
        }
    }

    public void incrementAuthzVersion(long userId) {
        jdbc.update("UPDATE `user` SET authz_version=authz_version+1 WHERE id=?", userId);
    }

    public void changePassword(long userId, String passwordHash) {
        jdbc.update("UPDATE `user` SET password='!',password_hash=?,password_changed_at=NOW(),failed_login_count=0,locked_until=NULL,authz_version=authz_version+1 WHERE id=?",
                passwordHash, userId);
        jdbc.update("UPDATE security_refresh_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=?", userId);
    }

    private SecurityPrincipal withAuthorities(SecurityPrincipal base) {
        Set<String> roles = new HashSet<>(jdbc.queryForList(
                "SELECT r.code FROM security_role r JOIN security_user_role ur ON ur.role_id=r.id WHERE ur.user_id=? AND r.status=1",
                String.class, base.userId()));
        Set<String> permissions = new HashSet<>(jdbc.queryForList(
                "SELECT DISTINCT p.code FROM security_permission p " +
                        "JOIN security_role_permission rp ON rp.permission_id=p.id " +
                        "JOIN security_user_role ur ON ur.role_id=rp.role_id " +
                        "JOIN security_role r ON r.id=ur.role_id AND r.status=1 WHERE ur.user_id=?",
                String.class, base.userId()));
        return new SecurityPrincipal(base.userId(), base.subject(), base.username(), base.displayName(),
                base.passwordHash(), base.status(), base.authzVersion(), base.failedLoginCount(),
                base.lockedUntil(), Set.copyOf(roles), Set.copyOf(permissions));
    }

    private String baseUserSql() {
        return "SELECT u.id,u.auth_subject,u.username,u.real_name,u.password_hash,u.status,u.authz_version," +
                "u.failed_login_count,u.locked_until FROM `user` u";
    }

    private SecurityPrincipal mapUser(ResultSet rs, int rowNum) throws SQLException {
        return new SecurityPrincipal(
                rs.getLong("id"), rs.getString("auth_subject"), rs.getString("username"),
                rs.getString("real_name"), rs.getString("password_hash"), rs.getInt("status"),
                rs.getLong("authz_version"), rs.getInt("failed_login_count"),
                rs.getTimestamp("locked_until") == null ? null : rs.getTimestamp("locked_until").toLocalDateTime(),
                Set.of(), Set.of());
    }
}
