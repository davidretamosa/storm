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
public TransactionDTO getTransactionById(Long id) {

    Transaction transaction = transactionRepository.findById(id)
            .orElseThrow(() ->
                    new ResourceNotFoundException(
                            "Transaction not found with id: " + id));

    return toTransactionDTO(transaction);
}