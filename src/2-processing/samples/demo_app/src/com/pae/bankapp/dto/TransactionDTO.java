package com.pae.bankapp.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

// SOLO PARA PRUEBAS del jar_parser (en la app real Martina usa Lombok: @Data genera los getters/setters).
public class TransactionDTO {
    private Long id;
    private String type;
    private BigDecimal amount;
    private String concept;
    private LocalDateTime timestamp;
}
