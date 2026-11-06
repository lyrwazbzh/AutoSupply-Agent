package com.motorparts.mq;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.motorparts.entity.LocalMessage;
import com.motorparts.mapper.LocalMessageMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class LocalMessageService {

    public static final String TOPIC_ORDER_PENDING_CANCEL = "order.pending.cancel";
    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_DONE = "DONE";
    public static final String STATUS_FAILED = "FAILED";

    private final LocalMessageMapper localMessageMapper;
    private final ObjectMapper objectMapper;

    @Transactional(rollbackFor = Exception.class)
    public void enqueueOrderPendingCancel(Long orderId, LocalDateTime deliverAt) {
        if (orderId == null || deliverAt == null) {
            return;
        }
        String msgKey = "timeout:order-cancel:" + orderId;
        LocalMessage existing = localMessageMapper.selectOne(
                new LambdaQueryWrapper<LocalMessage>().eq(LocalMessage::getMsgKey, msgKey)
        );
        if (existing != null) {
            return;
        }
        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("orderId", orderId);
            payload.put("action", "AUTO_CANCEL_PENDING");
            LocalMessage msg = new LocalMessage();
            msg.setMsgKey(msgKey);
            msg.setTopic(TOPIC_ORDER_PENDING_CANCEL);
            msg.setPayload(objectMapper.writeValueAsString(payload));
            msg.setStatus(STATUS_PENDING);
            msg.setDeliverAt(deliverAt);
            msg.setRetryCount(0);
            msg.setCreateTime(LocalDateTime.now());
            msg.setUpdateTime(LocalDateTime.now());
            localMessageMapper.insert(msg);
        } catch (DuplicateKeyException ignored) {
            // msg_key 唯一
        } catch (Exception e) {
            throw new IllegalStateException("登记 local_message 失败: " + msgKey, e);
        }
    }

    public List<LocalMessage> pollDue(int limit) {
        return localMessageMapper.selectList(
                new LambdaQueryWrapper<LocalMessage>()
                        .eq(LocalMessage::getStatus, STATUS_PENDING)
                        .le(LocalMessage::getDeliverAt, LocalDateTime.now())
                        .orderByAsc(LocalMessage::getDeliverAt)
                        .last("LIMIT " + Math.max(1, limit))
        );
    }

    public void markDone(Long id) {
        localMessageMapper.update(
                null,
                new LambdaUpdateWrapper<LocalMessage>()
                        .set(LocalMessage::getStatus, STATUS_DONE)
                        .set(LocalMessage::getUpdateTime, LocalDateTime.now())
                        .eq(LocalMessage::getId, id)
                        .eq(LocalMessage::getStatus, STATUS_PENDING)
        );
    }

    public void markFailed(Long id) {
        LocalMessage msg = localMessageMapper.selectById(id);
        int retry = msg != null && msg.getRetryCount() != null ? msg.getRetryCount() + 1 : 1;
        localMessageMapper.update(
                null,
                new LambdaUpdateWrapper<LocalMessage>()
                        .set(LocalMessage::getStatus, retry >= 5 ? STATUS_FAILED : STATUS_PENDING)
                        .set(LocalMessage::getRetryCount, retry)
                        .set(LocalMessage::getDeliverAt, LocalDateTime.now().plusSeconds(10L * retry))
                        .set(LocalMessage::getUpdateTime, LocalDateTime.now())
                        .eq(LocalMessage::getId, id)
        );
    }
}
