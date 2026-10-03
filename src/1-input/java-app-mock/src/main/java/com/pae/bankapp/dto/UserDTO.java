package com.pae.bankapp.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * Data Transfer Object: the shape of the JSON that goes in and out of the API.
 * We use it instead of the entity so we don't expose the internal DB structure
 * (e.g. the "accounts" list) and so we can validate the input.
 */
@Getter
@Setter
@NoArgsConstructor
public class UserDTO {

    // Output only: if the client sends an "id" in the POST body, it is ignored
    @JsonProperty(access = JsonProperty.Access.READ_ONLY)
    private Long id;

    @NotBlank(message = "Name is required")             // Not null and not empty
    private String name;

    @NotBlank(message = "Email is required")
    @Email(message = "Email format is not valid")       // Must look like an email
    private String email;
}