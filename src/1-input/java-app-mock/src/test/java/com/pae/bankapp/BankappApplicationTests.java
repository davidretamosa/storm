package com.pae.bankapp;

import com.pae.bankapp.dto.TransferRequest;
import com.pae.bankapp.dto.TransferResponse;
import com.pae.bankapp.entity.Account;
import com.pae.bankapp.entity.User;
import com.pae.bankapp.exception.ResourceNotFoundException;
import com.pae.bankapp.repository.AccountRepository;
import com.pae.bankapp.repository.TransactionRepository;
import com.pae.bankapp.repository.UserRepository;
import com.pae.bankapp.service.TransferService;
import com.pae.bankapp.service.UserService;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class BankappApplicationTests {

	@Test
	void invalidUserShouldReturnClearNotFoundMessage() {
		UserRepository userRepository = mock(UserRepository.class);
		when(userRepository.findById(999L)).thenReturn(Optional.empty());

		UserService userService = new UserService(userRepository);
		ResourceNotFoundException exception = assertThrows(ResourceNotFoundException.class,
				() -> userService.findById(999L));

		assertThat(exception.getMessage()).isEqualTo("User with id 999 was not found.");
	}

	@Test
	void sameAccountTransferShouldReturnReadableBusinessMessage() {
		Validator validator = Validation.buildDefaultValidatorFactory().getValidator();
		TransferRequest request = new TransferRequest();
		request.setFromAccountId(1L);
		request.setToAccountId(1L);
		request.setAmount(BigDecimal.TEN);
		request.setConcept("Test");

		Set<ConstraintViolation<TransferRequest>> violations = validator.validate(request);

		assertThat(violations).isNotEmpty();
		assertThat(violations)
				.extracting(ConstraintViolation::getMessage)
				.contains("Source and destination account must be different.");
	}

	@Test
	void transferShouldReturnParticipantsAmountAndUpdatedBalances() {
		AccountRepository accountRepository = mock(AccountRepository.class);
		TransactionRepository transactionRepository = mock(TransactionRepository.class);
		User sender = new User();
		sender.setName("Alice");
		User recipient = new User();
		recipient.setName("Bob");
		Account source = new Account(1L, "IBAN-SOURCE", new BigDecimal("100.00"), sender, null);
		Account destination = new Account(2L, "IBAN-DESTINATION", new BigDecimal("25.00"), recipient, null);
		when(accountRepository.findById(1L)).thenReturn(Optional.of(source));
		when(accountRepository.findById(2L)).thenReturn(Optional.of(destination));
		TransferRequest request = new TransferRequest();
		request.setFromAccountId(1L);
		request.setToAccountId(2L);
		request.setAmount(new BigDecimal("30.00"));

		TransferResponse response = new TransferService(accountRepository, transactionRepository).transfer(request);

		assertThat(response.message()).contains("Alice", "IBAN-SOURCE", "Bob", "IBAN-DESTINATION", "30.00");
		assertThat(response.amount()).isEqualByComparingTo("30.00");
		assertThat(response.fromAccount().userName()).isEqualTo("Alice");
		assertThat(response.fromAccount().balance()).isEqualByComparingTo("70.00");
		assertThat(response.toAccount().userName()).isEqualTo("Bob");
		assertThat(response.toAccount().balance()).isEqualByComparingTo("55.00");
	}

}
