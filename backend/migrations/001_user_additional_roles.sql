CREATE TABLE user_additional_roles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role_code VARCHAR(30) NOT NULL,
    assigned_by INTEGER NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_additional_roles_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_additional_roles_assigned_by
        FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_user_additional_role UNIQUE (user_id, role_code),
    CONSTRAINT ck_user_additional_role_allowed
        CHECK (role_code IN ('almacen', 'cajero', 'supervisor', 'contador'))
);
