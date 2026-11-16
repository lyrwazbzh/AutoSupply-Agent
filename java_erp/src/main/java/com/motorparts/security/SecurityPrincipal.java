package com.motorparts.security;

import java.time.LocalDateTime;
import java.util.Set;

public record SecurityPrincipal(
        Long userId,
        String subject,
        String username,
        String displayName,
        String passwordHash,
        Integer status,
        long authzVersion,
        int failedLoginCount,
        LocalDateTime lockedUntil,
        Set<String> roles,
        Set<String> permissions
) {
    public boolean active() {
        return Integer.valueOf(1).equals(status)
                && (lockedUntil == null || lockedUntil.isBefore(LocalDateTime.now()));
    }
}

