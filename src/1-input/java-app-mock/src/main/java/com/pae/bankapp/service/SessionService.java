
package com.pae.bankapp.service;

import com.pae.bankapp.dto.SessionDTO;
import com.pae.bankapp.entity.User;
import com.pae.bankapp.entity.UserSession;
import com.pae.bankapp.repository.UserRepository;
import com.pae.bankapp.repository.UserSessionRepository;

import lombok.RequiredArgsConstructor;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class SessionService {

    private final UserRepository userRepository;
    private final UserSessionRepository sessionRepository;

    // Create a new session for an existing user
    public SessionDTO createSession(Long userId) {

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND,
                        "User not found"
                ));

        String sessionId = UUID.randomUUID().toString();

        Instant now = Instant.now();
        Instant expiresAt = now.plus(8, ChronoUnit.HOURS);

        UserSession session = new UserSession(
                sessionId,
                user,
                now,
                expiresAt
        );

        sessionRepository.save(session);

        return toDTO(session);
    }

    // Find a session and check that it is still valid
    public UserSession getValidSession(String sessionId) {

        UserSession session = sessionRepository.findById(sessionId)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND,
                        "Session not found"
                ));

        if (!session.isValid()) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Session is closed or expired"
            );
        }

        return session;
    }

    // Get session information
    public SessionDTO getSession(String sessionId) {

        UserSession session = getValidSession(sessionId);

        return toDTO(session);
    }

    // Close a session
    public void closeSession(String sessionId) {

        UserSession session = getValidSession(sessionId);

        session.close();

        sessionRepository.save(session);
    }

    // Convert an entity into a DTO
    private SessionDTO toDTO(UserSession session) {

        return new SessionDTO(
                session.getId(),
                session.getUser().getId(),
                session.getCreatedAt(),
                session.getExpiresAt(),
                session.isActive()
        );
    }
}
