package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.security.SecurityAdminService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class SecurityAdminController {
    private final SecurityAdminService admin;

    @GetMapping("/users")
    @PreAuthorize("hasAuthority('system:user:read')")
    public Result<List<Map<String, Object>>> users() { return Result.success(admin.listUsers()); }

    @PostMapping("/users")
    @PreAuthorize("hasAuthority('system:user:manage')")
    public Result<Map<String, Long>> createUser(@Valid @RequestBody CreateUser body) {
        return Result.success(Map.of("id", admin.createUser(body.username(), body.displayName(), body.password(), body.roles())));
    }

    @GetMapping("/users/{id}/roles")
    @PreAuthorize("hasAuthority('system:user:read')")
    public Result<List<String>> userRoles(@PathVariable long id) { return Result.success(admin.rolesForUser(id)); }

    @PutMapping("/users/{id}/roles")
    @PreAuthorize("hasAuthority('system:user:manage')")
    public Result<Void> updateRoles(@PathVariable long id, @RequestBody Codes body) { admin.assignRoles(id, body.codes()); return Result.success(); }

    @PatchMapping("/users/{id}/status")
    @PreAuthorize("hasAuthority('system:user:manage')")
    public Result<Void> status(@PathVariable long id, @RequestBody Status body) { admin.setUserStatus(id, body.status()); return Result.success(); }

    @PostMapping("/users/{id}/reset-password")
    @PreAuthorize("hasAuthority('system:user:manage')")
    public Result<Void> resetPassword(@PathVariable long id, @Valid @RequestBody Password body) { admin.resetPassword(id, body.password()); return Result.success(); }

    @GetMapping("/roles")
    @PreAuthorize("hasAuthority('system:role:read')")
    public Result<List<Map<String, Object>>> roles() { return Result.success(admin.listRoles()); }

    @PostMapping("/roles")
    @PreAuthorize("hasAuthority('system:role:manage')")
    public Result<Map<String, Long>> createRole(@Valid @RequestBody CreateRole body) { return Result.success(Map.of("id", admin.createRole(body.code(), body.name(), body.description()))); }

    @GetMapping("/roles/{id}/permissions")
    @PreAuthorize("hasAuthority('system:role:read')")
    public Result<List<String>> rolePermissions(@PathVariable long id) { return Result.success(admin.permissionsForRole(id)); }

    @PutMapping("/roles/{id}/permissions")
    @PreAuthorize("hasAuthority('system:role:manage')")
    public Result<Void> updatePermissions(@PathVariable long id, @RequestBody Codes body) { admin.assignPermissions(id, body.codes()); return Result.success(); }

    @DeleteMapping("/roles/{id}")
    @PreAuthorize("hasAuthority('system:role:manage')")
    public Result<Void> deleteRole(@PathVariable long id) { admin.deleteRole(id); return Result.success(); }

    @GetMapping("/permissions")
    @PreAuthorize("hasAuthority('system:role:read')")
    public Result<List<Map<String, Object>>> permissions() { return Result.success(admin.listPermissions()); }

    public record CreateUser(@NotBlank String username, String displayName, @NotBlank @Size(min=10) String password, List<String> roles) {}
    public record CreateRole(@NotBlank String code, @NotBlank String name, String description) {}
    public record Codes(List<String> codes) {}
    public record Status(int status) {}
    public record Password(@NotBlank @Size(min=10) String password) {}
}
