package com.motorparts.security;

import jakarta.annotation.PostConstruct;
import lombok.Getter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

@Component
@Getter
public class JwtKeyProvider {
    private static final Logger log = LoggerFactory.getLogger(JwtKeyProvider.class);

    @Value("${motorparts.security.jwt.private-key-path:}")
    private String privateKeyPath = "";
    @Value("${motorparts.security.jwt.public-key-path:}")
    private String publicKeyPath = "";
    @Value("${motorparts.security.jwt.require-configured-key:false}")
    private boolean requireConfiguredKey;

    private RSAPrivateKey privateKey;
    private RSAPublicKey publicKey;

    @PostConstruct
    void initialize() throws Exception {
        if (!privateKeyPath.isBlank() && !publicKeyPath.isBlank()) {
            KeyFactory factory = KeyFactory.getInstance("RSA");
            privateKey = (RSAPrivateKey) factory.generatePrivate(new PKCS8EncodedKeySpec(readPem(privateKeyPath)));
            publicKey = (RSAPublicKey) factory.generatePublic(new X509EncodedKeySpec(readPem(publicKeyPath)));
            return;
        }
        if (requireConfiguredKey) {
            throw new IllegalStateException("ERP JWT key paths are required in this profile");
        }
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        KeyPair pair = generator.generateKeyPair();
        privateKey = (RSAPrivateKey) pair.getPrivate();
        publicKey = (RSAPublicKey) pair.getPublic();
        log.warn("Using an ephemeral JWT signing key; configure ERP_JWT_PRIVATE_KEY_PATH and ERP_JWT_PUBLIC_KEY_PATH outside development");
    }

    private static byte[] readPem(String path) throws Exception {
        String pem = Files.readString(Path.of(path), StandardCharsets.US_ASCII)
                .replaceAll("-----BEGIN [A-Z ]+-----", "")
                .replaceAll("-----END [A-Z ]+-----", "")
                .replaceAll("\\s", "");
        return Base64.getDecoder().decode(pem);
    }
}
