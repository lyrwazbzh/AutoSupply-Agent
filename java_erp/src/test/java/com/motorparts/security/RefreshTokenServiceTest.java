package com.motorparts.security;

import org.junit.jupiter.api.Test;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertTrue;

class RefreshTokenServiceTest {

    @Test
    void replayDetectionCommitsFamilyRevocation() throws Exception {
        Method rotate = RefreshTokenService.class.getMethod(
                "rotate", String.class, String.class, String.class);
        Transactional transactional = rotate.getAnnotation(Transactional.class);

        assertTrue(Arrays.asList(transactional.noRollbackFor())
                .contains(RefreshTokenService.RefreshTokenReuseException.class));
    }
}
