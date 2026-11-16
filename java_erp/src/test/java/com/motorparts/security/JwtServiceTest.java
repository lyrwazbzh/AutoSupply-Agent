package com.motorparts.security;

import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JwtServiceTest {
    @Test
    void issuedTokenContainsStableIdentityRolesPermissionsAndVersion() throws Exception {
        JwtKeyProvider keys = new JwtKeyProvider();
        keys.initialize();
        JwtService service = new JwtService(keys, "test-issuer", "erp-api,assistant-api,mcp", 120);
        SecurityPrincipal principal = new SecurityPrincipal(9L, "usr_9", "warehouse", "仓管员", "hash", 1,
                6L, 0, null, Set.of("WAREHOUSE"), Set.of("erp:inventory:inbound", "assistant:use"));

        JwtService.AccessToken issued = service.issue(principal);
        Jwt token = NimbusJwtDecoder.withPublicKey(keys.getPublicKey()).build().decode(issued.value());

        assertEquals("usr_9", token.getSubject());
        assertEquals("warehouse", token.getClaimAsString("username"));
        assertEquals(6L, ((Number) token.getClaim("authz_version")).longValue());
        assertTrue(token.getAudience().containsAll(Set.of("erp-api", "assistant-api", "mcp")));
        assertTrue(token.getClaimAsStringList("roles").contains("WAREHOUSE"));
        assertTrue(token.getClaimAsStringList("permissions").contains("erp:inventory:inbound"));
    }
}
