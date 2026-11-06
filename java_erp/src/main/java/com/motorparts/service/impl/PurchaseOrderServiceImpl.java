package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.common.PayloadHashUtil;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.dto.OrderDetailWithPartAndSupplier;
import com.motorparts.dto.PartWithSupplier;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.OrderDetailWithPart;
import com.motorparts.entity.OrderIdempotency;
import com.motorparts.entity.Part;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.OrderIdempotencyMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.mq.LocalMessageService;
import com.motorparts.service.ErpOperationService;
import com.motorparts.service.PurchaseOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 采购订单服务实现类
 */
@Service
@RequiredArgsConstructor
public class PurchaseOrderServiceImpl extends ServiceImpl<PurchaseOrderMapper, PurchaseOrder> implements PurchaseOrderService {

    private final OrderDetailMapper orderDetailMapper;
    private final PartMapper partMapper;
    private final SupplierMapper supplierMapper;
    private final OrderIdempotencyMapper orderIdempotencyMapper;
    private final ErpOperationService erpOperationService;
    private final LocalMessageService localMessageService;

    @Value("${motorparts.mq.enabled:true}")
    private boolean mqEnabled;

    @Value("${motorparts.mq.pending-cancel-hours:24}")
    private long pendingCancelHours;

    private static final Set<Integer> TERMINAL_STATUS = Set.of(4, 5);
    private static final Map<Integer, Set<Integer>> STATUS_TRANSITIONS = Map.of(
            1, Set.of(2, 5),
            2, Set.of(3, 5),
            3, Set.of(4, 5)
    );

    @Override
    public Page<PurchaseOrder> pageOrders(Page<PurchaseOrder> page, String orderNumber,
                                          Integer status, LocalDate startDate, LocalDate endDate) {
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(orderNumber)) {
            wrapper.like(PurchaseOrder::getOrderNumber, orderNumber);
        }

        if (status != null) {
            wrapper.eq(PurchaseOrder::getStatus, status);
        }

        if (startDate != null) {
            wrapper.ge(PurchaseOrder::getOrderTime, startDate.atStartOfDay());
        }

        if (endDate != null) {
            wrapper.le(PurchaseOrder::getOrderTime, endDate.plusDays(1).atStartOfDay());
        }

