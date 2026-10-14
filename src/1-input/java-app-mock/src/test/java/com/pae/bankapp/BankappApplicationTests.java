package com.pae.bankapp;

import com.pae.bankapp.dto.TransferRequest;
import com.pae.bankapp.exception.ResourceNotFoundException;
import com.pae.bankapp.repository.UserRepository;
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

}
