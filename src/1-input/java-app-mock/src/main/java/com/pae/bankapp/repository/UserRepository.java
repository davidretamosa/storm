package com.pae.bankapp.repository;

import com.pae.bankapp.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

/**
 * Data access layer for User.
 * It is an interface with no implementation: Spring Data JPA creates it automatically.
 * JpaRepository<User, Long> = entity type "User", primary key type "Long".
 * It already provides findAll(), findById(), save(), delete(), etc.
 */
@Repository
public interface UserRepository extends JpaRepository<User, Long> {
}