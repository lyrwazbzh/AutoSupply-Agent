package com.motorparts.security;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.Instant;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.*;

class AuthServiceTest {
    private SecurityUserRepository users;
    private PasswordEncoder encoder;
    private JwtService jwt;
    private RefreshTokenService refresh;
    private AuthService service;

    @BeforeEach
    void setUp() {
        users = mock(SecurityUserRepository.class);
        encoder = mock(PasswordEncoder.class);
        jwt = mock(JwtService.class);
        refresh = mock(RefreshTokenService.class);
        service = new AuthService(users, encoder, jwt, refresh);
    }

    @Test
    void successfulLoginRecordsSuccessAndIssuesBothTokens() {
        SecurityPrincipal principal = principal(0, 1);
        when(users.findByUsername("buyer")).thenReturn(Optional.of(principal));
        when(encoder.matches("correct-password", "{bcrypt}hash")).thenReturn(true);
        when(users.findById(7)).thenReturn(Optional.of(principal));
        when(refresh.issue(7, "127.0.0.1", "test")).thenReturn(
                new RefreshTokenService.IssuedRefreshToken("refresh-id", "refresh-token", Instant.now().plusSeconds(60)));
        when(jwt.issue(principal)).thenReturn(new JwtService.AccessToken("access-token", Instant.now().plusSeconds(30)));

        AuthService.TokenBundle result = service.login("buyer", "correct-password", "127.0.0.1", "test");

        assertEquals("access-token", result.accessToken());
        assertEquals("refresh-token", result.refreshToken());
        verify(users).recordLoginSuccess(7);
        verify(users, never()).recordLoginFailure(anyLong(), anyInt());
    }

    @Test
    void badPasswordIncrementsFailureAndDoesNotIssueTokens() {
        SecurityPrincipal principal = principal(2, 1);
        when(users.findByUsername("buyer")).thenReturn(Optional.of(principal));
        when(encoder.matches(anyString(), anyString())).thenReturn(false);

        assertThrows(AuthService.AuthenticationFailed.class,
                () -> service.login("buyer", "wrong-password", "127.0.0.1", "test"));

        verify(users).recordLoginFailure(7, 3);
        verifyNoInteractions(jwt, refresh);
    }

    @Test
    void disabledAccountCannotLoginEvenWithMatchingPassword() {
        SecurityPrincipal principal = principal(0, 2);
        when(users.findByUsername("buyer")).thenReturn(Optional.of(principal));

        assertThrows(AuthService.AuthenticationFailed.class,
                () -> service.login("buyer", "correct-password", "127.0.0.1", "test"));

        verify(users).recordLoginFailure(7, 1);
        verifyNoInteractions(jwt, refresh);
    }

    @Test
    void changingPasswordVerifiesCurrentPasswordAndRevokesSessions() {
        SecurityPrincipal principal = principal(0, 1);
        when(users.findBySubject("usr_7")).thenReturn(Optional.of(principal));
        when(encoder.matches("old-password", "{bcrypt}hash")).thenReturn(true);
        when(encoder.matches("new-password-123", "{bcrypt}hash")).thenReturn(false);
        when(encoder.encode("new-password-123")).thenReturn("{bcrypt}new-hash");

        service.changePassword("usr_7", "old-password", "new-password-123");

        verify(users).changePassword(7, "{bcrypt}new-hash");
    }

    @Test
    void changingPasswordRejectsWrongCurrentPassword() {
        SecurityPrincipal principal = principal(0, 1);
        when(users.findBySubject("usr_7")).thenReturn(Optional.of(principal));
        when(encoder.matches("wrong-password", "{bcrypt}hash")).thenReturn(false);

        assertThrows(AuthService.AuthenticationFailed.class,
                () -> service.changePassword("usr_7", "wrong-password", "new-password-123"));

        verify(users, never()).changePassword(anyLong(), anyString());
    }

    private SecurityPrincipal principal(int failures, int status) {
        return new SecurityPrincipal(7L, "usr_7", "buyer", "Buyer", "{bcrypt}hash", status,
                4L, failures, null, Set.of("PURCHASER"), Set.of("assistant:use"));
    }
}
