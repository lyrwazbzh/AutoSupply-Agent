package com.motorparts.security;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class BusinessAuditService {
    private final JdbcTemplate jdbc;

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void append(AuditEvent event) {
        jdbc.update("INSERT INTO business_audit_event(event_id,actor_subject,actor_username,actor_roles,source,action,resource_type,resource_id,request_id,trace_id,operation_id,http_method,request_path,outcome,status_code,error_code,error_message,client_ip,user_agent) VALUES(?,?,?,CAST(? AS JSON),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                UUID.randomUUID().toString(), event.actorSubject(), event.actorUsername(), jsonArray(event.roles()),
                event.source(), event.action(), event.resourceType(), event.resourceId(), event.requestId(), event.traceId(),
                event.operationId(), event.method(), event.path(), event.outcome(), event.statusCode(), event.errorCode(),
                truncate(event.errorMessage(), 500), event.clientIp(), truncate(event.userAgent(), 500));
    }

    public List<Map<String, Object>> list(String actor, String action, String outcome, int limit) {
        StringBuilder sql = new StringBuilder("SELECT event_id,occurred_at,actor_subject,actor_username,actor_roles,source,action,resource_type,resource_id,request_id,trace_id,operation_id,http_method,request_path,outcome,status_code,error_code,error_message FROM business_audit_event WHERE 1=1");
        java.util.ArrayList<Object> args = new java.util.ArrayList<>();
        if (actor != null && !actor.isBlank()) { sql.append(" AND actor_subject=?"); args.add(actor); }
        if (action != null && !action.isBlank()) { sql.append(" AND action=?"); args.add(action); }
        if (outcome != null && !outcome.isBlank()) { sql.append(" AND outcome=?"); args.add(outcome); }
        sql.append(" ORDER BY occurred_at DESC LIMIT ?"); args.add(Math.min(Math.max(limit, 1), 500));
        return jdbc.queryForList(sql.toString(), args.toArray());
    }

    private static String jsonArray(List<String> values) {
        if (values == null || values.isEmpty()) return "[]";
        return values.stream().map(v -> "\"" + v.replace("\\", "\\\\").replace("\"", "\\\"") + "\"")
                .collect(java.util.stream.Collectors.joining(",", "[", "]"));
    }
    private static String truncate(String value, int max) { return value == null ? null : value.substring(0, Math.min(value.length(), max)); }

    public record AuditEvent(String actorSubject, String actorUsername, List<String> roles, String source,
                             String action, String resourceType, String resourceId, String requestId, String traceId,
                             String operationId, String method, String path, String outcome, int statusCode,
                             String errorCode, String errorMessage, String clientIp, String userAgent) {}
}

