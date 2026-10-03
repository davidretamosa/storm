package com.pae.bankapp.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

// SOLO PARA PRUEBAS del jar_parser (en la app real Martina usa Lombok: @Data genera los getters/setters).
public class TransferRequest {
    private Long fromAccountId;
    private Long toAccountId;
    private BigDecimal amount;
    private String concept;
}
