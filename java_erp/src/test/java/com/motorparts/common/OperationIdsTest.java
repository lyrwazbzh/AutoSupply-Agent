package com.motorparts.common;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class OperationIdsTest {

    @Test
    void bodyTakesPrecedenceAndValuesAreTrimmed() {
        assertEquals("body", OperationIds.resolve(" body ", "query", "header"));
    }

    @Test
    void queryTakesPrecedenceOverHeader() {
        assertEquals("query", OperationIds.resolve(" ", " query ", "header"));
    }

    @Test
    void headerIsUsedAsLastFallback() {
        assertEquals("header", OperationIds.resolve(null, "", " header "));
    }

    @Test
    void blankInputsResolveToNull() {
        assertNull(OperationIds.resolve(null, " ", ""));
    }
}

