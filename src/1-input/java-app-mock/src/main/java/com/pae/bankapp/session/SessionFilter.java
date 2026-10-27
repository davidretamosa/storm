
package com.pae.bankapp.session;

import com.pae.bankapp.entity.UserSession;
import com.pae.bankapp.service.SessionService;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
public class SessionFilter extends OncePerRequestFilter {

    private final SessionService sessionService;

    public SessionFilter(SessionService sessionService) {
        this.sessionService = sessionService;
    }

    @Override
    protected boolean shouldNotFilter(
            HttpServletRequest request) {

        String path = request.getServletPath();

        return !path.startsWith("/api/")
                || path.equals("/api/sessions")
                || path.startsWith("/api/sessions/");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain)
            throws ServletException, IOException {

        String sessionId = request.getHeader("X-Session-Id");

        if (sessionId == null || sessionId.isBlank()) {
            response.sendError(
                    HttpServletResponse.SC_BAD_REQUEST,
                    "Missing X-Session-Id"
            );
            return;
        }

        UserSession session;

        try {
            session = sessionService.getValidSession(sessionId);
        } catch (Exception ex) {
            response.sendError(
                    HttpServletResponse.SC_BAD_REQUEST,
                    "Invalid or expired session"
            );
            return;
        }

        request.setAttribute("sessionId", session.getId());
        request.setAttribute(
                "userId",
                session.getUser().getId()
        );

        filterChain.doFilter(request, response);
    }
}
