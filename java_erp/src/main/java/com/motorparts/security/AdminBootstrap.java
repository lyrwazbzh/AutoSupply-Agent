package com.motorparts.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;
import java.util.List;

@Component
public class AdminBootstrap implements ApplicationRunner {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder encoder;
    private final String username;
    private final String password;

    public AdminBootstrap(JdbcTemplate jdbc, PasswordEncoder encoder,
                          @Value("${ERP_BOOTSTRAP_ADMIN_USERNAME:}") String username,
                          @Value("${ERP_BOOTSTRAP_ADMIN_PASSWORD:}") String password) {
        this.jdbc = jdbc; this.encoder = encoder; this.username = username; this.password = password;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (username.isBlank() && password.isBlank()) return;
        if (username.isBlank() || password.length() < 10) throw new IllegalStateException("Bootstrap admin requires username and a password of at least 10 characters");
        List<Long> existing = jdbc.queryForList("SELECT id FROM `user` WHERE username=? AND deleted=0", Long.class, username);
        if (!existing.isEmpty()) {
            long userId = existing.get(0);
            Integer ready = jdbc.queryForObject("SELECT COUNT(*) FROM `user` u JOIN security_user_role ur ON ur.user_id=u.id JOIN security_role r ON r.id=ur.role_id WHERE u.id=? AND u.password_hash IS NOT NULL AND r.code='ADMIN'", Integer.class, userId);
            if (ready != null && ready > 0) return;
            jdbc.update("UPDATE `user` SET password='!',password_hash=?,status=1,failed_login_count=0,locked_until=NULL,authz_version=authz_version+1 WHERE id=?",
                    encoder.encode(password), userId);
            jdbc.update("INSERT IGNORE INTO security_user_role(user_id,role_id) SELECT ?,id FROM security_role WHERE code='ADMIN'", userId);
            jdbc.update("UPDATE security_refresh_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=?", userId);
            return;
        }
        Integer admins = jdbc.queryForObject("SELECT COUNT(*) FROM security_user_role ur JOIN security_role r ON r.id=ur.role_id JOIN `user` u ON u.id=ur.user_id WHERE r.code='ADMIN' AND u.password_hash IS NOT NULL AND u.status=1", Integer.class);
        if (admins != null && admins > 0) return;
        String subject = "usr_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.update("INSERT INTO `user`(auth_subject,username,password,password_hash,real_name,role,status,deleted) VALUES(?,?,?, ?,?,'admin',1,0)",
                subject, username, "!", encoder.encode(password), username);
        Long userId = jdbc.queryForObject("SELECT id FROM `user` WHERE auth_subject=?", Long.class, subject);
        jdbc.update("INSERT INTO security_user_role(user_id,role_id) SELECT ?,id FROM security_role WHERE code='ADMIN'", userId);
    }
}
