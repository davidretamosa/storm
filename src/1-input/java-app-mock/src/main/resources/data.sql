-- Usuarios de prueba
INSERT INTO users (id, name, email) VALUES (1, 'Laura Martínez', 'laura@example.com');
INSERT INTO users (id, name, email) VALUES (2, 'Marc Ferrer', 'marc@example.com');
INSERT INTO users (id, name, email) VALUES (3, 'Aisha Khan', 'aisha@example.com');

-- Cuentas asociadas a usuarios
INSERT INTO accounts (id, iban, balance, user_id) VALUES (1, 'ES7620770024003102575766', 1500.00, 1);
INSERT INTO accounts (id, iban, balance, user_id) VALUES (2, 'ES9121000418450200051332', 850.50, 2);
INSERT INTO accounts (id, iban, balance, user_id) VALUES (3, 'ES6000491500051234567892', 3200.75, 3);

-- Transacciones de ejemplo
INSERT INTO transactions (id, type, amount, concept, timestamp, account_id) VALUES (1, 'DEPOSIT', 500.00, 'Nómina', '2026-09-01T09:00:00', 1);
INSERT INTO transactions (id, type, amount, concept, timestamp, account_id) VALUES (2, 'WITHDRAWAL', 100.00, 'Cajero', '2026-09-15T18:30:00', 1);
INSERT INTO transactions (id, type, amount, concept, timestamp, account_id) VALUES (3, 'DEPOSIT', 850.50, 'Nómina', '2026-09-01T09:05:00', 2);