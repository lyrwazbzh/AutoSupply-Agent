package com.motorparts.security;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class RefreshTokenService {
    private final JdbcTemplate jdbc;
    private final SecureRandom random = new SecureRandom();

    @Value("${motorparts.security.jwt.refresh-ttl-seconds:604800}")
    private long refreshTtlSeconds;

    @Transactional
    public IssuedRefreshToken issue(long userId, String ip, String userAgent) {
        return issue(userId, UUID.randomUUID().toString(), ip, userAgent);
    }

    // Reuse detection must commit the family-wide revocation even though the request is
    // rejected with an exception.  Rolling the transaction back here would leave the
    // attacker's replacement token valid.
    @Transactional(noRollbackFor = RefreshTokenReuseException.class)
    public RotatedRefreshToken rotate(String raw, String ip, String userAgent) {
        String hash = hash(raw);
        List<RefreshRow> rows = jdbc.query(
                "SELECT id,family_id,user_id,expires_at,revoked_at FROM security_refresh_session WHERE token_hash=? FOR UPDATE",
                (rs, n) -> new RefreshRow(rs.getString("id"), rs.getString("family_id"), rs.getLong("user_id"),
                        rs.getTimestamp("expires_at").toLocalDateTime(),
                        rs.getTimestamp("revoked_at") == null ? null : rs.getTimestamp("revoked_at").toLocalDateTime()), hash);
        if (rows.isEmpty()) throw new InvalidRefreshTokenException();
        RefreshRow row = rows.get(0);
        if (row.revokedAt != null) {
            jdbc.update("UPDATE security_refresh_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE family_id=?", row.familyId);
            throw new RefreshTokenReuseException();
        }
        if (row.expiresAt.isBefore(LocalDateTime.now())) throw new InvalidRefreshTokenException();
        IssuedRefreshToken next = issue(row.userId, row.familyId, ip, userAgent);
        jdbc.update("UPDATE security_refresh_session SET revoked_at=NOW(),replaced_by=? WHERE id=?", next.id(), row.id);
        return new RotatedRefreshToken(row.userId, next);
    }

    public void revoke(String raw) {
        if (raw != null && !raw.isBlank()) jdbc.update("UPDATE security_refresh_session SET revoked_at=COALESCE(revoked_at,NOW()) WHERE token_hash=?", hash(raw));
    }

    private IssuedRefreshToken issue(long userId, String familyId, String ip, String userAgent) {
        byte[] value = new byte[32];
        random.nextBytes(value);
        String raw = Base64.getUrlEncoder().withoutPadding().encodeToString(value);
        String id = UUID.randomUUID().toString();
        Instant expires = Instant.now().plusSeconds(refreshTtlSeconds);
        jdbc.update("INSERT INTO security_refresh_session(id,family_id,user_id,token_hash,expires_at,client_ip,user_agent) VALUES(?,?,?,?,?,?,?)",
                id, familyId, userId, hash(raw), LocalDateTime.now().plusSeconds(refreshTtlSeconds), ip, truncate(userAgent, 500));
        return new IssuedRefreshToken(id, raw, expires);
    }

    private static String hash(String raw) {
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String truncate(String value, int limit) {
        return value == null ? null : value.substring(0, Math.min(limit, value.length()));
    }

    private record RefreshRow(String id, String familyId, long userId, LocalDateTime expiresAt, LocalDateTime revokedAt) {}
    public record IssuedRefreshToken(String id, String value, Instant expiresAt) {}
    public record RotatedRefreshToken(long userId, IssuedRefreshToken token) {}
    public static class InvalidRefreshTokenException extends RuntimeException {}
    public static class RefreshTokenReuseException extends RuntimeException {}
}
