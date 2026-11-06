package com.motorparts.common;

import org.springframework.util.StringUtils;

/**
 * 从 body / query / header 解析 operationId。
 */
public final class OperationIds {

    private OperationIds() {
    }

    public static String resolve(String bodyId, String queryId, String headerId) {
        if (StringUtils.hasText(bodyId)) {
            return bodyId.trim();
        }
        if (StringUtils.hasText(queryId)) {
            return queryId.trim();
        }
        if (StringUtils.hasText(headerId)) {
            return headerId.trim();
        }
        return null;
    }
}
