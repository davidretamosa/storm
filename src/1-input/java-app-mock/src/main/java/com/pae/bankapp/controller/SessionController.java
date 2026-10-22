
package com.pae.bankapp.controller;

import com.pae.bankapp.dto.CreateSessionRequest;
import com.pae.bankapp.dto.SessionDTO;
import com.pae.bankapp.service.SessionService;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/sessions")
@RequiredArgsConstructor
public class SessionController {

    private final SessionService sessionService;

    // POST /api/sessions -> 201 Created
    @PostMapping
    public ResponseEntity<SessionDTO> create(
            @Valid @RequestBody CreateSessionRequest request) {

        SessionDTO session = sessionService.createSession(
                request.userId()
        );

        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(session);
    }

    // GET /api/sessions/{id} -> 200 OK
    @GetMapping("/{id}")
    public SessionDTO getById(@PathVariable String id) {

        return sessionService.getSession(id);
    }

    // DELETE /api/sessions/{id} -> 204 No Content
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> close(@PathVariable String id) {

        sessionService.closeSession(id);

        return ResponseEntity.noContent().build();
    }
}
