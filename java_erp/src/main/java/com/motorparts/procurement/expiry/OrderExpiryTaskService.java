package com.motorparts.procurement.expiry;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class OrderExpiryTaskService {
    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_DONE = "DONE";
    public static final String STATUS_FAILED = "FAILED";

    private final OrderExpiryTaskMapper mapper;

    @Transactional(rollbackFor = Exception.class)
    public void schedulePendingOrderCancellation(Long orderId, LocalDateTime expireAt) {
        if (orderId == null || expireAt == null) return;
        String taskKey = "pending-order-expiry:" + orderId;
        if (mapper.selectOne(new LambdaQueryWrapper<OrderExpiryTask>()
                .eq(OrderExpiryTask::getTaskKey, taskKey)) != null) return;
        OrderExpiryTask task = new OrderExpiryTask();
        task.setTaskKey(taskKey);
        task.setOrderId(orderId);
        task.setStatus(STATUS_PENDING);
        task.setExpireAt(expireAt);
        task.setRetryCount(0);
        task.setCreateTime(LocalDateTime.now());
        task.setUpdateTime(LocalDateTime.now());
        try {
            mapper.insert(task);
        } catch (DuplicateKeyException ignored) {
            // task_key is the idempotency boundary.
        }
    }

    public List<OrderExpiryTask> pollDue(int limit) {
        return mapper.selectList(new LambdaQueryWrapper<OrderExpiryTask>()
                .eq(OrderExpiryTask::getStatus, STATUS_PENDING)
                .le(OrderExpiryTask::getExpireAt, LocalDateTime.now())
                .orderByAsc(OrderExpiryTask::getExpireAt)
                .last("LIMIT " + Math.max(1, limit)));
    }

    public void markDone(Long id) {
        mapper.update(null, new LambdaUpdateWrapper<OrderExpiryTask>()
                .set(OrderExpiryTask::getStatus, STATUS_DONE)
                .set(OrderExpiryTask::getLastError, null)
                .set(OrderExpiryTask::getUpdateTime, LocalDateTime.now())
                .eq(OrderExpiryTask::getId, id)
                .eq(OrderExpiryTask::getStatus, STATUS_PENDING));
    }

    public void markFailed(Long id, String error) {
        OrderExpiryTask task = mapper.selectById(id);
        int retry = task != null && task.getRetryCount() != null ? task.getRetryCount() + 1 : 1;
        mapper.update(null, new LambdaUpdateWrapper<OrderExpiryTask>()
                .set(OrderExpiryTask::getStatus, retry >= 5 ? STATUS_FAILED : STATUS_PENDING)
                .set(OrderExpiryTask::getRetryCount, retry)
                .set(OrderExpiryTask::getLastError, error)
                .set(OrderExpiryTask::getExpireAt, LocalDateTime.now().plusSeconds(10L * retry))
                .set(OrderExpiryTask::getUpdateTime, LocalDateTime.now())
                .eq(OrderExpiryTask::getId, id));
    }
}
