package com.pae.labapi.item;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;

/** Cuerpo de la petición POST /api/items. */
public record NuevoItem(
        @NotBlank(message = "el nombre es obligatorio")
        @Size(max = 100, message = "el nombre no puede superar 100 caracteres")
        String nombre,

        @NotNull(message = "el precio es obligatorio")
        @DecimalMin(value = "0.0", message = "el precio no puede ser negativo")
        @Digits(integer = 8, fraction = 2, message = "el precio admite como máximo 2 decimales")
        BigDecimal precio) {
}
