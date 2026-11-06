package com.motorparts.service;

import com.motorparts.common.Result;

import java.util.Map;

/**
 * 写操作号登记与回查（对齐 Mock replay_operation / complete_operation）。
 */
public interface ErpOperationService {

    /**
     * 若 operationId 已登记，返回首次 Result 信封；否则 null。
     */
    Result<?> replay(String operationId);

    /**
     * 首次写入终态；同 id 已存在则保持首次结果。
     */
    void complete(String operationId, Result<?> result);

    /**
     * 对账回查：未找到时 data.applied=false, status=NOT_FOUND。
     */
    Result<Map<String, Object>> get(String operationId);
}
