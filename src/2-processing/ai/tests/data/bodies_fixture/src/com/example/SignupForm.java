package com.example;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;

// Un DTO generic de prova (no es de cap app): un camp per a cada anotacio que llegeix bodies_jar.py
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

    private Long groupId;

    private java.util.List<String> tags;
}
