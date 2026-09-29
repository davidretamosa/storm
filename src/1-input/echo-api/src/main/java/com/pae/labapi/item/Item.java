package com.pae.labapi.item;

import java.math.BigDecimal;
import java.time.Instant;

public record Item(long id, String nombre, BigDecimal precio, Instant creado) {
}
