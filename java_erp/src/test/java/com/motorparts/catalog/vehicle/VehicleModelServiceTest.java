package com.motorparts.catalog.vehicle;

import com.motorparts.common.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class VehicleModelServiceTest {
    private VehicleModelMapper mapper;
    private VehicleModelService service;

    @BeforeEach
    void setUp() {
        mapper = mock(VehicleModelMapper.class);
        service = new VehicleModelService(mapper);
    }

    @Test
    void rejectsReversedModelYearRange() {
        VehicleModel model = vehicle("Honda", "CBR500R", 2024, 2022);

        assertThrows(IllegalArgumentException.class, () -> service.create(model));
        verify(mapper, never()).insert(any());
    }

    @Test
    void rejectsDuplicateNaturalVehicleIdentity() {
        VehicleModel model = vehicle("Honda", "CBR500R", 2022, 2024);
        when(mapper.selectCount(any())).thenReturn(1L);

        assertThrows(BusinessException.class, () -> service.create(model));
        verify(mapper, never()).insert(any());
    }

    @Test
    void normalizesAndCreatesVehicle() {
        VehicleModel model = vehicle(" Honda ", " CBR500R ", 2022, 2024);
        when(mapper.selectCount(any())).thenReturn(0L);
        when(mapper.insert(any())).thenAnswer(invocation -> {
            VehicleModel inserted = invocation.getArgument(0);
            inserted.setId(7L);
            return 1;
        });

        VehicleModel created = service.create(model);

        assertEquals(7L, created.getId());
        assertEquals("Honda", created.getBrand());
        assertEquals("CBR500R", created.getModel());
    }

    private static VehicleModel vehicle(String brand, String modelName, int from, int to) {
        VehicleModel model = new VehicleModel();
        model.setBrand(brand);
        model.setSeries("CBR");
        model.setModel(modelName);
        model.setModelYearStart(from);
        model.setModelYearEnd(to);
        model.setDisplacement(471);
        return model;
    }
}
