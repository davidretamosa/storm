
package com.pae.bankapp.dto;

import java.time.Instant;

public record SessionDTO(
        String sessionId,
        Long userId,
        Instant createdAt,
        Instant expiresAt,
        boolean active
) {
}
