
package com.pae.bankapp.repository;

import com.pae.bankapp.entity.UserSession;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface UserSessionRepository
        extends JpaRepository<UserSession, String> {
}
