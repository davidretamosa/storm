package com.example;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

// Un DTO genérico de prueba (no es de ninguna aplicación): un campo por cada anotación que lee dto_bodies.py
public class SignupForm {
    public static final String KIND = "signup";

    @JsonProperty(access = JsonProperty.Access.READ_ONLY)
    private Long id;

    @NotBlank
    @Size(min = 3, max = 12)
    private String handle;

    @Email
    private String contact;

    @Size(min = 20)
    private String motto;

    @DecimalMin(value = "0.5")
    @DecimalMax(value = "10", inclusive = false)
    private BigDecimal fee;

    @Positive
    private int seats;

    @DecimalMin(value = "500")
    private BigDecimal floor500;

    @Positive
    @DecimalMax(value = "0.5")
    private BigDecimal tiny;

    @Size(min = 40)
    private String slogan;

    @Size(max = 8)
    private String nick;

    @Min(2)
    @Max(9)
    private int rooms;

    private Long groupId;

    private java.util.List<String> tags;
}
