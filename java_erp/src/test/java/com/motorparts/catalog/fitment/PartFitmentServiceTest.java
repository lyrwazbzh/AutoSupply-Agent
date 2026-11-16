package com.motorparts.catalog.fitment;

import com.motorparts.catalog.vehicle.VehicleModel;
import com.motorparts.catalog.vehicle.VehicleModelMapper;
import com.motorparts.common.exception.BusinessException;
import com.motorparts.entity.Part;
import com.motorparts.mapper.PartMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PartFitmentServiceTest {
    private PartFitmentMapper fitmentMapper;
    private VehicleModelMapper vehicleMapper;
    private PartMapper partMapper;
    private PartFitmentService service;

    @BeforeEach
    void setUp() {
        fitmentMapper = mock(PartFitmentMapper.class);
        vehicleMapper = mock(VehicleModelMapper.class);
        partMapper = mock(PartMapper.class);
        service = new PartFitmentService(fitmentMapper, vehicleMapper, partMapper);
    }

    @Test
    void rejectsDuplicateFitment() {
        when(partMapper.selectById(1L)).thenReturn(part(1L));
        when(vehicleMapper.selectById(2L)).thenReturn(vehicle(2L));
        when(fitmentMapper.selectOne(any())).thenReturn(fitment(9L, 1L, 2L, true));

        assertThrows(BusinessException.class,
                () -> service.add(1L, new PartFitmentRequest(2L, null, true)));
        verify(fitmentMapper, never()).insert(any());
    }

    @Test
    void createsVerifiedFitmentAndReturnsVehicleDetails() {
        when(partMapper.selectById(1L)).thenReturn(part(1L));
        when(vehicleMapper.selectById(2L)).thenReturn(vehicle(2L));
        when(fitmentMapper.selectOne(any())).thenReturn(null);
        when(fitmentMapper.insert(any())).thenAnswer(invocation -> {
            PartFitment value = invocation.getArgument(0);
            value.setId(11L);
            return 1;
        });

        PartFitmentView created = service.add(1L, new PartFitmentRequest(2L, "原厂规格", true));

        assertEquals(11L, created.id());
        assertEquals("Honda", created.vehicleModel().getBrand());
        assertEquals(true, created.verified());
    }

    @Test
    void searchByVehicleKeepsVerifiedPartsFirst() {
        when(vehicleMapper.selectById(2L)).thenReturn(vehicle(2L));
        when(fitmentMapper.selectList(any())).thenReturn(List.of(
                fitment(1L, 8L, 2L, true), fitment(2L, 9L, 2L, false)));
        when(partMapper.selectBatchIds(any())).thenReturn(List.of(part(9L), part(8L)));

        assertEquals(List.of(8L, 9L), service.searchPartsByVehicle(2L).stream().map(Part::getId).toList());
    }

    private static Part part(Long id) {
        Part part = new Part();
        part.setId(id);
        part.setPartCode("P-" + id);
        part.setName("零件" + id);
        return part;
    }

    private static VehicleModel vehicle(Long id) {
        VehicleModel vehicle = new VehicleModel();
        vehicle.setId(id);
        vehicle.setBrand("Honda");
        vehicle.setSeries("CBR");
        vehicle.setModel("CBR500R");
        return vehicle;
    }

    private static PartFitment fitment(Long id, Long partId, Long vehicleId, boolean verified) {
        PartFitment fitment = new PartFitment();
        fitment.setId(id);
        fitment.setPartId(partId);
        fitment.setVehicleModelId(vehicleId);
        fitment.setVerified(verified);
        return fitment;
    }
}
