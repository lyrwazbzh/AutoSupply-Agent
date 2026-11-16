package com.motorparts.controller;

import com.motorparts.redis.LoginRateLimiter;
import com.motorparts.security.AuthService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AuthControllerTest {
    private AuthService auth;
    private LoginRateLimiter limiter;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        auth = mock(AuthService.class);
        limiter = mock(LoginRateLimiter.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new AuthController(auth, limiter, false)).build();
    }

    @Test
    void rejectsRateLimitedLoginBeforePasswordVerification() throws Exception {
        when(limiter.check("203.0.113.9"))
                .thenReturn(new LoginRateLimiter.Decision(false, 11, 42));

        mockMvc.perform(post("/api/auth/login")
                        .header("X-Real-IP", "203.0.113.9")
                        .contentType("application/json")
                        .content("{\"username\":\"buyer\",\"password\":\"wrong\"}"))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().string("Retry-After", "42"))
                .andExpect(jsonPath("$.code").value(429))
                .andExpect(jsonPath("$.message").value("登录尝试过于频繁，请稍后再试"));

        verify(auth, never()).login(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any());
    }
}
