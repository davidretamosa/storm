package com.pae.bankapp.service;

import com.pae.bankapp.dto.UserDTO;
import com.pae.bankapp.entity.User;
import com.pae.bankapp.exception.ResourceNotFoundException;
import com.pae.bankapp.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Business logic layer for users.
 * The controller delegates here; this class talks to the repository
 * and converts between entities (DB) and DTOs (API).
 */
@Service                 // Registers this class as a Spring bean
@RequiredArgsConstructor // Lombok: constructor for final fields; Spring injects the repository through it
public class UserService {

    private final UserRepository userRepository;

    // GET /api/users
    public List<UserDTO> findAll() {
        return userRepository.findAll().stream()
                .map(this::toDTO)   // convert each User into a UserDTO
                .toList();
    }

    // GET /api/users/{id}
    public UserDTO findById(Long id) {
        // findById returns an Optional (the user may not exist).
        // If it is empty we throw an exception, which ends up as a 404.
        User user = userRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("User with id " + id + " not found"));
        return toDTO(user);
    }

    // POST /api/users
    public UserDTO create(UserDTO dto) {
        User user = new User();
        user.setName(dto.getName());
        user.setEmail(dto.getEmail());
        // If the email already exists, the unique constraint in the database
        // makes save() throw a DataIntegrityViolationException (handled as a 400)
        User saved = userRepository.save(user);  // "saved" already has its generated id
        return toDTO(saved);
    }

    // Copies the entity fields into a DTO (what the client will see)
    private UserDTO toDTO(User user) {
        UserDTO dto = new UserDTO();
        dto.setId(user.getId());
        dto.setName(user.getName());
        dto.setEmail(user.getEmail());
        return dto;
    }
}