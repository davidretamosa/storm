
package com.pae.bankapp.dto;

import jakarta.validation.constraints.NotNull;

public record CreateSessionRequest(
        @NotNull Long userId
) {
}
