package com.motorparts.controller;

import com.motorparts.security.JwtKeyProvider;
import com.nimbusds.jose.jwk.RSAKey;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequiredArgsConstructor
public class JwkController {
    private final JwtKeyProvider keys;

    @GetMapping("/internal/auth/jwks")
    public Map<String, Object> jwks() {
        RSAKey publicJwk = new RSAKey.Builder(keys.getPublicKey()).keyID("java-erp-rs256").build();
        return Map.of("keys", java.util.List.of(publicJwk.toJSONObject()));
    }
}

