package com.motorparts.catalog.fitment;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.motorparts.catalog.vehicle.VehicleModel;
import com.motorparts.catalog.vehicle.VehicleModelMapper;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.common.exception.BusinessException;
import com.motorparts.entity.Part;
import com.motorparts.mapper.PartMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class PartFitmentService {
    private final PartFitmentMapper fitmentMapper;
    private final VehicleModelMapper vehicleModelMapper;
    private final PartMapper partMapper;

    @Transactional(readOnly = true)
    public List<PartFitmentView> listForPart(Long partId) {
        requirePart(partId);
        List<PartFitment> fitments = fitmentMapper.selectList(new LambdaQueryWrapper<PartFitment>()
                .eq(PartFitment::getPartId, partId));
        if (fitments.isEmpty()) return List.of();
        Map<Long, VehicleModel> vehicles = new HashMap<>();
        for (VehicleModel vehicle : vehicleModelMapper.selectBatchIds(
                fitments.stream().map(PartFitment::getVehicleModelId).distinct().toList())) {
            vehicles.put(vehicle.getId(), vehicle);
        }
        return fitments.stream()
                .filter(fitment -> vehicles.containsKey(fitment.getVehicleModelId()))
                .map(fitment -> toView(fitment, vehicles.get(fitment.getVehicleModelId())))
                .sorted(Comparator.comparing((PartFitmentView view) -> view.vehicleModel().getBrand(),
                                Comparator.nullsLast(String::compareToIgnoreCase))
                        .thenComparing(view -> view.vehicleModel().getSeries(), Comparator.nullsLast(String::compareToIgnoreCase))
                        .thenComparing(view -> view.vehicleModel().getModel(), Comparator.nullsLast(String::compareToIgnoreCase))
                        .thenComparing(view -> view.vehicleModel().getModelYearStart(), Comparator.nullsLast(Integer::compareTo)))
                .toList();
    }

    @Transactional
    public PartFitmentView add(Long partId, PartFitmentRequest request) {
        requirePart(partId);
        VehicleModel vehicle = requireVehicle(request.vehicleModelId());
        if (find(partId, request.vehicleModelId()) != null) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "该零件已经绑定此车型");
        }
        PartFitment fitment = new PartFitment();
        fitment.setPartId(partId);
        fitment.setVehicleModelId(request.vehicleModelId());
        fitment.setFitmentNote(trimToNull(request.fitmentNote()));
        fitment.setVerified(Boolean.TRUE.equals(request.verified()));
        LocalDateTime now = LocalDateTime.now();
        fitment.setCreateTime(now);
        fitment.setUpdateTime(now);
        try {
            if (fitmentMapper.insert(fitment) != 1) {
                throw new BusinessException("车型适配关系创建失败");
            }
        } catch (DuplicateKeyException duplicate) {
            throw new BusinessException(ResultCode.DATA_EXISTS, "该零件已经绑定此车型");
        }
        return toView(fitment, vehicle);
    }

    @Transactional
    public void delete(Long partId, Long vehicleModelId) {
        requirePart(partId);
        PartFitment fitment = find(partId, vehicleModelId);
        if (fitment == null) {
            throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "车型适配关系不存在");
        }
        if (fitmentMapper.deleteById(fitment.getId()) != 1) {
            throw new BusinessException("车型适配关系删除失败");
        }
    }

    @Transactional(readOnly = true)
    public List<Part> searchPartsByVehicle(Long vehicleModelId) {
        requireVehicle(vehicleModelId);
        List<PartFitment> fitments = fitmentMapper.selectList(new LambdaQueryWrapper<PartFitment>()
                .eq(PartFitment::getVehicleModelId, vehicleModelId)
                .orderByDesc(PartFitment::getVerified)
                .orderByAsc(PartFitment::getPartId));
        if (fitments.isEmpty()) return List.of();
        Map<Long, Part> byId = new HashMap<>();
        for (Part part : partMapper.selectBatchIds(fitments.stream().map(PartFitment::getPartId).distinct().toList())) {
            byId.put(part.getId(), part);
        }
        List<Part> ordered = new ArrayList<>();
        for (PartFitment fitment : fitments) {
            Part part = byId.get(fitment.getPartId());
            if (part != null && ordered.stream().noneMatch(existing -> existing.getId().equals(part.getId()))) {
                ordered.add(part);
            }
        }
        return ordered;
    }

    private PartFitment find(Long partId, Long vehicleModelId) {
        return fitmentMapper.selectOne(new LambdaQueryWrapper<PartFitment>()
                .eq(PartFitment::getPartId, partId)
                .eq(PartFitment::getVehicleModelId, vehicleModelId));
    }

    private Part requirePart(Long partId) {
        Part part = partId == null ? null : partMapper.selectById(partId);
        if (part == null) throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "零件不存在");
        return part;
    }

    private VehicleModel requireVehicle(Long id) {
        VehicleModel vehicle = id == null ? null : vehicleModelMapper.selectById(id);
        if (vehicle == null) throw new BusinessException(ResultCode.DATA_NOT_EXISTS, "车型不存在");
        return vehicle;
    }

    private static PartFitmentView toView(PartFitment fitment, VehicleModel vehicle) {
        return new PartFitmentView(fitment.getId(), fitment.getPartId(), fitment.getVehicleModelId(),
                fitment.getFitmentNote(), Boolean.TRUE.equals(fitment.getVerified()), fitment.getCreateTime(), vehicle);
    }

    private static String trimToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }
}
