package com.pae.bankapp.controller;

import com.pae.bankapp.dto.UserDTO;
import com.pae.bankapp.service.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * REST layer: receives HTTP requests and returns HTTP responses.
 * It contains no business logic, it only delegates to UserService.
 */
@RestController               // Every method returns data (JSON), not a view
@RequestMapping("/api/users") // Base URL for all endpoints in this class
@RequiredArgsConstructor      // Spring injects the service through the constructor
public class UserController {

    private final UserService userService;

    // GET /api/users -> 200 with the list of users
    @GetMapping
    public List<UserDTO> getAll() {
        return userService.findAll();
    }

    // GET /api/users/{id} -> 200 with the user, or 404 if it does not exist
    @GetMapping("/{id}")
    public UserDTO getById(@PathVariable Long id) {  // @PathVariable takes {id} from the URL
        return userService.findById(id);
    }

    // POST /api/users -> 201 with the created user, or 400 if validation fails
    @PostMapping
    public ResponseEntity<UserDTO> create(@Valid @RequestBody UserDTO dto) {
        // @RequestBody converts the JSON body into a UserDTO
        // @Valid triggers the validations declared in UserDTO (@NotBlank, @Email)
        return ResponseEntity.status(HttpStatus.CREATED).body(userService.create(dto));
    }
}