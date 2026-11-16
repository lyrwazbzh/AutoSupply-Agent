package com.motorparts.security;

import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.proc.SecurityContext;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

@Service
public class JwtService {
    private final JwtEncoder encoder;
    private final String issuer;
    private final List<String> audience;
    private final long accessTtlSeconds;

    public JwtService(
            JwtKeyProvider keys,
            @Value("${motorparts.security.jwt.issuer:java-erp}") String issuer,
            @Value("${motorparts.security.jwt.audience:erp-api,assistant-api,mcp}") String audience,
            @Value("${motorparts.security.jwt.access-ttl-seconds:900}") long accessTtlSeconds) {
        RSAKey rsa = new RSAKey.Builder(keys.getPublicKey()).privateKey(keys.getPrivateKey()).keyID("java-erp-rs256").build();
        this.encoder = new NimbusJwtEncoder(new ImmutableJWKSet<SecurityContext>(new JWKSet(rsa)));
        this.issuer = issuer;
        this.audience = Arrays.stream(audience.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
        this.accessTtlSeconds = accessTtlSeconds;
    }

    public AccessToken issue(SecurityPrincipal principal) {
        Instant now = Instant.now();
        Instant expires = now.plusSeconds(accessTtlSeconds);
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(issuer).subject(principal.subject()).audience(audience)
                .issuedAt(now).expiresAt(expires).id(UUID.randomUUID().toString())
                .claim("username", principal.username())
                .claim("user_id", principal.userId())
                .claim("display_name", principal.displayName() == null ? principal.username() : principal.displayName())
                .claim("roles", principal.roles()).claim("permissions", principal.permissions())
                .claim("authz_version", principal.authzVersion()).build();
        return new AccessToken(encoder.encode(JwtEncoderParameters.from(claims)).getTokenValue(), expires);
    }

    public record AccessToken(String value, Instant expiresAt) {}
}