        wrapper.orderByDesc(PurchaseOrder::getOrderTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public boolean createOrder(PurchaseOrder order) {
        if (order == null || !StringUtils.hasText(order.getOrderNumber())) {
            return false;
        }

        // 检查订单编号是否已存在
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(PurchaseOrder::getOrderNumber, order.getOrderNumber());
        if (baseMapper.selectCount(wrapper) > 0) {
            return false;
        }

        // 设置默认值
        if (order.getOrderTime() == null) {
            order.setOrderTime(LocalDateTime.now());
        }

        if (order.getStatus() == null || order.getStatus() == 0) {
            order.setStatus(1); // 待审核（Harness/MCP 0 与缺省归一）
        }

        // 计算总金额
        BigDecimal totalAmount = BigDecimal.ZERO;
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    if (detailWithPart.getQuantity() != null && detailWithPart.getUnitPrice() != null) {
                        totalAmount = totalAmount.add(
                            detailWithPart.getUnitPrice().multiply(BigDecimal.valueOf(detailWithPart.getQuantity())));
                    }
                }
            }
        }
        order.setTotalAmount(totalAmount);

        // 手动设置deleted、createTime、updateTime字段
        order.setDeleted(0);
        order.setCreateTime(LocalDateTime.now());
        order.setUpdateTime(LocalDateTime.now());

        // 保存订单
        if (!save(order)) {
            return false;
        }

        // 获取订单明细列表并保存
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    // 创建纯OrderDetail对象用于插入，避免partDetail字段干扰
                    OrderDetail detail = OrderDetail.builder()
                            .orderId(order.getId())
                            .partId(detailWithPart.getPartId())
                            .quantity(detailWithPart.getQuantity())
                            .unitPrice(detailWithPart.getUnitPrice())
                            .remark(detailWithPart.getRemark())
                            .build();
                    // 手动设置deleted、createTime、updateTime字段
                    detail.setDeleted(0);
                    detail.setCreateTime(LocalDateTime.now());
                    detail.setUpdateTime(LocalDateTime.now());
                    orderDetailMapper.insert(detail);
                }
            }
        }

        return true;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> createOrderIdempotent(PurchaseOrderWithDetails order, String operationId) {
        if (order == null) {
            return Result.paramError("order_data 不能为空");
        }
        List<OrderDetailWithPart> details = order.getOrderDetail();
        if (details == null || details.isEmpty()) {
            return Result.paramError("orderDetail 不能为空");
        }
        for (int i = 0; i < details.size(); i++) {
            OrderDetailWithPart row = details.get(i);
            if (row.getPartId() == null || partMapper.selectById(row.getPartId()) == null) {
                return Result.error(ResultCode.NOT_FOUND.getCode(),
                        "orderDetail[" + i + "].partId 对应的零部件不存在: " + row.getPartId());
            }
            if (row.getQuantity() == null || row.getQuantity() < 1) {
                return Result.paramError("orderDetail[" + i + "].quantity 必须 >= 1");
            }
            if (row.getUnitPrice() == null) {
                return Result.paramError("orderDetail[" + i + "].unitPrice 为必填");
            }
        }

        if (order.getStatus() == null || order.getStatus() == 0) {
            order.setStatus(1);
        }
        if (!StringUtils.hasText(order.getOrderNumber())) {
            order.setOrderNumber("PO" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss")));
        }

        String idem = order.getIdempotencyKey();
        String payloadHash = PayloadHashUtil.businessPayloadHash(order);
        order.setPayloadHash(payloadHash);

        if (StringUtils.hasText(idem)) {
            OrderIdempotency binding = orderIdempotencyMapper.selectById(idem);
            if (binding != null) {
                if (!payloadHash.equals(binding.getPayloadHash())) {
                    Map<String, Object> conflict = new HashMap<>();
                    conflict.put("idempotencyKey", idem);
                    conflict.put("expectedPayloadHash", binding.getPayloadHash());
                    conflict.put("actualPayloadHash", payloadHash);
                    conflict.put("operationStatus", "REJECTED");
                    return Result.error(ResultCode.IDEMPOTENCY_CONFLICT.getCode(),
                            ResultCode.IDEMPOTENCY_CONFLICT.getMessage(),
                            conflict);
                }
                PurchaseOrderWithDetails existing = loadOrderWithDetails(binding.getOrderId());
                if (existing == null) {
                    return Result.error(500, "幂等记录存在但订单不存在", Map.of(
                            "idempotencyKey", idem,
                            "operationStatus", "UNKNOWN"
                    ));
                }
                existing.setIdempotencyKey(idem);
                existing.setIdempotentReplay(true);
                existing.setOperationStatus("CONFIRMED");
                Result<?> replayHit = Result.success(existing, "幂等命中，返回已有订单");
                erpOperationService.complete(operationId, replayHit);
                return replayHit;
            }
        }

        if (!createOrder(order)) {
            return Result.error(ResultCode.DATA_EXISTS);
        }

        if (StringUtils.hasText(idem)) {
            try {
                OrderIdempotency row = new OrderIdempotency();
                row.setIdempotencyKey(idem);
                row.setOrderId(order.getId());
                row.setPayloadHash(payloadHash);
                row.setStatus("CONFIRMED");
                row.setCreateTime(LocalDateTime.now());
                row.setUpdateTime(LocalDateTime.now());
                orderIdempotencyMapper.insert(row);
            } catch (DuplicateKeyException ex) {
                OrderIdempotency raced = orderIdempotencyMapper.selectById(idem);
                if (raced != null && payloadHash.equals(raced.getPayloadHash())) {
                    PurchaseOrderWithDetails existing = loadOrderWithDetails(raced.getOrderId());
                    if (existing != null) {
                        existing.setIdempotentReplay(true);
                        existing.setOperationStatus("CONFIRMED");
                        Result<?> replayHit = Result.success(existing, "幂等命中，返回已有订单");
                        erpOperationService.complete(operationId, replayHit);
                        return replayHit;
                    }
                }
                Map<String, Object> conflict = new HashMap<>();
                conflict.put("idempotencyKey", idem);
                conflict.put("expectedPayloadHash", raced != null ? raced.getPayloadHash() : null);
                conflict.put("actualPayloadHash", payloadHash);
                conflict.put("operationStatus", "REJECTED");
                return Result.error(ResultCode.IDEMPOTENCY_CONFLICT.getCode(),
                        ResultCode.IDEMPOTENCY_CONFLICT.getMessage(),
                        conflict);
            }
        }

        PurchaseOrderWithDetails created = loadOrderWithDetails(order.getId());
        if (created == null) {
            return Result.error(ResultCode.SERVER_ERROR);
        }
        created.setIdempotencyKey(idem);
        created.setPayloadHash(payloadHash);
        created.setOperationStatus("CONFIRMED");
        if (mqEnabled && created.getStatus() != null && created.getStatus() == 1) {
            localMessageService.enqueueOrderPendingCancel(
                    created.getId(),
                    LocalDateTime.now().plusHours(Math.max(1, pendingCancelHours))
            );
        }
        Result<?> createdResult = Result.success(created, "创建成功");
        erpOperationService.complete(operationId, createdResult);
        return createdResult;
    }

    @Override
    public Result<?> getByIdempotencyKey(String idempotencyKey) {
        if (!StringUtils.hasText(idempotencyKey)) {
            return Result.paramError("idempotencyKey 不能为空");
        }
        OrderIdempotency binding = orderIdempotencyMapper.selectById(idempotencyKey.trim());
        if (binding == null) {
            Map<String, Object> data = new HashMap<>();
            data.put("idempotencyKey", idempotencyKey);
            data.put("operationStatus", "UNKNOWN");
            return Result.error(404, "未找到幂等请求: " + idempotencyKey, data);
        }
        PurchaseOrderWithDetails existing = loadOrderWithDetails(binding.getOrderId());
        if (existing == null) {
            return Result.error(500, "幂等记录存在但订单不存在", Map.of("operationStatus", "UNKNOWN"));
        }
        existing.setIdempotencyKey(binding.getIdempotencyKey());
        existing.setPayloadHash(binding.getPayloadHash());
        existing.setOperationStatus("CONFIRMED");
        return Result.success(existing, "订单回查成功");
    }

    @Override
    public PurchaseOrderWithDetails loadOrderWithDetails(Long orderId) {
        if (orderId == null) {
            return null;
        }
        PurchaseOrder order = getById(orderId);
        if (order == null) {
            return null;
        }
        PurchaseOrderWithDetails view = new PurchaseOrderWithDetails();
        view.setId(order.getId());
        view.setOrderNumber(order.getOrderNumber());
        view.setTotalAmount(order.getTotalAmount());
        view.setStatus(order.getStatus());
        view.setOrderTime(order.getOrderTime());
        view.setExpectedDeliveryDate(order.getExpectedDeliveryDate());
        view.setActualDeliveryDate(order.getActualDeliveryDate());
        view.setCreatedBy(order.getCreatedBy());
        view.setRemark(order.getRemark());
        view.setIdempotencyKey(order.getIdempotencyKey());
        view.setPayloadHash(order.getPayloadHash());
        view.setDeleted(order.getDeleted());
        view.setCreateTime(order.getCreateTime());
        view.setUpdateTime(order.getUpdateTime());

        List<OrderDetail> details = orderDetailMapper.selectList(
                new LambdaQueryWrapper<OrderDetail>().eq(OrderDetail::getOrderId, orderId)
        );
        List<OrderDetailWithPart> detailWithParts = new ArrayList<>();
        for (OrderDetail detail : details) {
            OrderDetailWithPart detailWithPart = new OrderDetailWithPart();
            detailWithPart.setId(detail.getId());
            detailWithPart.setOrderId(detail.getOrderId());
            detailWithPart.setPartId(detail.getPartId());
            detailWithPart.setQuantity(detail.getQuantity());
            detailWithPart.setUnitPrice(detail.getUnitPrice());
            detailWithPart.setSubtotal(detail.getSubtotal());
            detailWithPart.setRemark(detail.getRemark());
            detailWithPart.setDeleted(detail.getDeleted());
            detailWithPart.setCreateTime(detail.getCreateTime());
            detailWithPart.setUpdateTime(detail.getUpdateTime());
            detailWithPart.setPartDetail(partMapper.selectById(detail.getPartId()));
            detailWithParts.add(detailWithPart);
        }
        view.setOrderDetail(detailWithParts);
        return view;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public boolean updateById(PurchaseOrder order) {
        if (order == null || order.getId() == null) {
            return false;
        }

        Long orderId = order.getId();

        // 1. 物理删除订单明细表中该订单的所有明细数据（绕过 @TableLogic，直接 DELETE）
        orderDetailMapper.physicalDeleteByOrderId(orderId);

        // 2. 设置默认值
        if (order.getOrderTime() == null) {
            order.setOrderTime(LocalDateTime.now());
        }

        if (order.getStatus() == null || order.getStatus() == 0) {
            order.setStatus(1); // 待审核（Harness/MCP 0 与缺省归一）
        }

        // 3. 计算总金额
        BigDecimal totalAmount = BigDecimal.ZERO;
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    if (detailWithPart.getQuantity() != null && detailWithPart.getUnitPrice() != null) {
                        totalAmount = totalAmount.add(
                            detailWithPart.getUnitPrice().multiply(BigDecimal.valueOf(detailWithPart.getQuantity())));
                    }
                }
            }
        }
        order.setTotalAmount(totalAmount);

        // 4. 物理删除原订单主表数据，再重新插入
        baseMapper.physicalDeleteById(orderId);
        // 手动设置deleted、createTime、updateTime字段
        order.setDeleted(0);
        order.setCreateTime(LocalDateTime.now());
        order.setUpdateTime(LocalDateTime.now());
        baseMapper.insert(order);

        // 5. 插入新的订单明细数据
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    // 创建纯OrderDetail对象用于插入，避免partDetail字段干扰
                    OrderDetail detail = OrderDetail.builder()
                            .orderId(orderId)
                            .partId(detailWithPart.getPartId())
                            .quantity(detailWithPart.getQuantity())
                            .unitPrice(detailWithPart.getUnitPrice())
                            .remark(detailWithPart.getRemark())
                            .build();
                    // 手动设置deleted、createTime、updateTime字段
                    detail.setDeleted(0);
                    detail.setCreateTime(LocalDateTime.now());
                    detail.setUpdateTime(LocalDateTime.now());
                    orderDetailMapper.insert(detail);
                }
            }
        }
        return true;
    }

    @Override
    public boolean updateOrderStatus(Long id, Integer status) {
        if (id == null || status == null) {
            return false;
        }
        PurchaseOrder current = getById(id);
        if (current == null || current.getStatus() == null) {
            return false;
        }
        int from = current.getStatus();
        if (from == status) {
            return true;
        }
        if (TERMINAL_STATUS.contains(from)) {
            return false;
        }
        Set<Integer> allowed = STATUS_TRANSITIONS.get(from);
        if (allowed == null || !allowed.contains(status)) {
            return false;
        }

        LambdaUpdateWrapper<PurchaseOrder> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(PurchaseOrder::getStatus, status)
               .eq(PurchaseOrder::getId, id)
               .eq(PurchaseOrder::getStatus, from);
        if (status == 4) {
            wrapper.set(PurchaseOrder::getActualDeliveryDate, LocalDate.now());
        }
        return update(wrapper);
    }

    @Override
    public OrderStatistics getOrderStatistics(LocalDate startDate, LocalDate endDate) {
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();

        if (startDate != null) {
            wrapper.ge(PurchaseOrder::getOrderTime, startDate.atStartOfDay());
        }

        if (endDate != null) {
            wrapper.le(PurchaseOrder::getOrderTime, endDate.plusDays(1).atStartOfDay());
        }

        List<PurchaseOrder> orders = baseMapper.selectList(wrapper);

        long totalOrders = orders.size();
        long totalAmount = orders.stream()
                .map(order -> order.getTotalAmount() != null ? order.getTotalAmount() : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .longValue();
        long completedOrders = orders.stream()
                .filter(order -> order.getStatus() != null && order.getStatus() == 4)
                .count();
        long pendingOrders = orders.stream()
                .filter(order -> order.getStatus() != null && (order.getStatus() == 1 || order.getStatus() == 2 || order.getStatus() == 3))
                .count();

        return new OrderStatistics() {
            @Override
            public long getTotalOrders() {
                return totalOrders;
            }

            @Override
            public long getTotalAmount() {
                return totalAmount;
            }

            @Override
            public long getCompletedOrders() {
                return completedOrders;
            }

            @Override
            public long getPendingOrders() {
                return pendingOrders;
            }
        };
    }

    @Override
    public List<OrderDetailWithPartAndSupplier> searchOrderDetails(String partName, LocalDateTime startDate, LocalDateTime endDate) {
        // 1. 先根据时间范围查出所有订单ID
        LambdaQueryWrapper<PurchaseOrder> orderWrapper = new LambdaQueryWrapper<>();
        if (startDate != null) {
            orderWrapper.ge(PurchaseOrder::getOrderTime, startDate);
        }
        if (endDate != null) {
            orderWrapper.le(PurchaseOrder::getOrderTime, endDate);
        }
        List<PurchaseOrder> orders = baseMapper.selectList(orderWrapper);
        if (orders == null || orders.isEmpty()) {
            return new ArrayList<>();
        }
        List<Long> orderIds = orders.stream().map(PurchaseOrder::getId).collect(Collectors.toList());

        // 2. 查询所有订单的明细
        LambdaQueryWrapper<OrderDetail> detailWrapper = new LambdaQueryWrapper<>();
        detailWrapper.in(OrderDetail::getOrderId, orderIds);
        List<OrderDetail> allDetails = orderDetailMapper.selectList(detailWrapper);
        if (allDetails == null || allDetails.isEmpty()) {
            return new ArrayList<>();
        }

        // 3. 收集所有 partId
        List<Long> partIds = allDetails.stream()
                .map(OrderDetail::getPartId)
                .distinct()
                .collect(Collectors.toList());

        // 4. 一次性查出所有涉及的零部件
        LambdaQueryWrapper<Part> partWrapper = new LambdaQueryWrapper<>();
        partWrapper.in(Part::getId, partIds);
        if (StringUtils.hasText(partName)) {
            partWrapper.like(Part::getName, partName);
        }
        List<Part> matchedParts = partMapper.selectList(partWrapper);
        if (matchedParts == null || matchedParts.isEmpty()) {
            return new ArrayList<>();
        }
        Map<Long, Part> partMap = matchedParts.stream()
                .collect(Collectors.toMap(Part::getId, p -> p));

        // 5. 只保留被 partName 过滤命中的明细
        List<OrderDetail> filteredDetails = allDetails.stream()
                .filter(d -> partMap.containsKey(d.getPartId()))
                .collect(Collectors.toList());

        // 6. 收集涉及的供应商ID
        List<Long> supplierIds = matchedParts.stream()
                .map(Part::getSupplierId)
                .filter(sid -> sid != null)
                .distinct()
                .collect(Collectors.toList());

        // 7. 一次性查出所有涉及的供应商
        Map<Long, Supplier> supplierMap = Map.of();
        if (!supplierIds.isEmpty()) {
            LambdaQueryWrapper<Supplier> supplierWrapper = new LambdaQueryWrapper<>();
            supplierWrapper.in(Supplier::getId, supplierIds);
            List<Supplier> suppliers = supplierMapper.selectList(supplierWrapper);
            supplierMap = suppliers.stream().collect(Collectors.toMap(Supplier::getId, s -> s));
        }

        // 8. 构建嵌套返回结果
        List<OrderDetailWithPartAndSupplier> result = new ArrayList<>();
        for (OrderDetail detail : filteredDetails) {
            Part part = partMap.get(detail.getPartId());

            OrderDetailWithPartAndSupplier detailDTO = new OrderDetailWithPartAndSupplier();
            detailDTO.setId(detail.getId());
            detailDTO.setOrderId(detail.getOrderId());
            detailDTO.setPartId(detail.getPartId());
            detailDTO.setQuantity(detail.getQuantity());
            detailDTO.setUnitPrice(detail.getUnitPrice());
            detailDTO.setSubtotal(detail.getSubtotal());
            detailDTO.setRemark(detail.getRemark());
            detailDTO.setCreateTime(detail.getCreateTime());
            detailDTO.setUpdateTime(detail.getUpdateTime());

            // 零部件信息
            PartWithSupplier partDTO = new PartWithSupplier();
            partDTO.setId(part.getId());
            partDTO.setPartCode(part.getPartCode());
            partDTO.setName(part.getName());
            partDTO.setModel(part.getModel());
            partDTO.setSpecification(part.getSpecification());
            partDTO.setUnit(part.getUnit());
            partDTO.setPurchasePrice(part.getPurchasePrice());
            partDTO.setSuggestedRetailPrice(part.getSuggestedRetailPrice());
            partDTO.setStockWarningValue(part.getStockWarningValue());
            partDTO.setSupplierId(part.getSupplierId());
            partDTO.setCategory(part.getCategory());
            partDTO.setDescription(part.getDescription());
            partDTO.setCreateTime(part.getCreateTime());
            partDTO.setUpdateTime(part.getUpdateTime());

            // 供应商信息
            if (part.getSupplierId() != null && supplierMap.containsKey(part.getSupplierId())) {
                Supplier supplier = supplierMap.get(part.getSupplierId());
                PartWithSupplier.SupplierInfo supplierInfo = new PartWithSupplier.SupplierInfo();
                supplierInfo.setId(supplier.getId());
                supplierInfo.setSupplierCode(supplier.getSupplierCode());
                supplierInfo.setName(supplier.getName());
                supplierInfo.setContactPerson(supplier.getContactPerson());
                supplierInfo.setPhone(supplier.getPhone());
                supplierInfo.setEmail(supplier.getEmail());
                supplierInfo.setAddress(supplier.getAddress());
                supplierInfo.setCreditRating(supplier.getCreditRating());
                supplierInfo.setStatus(supplier.getStatus());
                partDTO.setSupplier(supplierInfo);
            }

            detailDTO.setPartDetail(partDTO);
            result.add(detailDTO);
        }

        return result;
    }
}
