package com.pae.bankapp.dto;

import com.pae.bankapp.entity.Transaction.TransactionType;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Getter
@Setter
@NoArgsConstructor
public class TransactionDTO {

    private Long id;
    private TransactionType type;
    private BigDecimal amount;
    private String concept;
    private LocalDateTime timestamp;
    private Long accountId;
}