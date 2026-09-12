-- Criar e selecionar o banco de dados
CREATE DATABASE IF NOT EXISTS `chat_system` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `chat_system`;

-- 1. Tabela de Usuários
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(50) UNIQUE NOT NULL,
    `password_hash` VARCHAR(255) NOT NULL,
    `email` VARCHAR(100),
    `full_name` VARCHAR(100),
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `last_seen` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `is_online` BOOLEAN DEFAULT FALSE,
    `last_ip` VARCHAR(45),
    `user_agent` TEXT,
    `auto_login_token` VARCHAR(255),
    `token_expires` TIMESTAMP NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Tabela de Mensagens
CREATE TABLE IF NOT EXISTS `messages` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `from_user` VARCHAR(50) NOT NULL,
    `to_user` VARCHAR(50) NULL,
    `room_name` VARCHAR(50) NULL,
    `message` TEXT NOT NULL,
    `timestamp` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `file_path` VARCHAR(255),
    `file_name` VARCHAR(255),
    `file_size` BIGINT DEFAULT 0,
    `mime_type` VARCHAR(100),
    `message_type` ENUM('text', 'file', 'image', 'video', 'audio') DEFAULT 'text',
    `is_read` BOOLEAN DEFAULT FALSE,
    INDEX `idx_room` (`room_name`),
    INDEX `idx_from_user` (`from_user`),
    INDEX `idx_to_user` (`to_user`),
    CONSTRAINT `fk_messages_from_user` FOREIGN KEY (`from_user`) REFERENCES `users` (`username`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Tabela de Salas
CREATE TABLE IF NOT EXISTS `rooms` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(50) UNIQUE NOT NULL,
    `created_by` VARCHAR(50) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `is_private` BOOLEAN DEFAULT FALSE,
    `password_hash` VARCHAR(255),
    `description` TEXT,
    CONSTRAINT `fk_rooms_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`username`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Tabela de Membros das Salas
CREATE TABLE IF NOT EXISTS `room_members` (
    `room_id` INT NOT NULL,
    `username` VARCHAR(50) NOT NULL,
    `joined_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `role` ENUM('admin', 'moderator', 'member') DEFAULT 'member',
    PRIMARY KEY (`room_id`, `username`),
    CONSTRAINT `fk_room_members_room` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_room_members_user` FOREIGN KEY (`username`) REFERENCES `users` (`username`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Tabela de Códigos de Recuperação
CREATE TABLE IF NOT EXISTS `recovery_codes` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `email` VARCHAR(100) NOT NULL,
    `code` VARCHAR(6) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `expires_at` TIMESTAMP NOT NULL,
    `used` BOOLEAN DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Tabela de Logs de Segurança
CREATE TABLE IF NOT EXISTS `security_logs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(50) NULL,
    `ip` VARCHAR(45) NOT NULL,
    `event_type` ENUM('login', 'logout', 'failed_login', 'recovery_request', 'password_change', 'register') NOT NULL,
    `details` TEXT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ========================================================
-- INSERÇÃO DE DADOS INICIAIS
-- Nota: Os hashes SHA256 abaixo foram gerados para:
-- admin123 -> c7ad44cbad762a5da0a452f9e854fdc1e0e7a52a38015f23f3eab1d80b931dd4
-- demo123  -> 2e9d226a260f85ee9ee5f586a1df0b457b019b841e2a5370f1a92e105e192c73
-- ========================================================

-- Inserir usuário Admin
INSERT IGNORE INTO `users` (`username`, `password_hash`, `email`, `full_name`)
VALUES ('admin', 'c7ad44cbad762a5da0a452f9e854fdc1e0e7a52a38015f23f3eab1d80b931dd4', 'admin@chat.com', 'Administrador');

-- Criar Sala Geral
INSERT IGNORE INTO `rooms` (`name`, `created_by`, `description`)
VALUES ('geral', 'admin', 'Sala geral de conversas');

-- Adicionar Admin como Admin da Sala Geral
INSERT IGNORE INTO `room_members` (`room_id`, `username`, `role`)
SELECT `id`, 'admin', 'admin' FROM `rooms` WHERE `name` = 'geral';

-- Inserir usuário Demo
INSERT IGNORE INTO `users` (`username`, `password_hash`, `email`, `full_name`)
VALUES ('demo', '2e9d226a260f85ee9ee5f586a1df0b457b019b841e2a5370f1a92e105e192c73', 'demo@chat.com', 'Usuário Demo');

-- Adicionar Demo como Membro da Sala Geral
INSERT IGNORE INTO `room_members` (`room_id`, `username`, `role`)
SELECT `id`, 'demo', 'member' FROM `rooms` WHERE `name` = 'geral';
