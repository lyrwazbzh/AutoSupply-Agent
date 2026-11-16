package com.motorparts.security;

import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class AuthService {
    private final SecurityUserRepository users;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final RefreshTokenService refreshTokens;

    @Transactional
    public TokenBundle login(String username, String password, String ip, String userAgent) {
        SecurityPrincipal user = users.findByUsername(username).orElseThrow(AuthenticationFailed::new);
        if (!user.active() || user.passwordHash() == null || !passwordEncoder.matches(password, user.passwordHash())) {
            users.recordLoginFailure(user.userId(), user.failedLoginCount() + 1);
            throw new AuthenticationFailed();
        }
        users.recordLoginSuccess(user.userId());
        SecurityPrincipal refreshed = users.findById(user.userId()).orElseThrow(AuthenticationFailed::new);
        return issue(refreshed, refreshTokens.issue(user.userId(), ip, userAgent));
    }

    @Transactional
    public TokenBundle refresh(String rawRefreshToken, String ip, String userAgent) {
        RefreshTokenService.RotatedRefreshToken rotated = refreshTokens.rotate(rawRefreshToken, ip, userAgent);
        SecurityPrincipal user = users.findById(rotated.userId()).orElseThrow(AuthenticationFailed::new);
        if (!user.active()) throw new AuthenticationFailed();
        return issue(user, rotated.token());
    }

    public void logout(String rawRefreshToken) {
        refreshTokens.revoke(rawRefreshToken);
    }

    @Transactional
    public void changePassword(String subject, String currentPassword, String newPassword) {
        if (newPassword == null || newPassword.length() < 10) throw new IllegalArgumentException("新密码至少 10 位");
        SecurityPrincipal user = users.findBySubject(subject).orElseThrow(AuthenticationFailed::new);
        if (!user.active() || user.passwordHash() == null
                || !passwordEncoder.matches(currentPassword, user.passwordHash())) {
            throw new AuthenticationFailed();
        }
        if (passwordEncoder.matches(newPassword, user.passwordHash())) {
            throw new IllegalArgumentException("新密码不能与当前密码相同");
        }
        users.changePassword(user.userId(), passwordEncoder.encode(newPassword));
    }

    private TokenBundle issue(SecurityPrincipal user, RefreshTokenService.IssuedRefreshToken refresh) {
        JwtService.AccessToken access = jwtService.issue(user);
        return new TokenBundle(access.value(), access.expiresAt().getEpochSecond(), refresh.value(),
                refresh.expiresAt().getEpochSecond(), user);
    }

    public record TokenBundle(String accessToken, long accessExpiresAt, String refreshToken,
                              long refreshExpiresAt, SecurityPrincipal principal) {}
    public static class AuthenticationFailed extends RuntimeException {}
}
