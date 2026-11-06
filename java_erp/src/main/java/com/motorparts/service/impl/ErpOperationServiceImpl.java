package com.motorparts.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.motorparts.common.Result;
import com.motorparts.entity.ErpOperation;
import com.motorparts.mapper.ErpOperationMapper;
import com.motorparts.service.ErpOperationService;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ErpOperationServiceImpl implements ErpOperationService {

    private final ErpOperationMapper erpOperationMapper;
    private final ObjectMapper objectMapper;

    @Override
    public Result<?> replay(String operationId) {
        if (!StringUtils.hasText(operationId)) {
            return null;
        }
        ErpOperation existing = erpOperationMapper.selectById(operationId.trim());
        if (existing == null || !StringUtils.hasText(existing.getResultJson())) {
            return null;
        }
        try {
            return objectMapper.readValue(existing.getResultJson(), Result.class);
        } catch (Exception e) {
            throw new IllegalStateException("解析 operation 结果失败: " + operationId, e);
        }
    }

    @Override
    public void complete(String operationId, Result<?> result) {
        if (!StringUtils.hasText(operationId) || result == null) {
            return;
        }
        String id = operationId.trim();
        ErpOperation existing = erpOperationMapper.selectById(id);
        if (existing != null) {
            return;
        }
        try {
            ErpOperation row = new ErpOperation();
            row.setOperationId(id);
            row.setStatus("SUCCEEDED");
            row.setApplied(1);
            row.setResultJson(objectMapper.writeValueAsString(result));
            row.setUpdatedAt(LocalDateTime.now());
            erpOperationMapper.insert(row);
        } catch (DuplicateKeyException ignored) {
            // 并发下首次写入已完成，保留首次结果
        } catch (Exception e) {
            throw new IllegalStateException("保存 operation 结果失败: " + id, e);
        }
    }

    @Override
    public Result<Map<String, Object>> get(String operationId) {
        if (!StringUtils.hasText(operationId)) {
            return notFound(null);
        }
        String id = operationId.trim();
        ErpOperation existing = erpOperationMapper.selectById(id);
        if (existing == null) {
            return Result.error(404, "未找到操作: " + id, notFoundData(id));
        }
        Map<String, Object> data = new HashMap<>();
        data.put("operationId", existing.getOperationId());
        data.put("status", existing.getStatus());
        data.put("applied", existing.getApplied() != null && existing.getApplied() == 1);
        data.put("updatedAt", existing.getUpdatedAt());
        if (StringUtils.hasText(existing.getResultJson())) {
            try {
                data.put("result", objectMapper.readValue(existing.getResultJson(), Object.class));
            } catch (Exception e) {
                data.put("result", existing.getResultJson());
            }
        }
        return Result.success(data, "操作回查成功");
    }

    private static Result<Map<String, Object>> notFound(String operationId) {
        return Result.error(404, "未找到操作: " + operationId, notFoundData(operationId));
    }

    private static Map<String, Object> notFoundData(String operationId) {
        Map<String, Object> data = new HashMap<>();
        data.put("operationId", operationId);
        data.put("applied", false);
        data.put("status", "NOT_FOUND");
        return data;
    }
}
