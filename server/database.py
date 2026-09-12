#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file database.py
@brief Classe Database para MySQL
"""

import mysql.connector
from mysql.connector import Error
import hashlib
import logging
from typing import Dict, List, Optional, Any
import time
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    """Classe para gerenciar conexão com MySQL"""
    
    def __init__(self, host="172.18.0.2", port=3306, user="redes2", 
                 password="r3d3s321", database="chat_system"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self.cursor = None
        
    def connect(self) -> bool:
        """Conecta ao banco de dados"""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                use_pure=True
            )
            self.cursor = self.connection.cursor(dictionary=True)
            logger.info(f"Conectado ao MySQL: {self.host}:{self.port}/{self.database}")
            self.init_database()
            return True
        except Error as e:
            logger.error(f"Erro ao conectar MySQL: {e}")
            return False
    
    def disconnect(self):
        """Desconecta do banco"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logger.info("Desconectado do MySQL")
    
    def init_database(self):
        """Inicializa as tabelas"""
        tables = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                email VARCHAR(100),
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_online BOOLEAN DEFAULT FALSE,
                last_ip VARCHAR(45),
                user_agent TEXT,
                auto_login_token VARCHAR(255),
                token_expires TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INT AUTO_INCREMENT PRIMARY KEY,
                from_user VARCHAR(50) NOT NULL,
                to_user VARCHAR(50) NULL,
                room_name VARCHAR(50) NULL,
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_path VARCHAR(255),
                file_name VARCHAR(255),
                file_size BIGINT DEFAULT 0,
                mime_type VARCHAR(100),
                message_type ENUM('text','file','image','video','audio') DEFAULT 'text',
                is_read BOOLEAN DEFAULT FALSE,
                INDEX idx_room (room_name),
                INDEX idx_from_user (from_user),
                INDEX idx_to_user (to_user),
                FOREIGN KEY (from_user) REFERENCES users(username) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                created_by VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_private BOOLEAN DEFAULT FALSE,
                password_hash VARCHAR(255),
                description TEXT,
                FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS room_members (
                room_id INT NOT NULL,
                username VARCHAR(50) NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role ENUM('admin','moderator','member') DEFAULT 'member',
                PRIMARY KEY (room_id, username),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS recovery_codes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(100) NOT NULL,
                code VARCHAR(6) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS security_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NULL,
                ip VARCHAR(45) NOT NULL,
                event_type ENUM('login','logout','failed_login','recovery_request','password_change','register') NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        ]
        
        for sql in tables:
            try:
                self.cursor.execute(sql)
            except Error as e:
                logger.error(f"Erro ao criar tabela: {e}")
        
        # Inserir admin (mesmas credenciais)
        admin_password = self.sha256("admin123")
        try:
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name) "
                "VALUES ('admin', %s, 'admin@chat.com', 'Administrador')",
                (admin_password,)
            )
            self.connection.commit()
            
            # Criar sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO rooms (name, created_by, description) "
                "VALUES ('geral', 'admin', 'Sala geral de conversas')"
            )
            self.connection.commit()
            
            # Adicionar admin à sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, 'admin', 'admin' FROM rooms WHERE name = 'geral'"
            )
            self.connection.commit()
            
            # Inserir usuário demo
            demo_password = self.sha256("demo123")
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name) "
                "VALUES ('demo', %s, 'demo@chat.com', 'Usuário Demo')",
                (demo_password,)
            )
            self.connection.commit()
            
            # Adicionar demo à sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, 'demo', 'member' FROM rooms WHERE name = 'geral'"
            )
            self.connection.commit()
            
            logger.info("Tabelas criadas e usuários inseridos")
        except Error as e:
            logger.error(f"Erro ao inserir dados iniciais: {e}")
    
    def sha256(self, text: str) -> str:
        """Calcula hash SHA256"""
        return hashlib.sha256(text.encode()).hexdigest()
    
    def authenticate_user(self, username: str, password: str) -> bool:
        """Autentica usuário"""
        try:
            password_hash = self.sha256(password)
            self.cursor.execute(
                "SELECT id FROM users WHERE username = %s AND password_hash = %s",
                (username, password_hash)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro na autenticação: {e}")
            return False
    
    def register_user(self, username: str, password: str, 
                      email: str = "", full_name: str = "") -> bool:
        """Registra novo usuário"""
        try:
            # Verificar se usuário já existe
            self.cursor.execute(
                "SELECT id FROM users WHERE username = %s",
                (username,)
            )
            if self.cursor.fetchone():
                return False
            
            password_hash = self.sha256(password)
            self.cursor.execute(
                "INSERT INTO users (username, password_hash, email, full_name, is_online) "
                "VALUES (%s, %s, %s, %s, TRUE)",
                (username, password_hash, email, full_name)
            )
            self.connection.commit()
            
            # Adicionar à sala geral
            self.cursor.execute(
                "INSERT INTO room_members (room_id, username) "
                "SELECT id, %s FROM rooms WHERE name = 'geral'",
                (username,)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro no registro: {e}")
            return False
    
    def user_exists(self, username: str) -> bool:
        """Verifica se usuário existe"""
        try:
            self.cursor.execute(
                "SELECT id FROM users WHERE username = %s",
                (username,)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro ao verificar usuário: {e}")
            return False
    
    def user_exists_by_email(self, email: str) -> bool:
        """Verifica se email existe"""
        try:
            self.cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (email,)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro ao verificar email: {e}")
            return False
    
    def update_user_status(self, username: str, online: bool, 
                           ip: str = "", user_agent: str = ""):
        """Atualiza status do usuário"""
        try:
            sql = "UPDATE users SET is_online = %s, last_seen = CURRENT_TIMESTAMP"
            params = [online]
            if ip:
                sql += ", last_ip = %s"
                params.append(ip)
            if user_agent:
                sql += ", user_agent = %s"
                params.append(user_agent)
            sql += " WHERE username = %s"
            params.append(username)
            
            self.cursor.execute(sql, params)
            self.connection.commit()
        except Error as e:
            logger.error(f"Erro ao atualizar status: {e}")
    
    def save_message(self, from_user: str, to_user: str, room: str, 
                     message: str, file_path: str = "", file_name: str = "",
                     file_size: str = "0", mime_type: str = "text/plain",
                     message_type: str = "text") -> bool:
        """Salva mensagem"""
        try:
            self.cursor.execute(
                "INSERT INTO messages (from_user, to_user, room_name, message, "
                "file_path, file_name, file_size, mime_type, message_type) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (from_user, to_user or None, room or None, message,
                 file_path or None, file_name or None, file_size, mime_type, message_type)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao salvar mensagem: {e}")
            return False
    
    def get_message_history(self, username: str, room: str = "", limit: int = 100):
        """Obtém histórico de mensagens"""
        messages = []
        try:
            if room:
                sql = """
                    SELECT from_user, to_user, room_name, message, timestamp,
                           file_path, file_name
                    FROM messages WHERE room_name = %s
                    ORDER BY timestamp DESC LIMIT %s
                """
                self.cursor.execute(sql, (room, limit))
            else:
                sql = """
                    SELECT from_user, to_user, room_name, message, timestamp,
                           file_path, file_name
                    FROM messages WHERE (to_user IS NULL OR to_user = %s OR from_user = %s)
                    ORDER BY timestamp DESC LIMIT %s
                """
                self.cursor.execute(sql, (username, username, limit))
            
            for row in self.cursor.fetchall():
                messages.append({
                    "from": row["from_user"],
                    "to": row["to_user"] or "",
                    "room": row["room_name"] or "",
                    "message": row["message"],
                    "timestamp": str(row["timestamp"]),
                    "file_path": row["file_path"] or "",
                    "file_name": row["file_name"] or ""
                })
        except Error as e:
            logger.error(f"Erro ao buscar histórico: {e}")
        
        return messages
    
    def get_online_users(self) -> List[str]:
        """Obtém usuários online"""
        try:
            self.cursor.execute("SELECT username FROM users WHERE is_online = TRUE")
            return [row["username"] for row in self.cursor.fetchall()]
        except Error as e:
            logger.error(f"Erro ao buscar usuários online: {e}")
            return []
    
    def create_room(self, name: str, creator: str, is_private: bool = False,
                    password: str = "", description: str = "") -> bool:
        """Cria nova sala"""
        try:
            password_hash = self.sha256(password) if is_private else ""
            self.cursor.execute(
                "INSERT INTO rooms (name, created_by, is_private, password_hash, description) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name, creator, is_private, password_hash, description)
            )
            self.connection.commit()
            self.add_room_member(name, creator, "admin")
            return True
        except Error as e:
            logger.error(f"Erro ao criar sala: {e}")
            return False
    
    def add_room_member(self, room_name: str, username: str, role: str = "member") -> bool:
        """Adiciona membro à sala"""
        try:
            self.cursor.execute(
                "INSERT INTO room_members (room_id, username, role) "
                "SELECT id, %s, %s FROM rooms WHERE name = %s",
                (username, role, room_name)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao adicionar membro: {e}")
            return False
    
    def is_room_member(self, room_name: str, username: str) -> bool:
        """Verifica se é membro da sala"""
        try:
            self.cursor.execute(
                "SELECT 1 FROM room_members rm "
                "JOIN rooms r ON rm.room_id = r.id "
                "WHERE r.name = %s AND rm.username = %s",
                (room_name, username)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro ao verificar membro: {e}")
            return False
    
    def get_user_rooms(self, username: str) -> List[str]:
        """Obtém salas do usuário"""
        try:
            self.cursor.execute(
                "SELECT r.name FROM rooms r "
                "JOIN room_members rm ON r.id = rm.room_id "
                "WHERE rm.username = %s",
                (username,)
            )
            return [row["name"] for row in self.cursor.fetchall()]
        except Error as e:
            logger.error(f"Erro ao buscar salas: {e}")
            return []
    
    def create_recovery_code(self, email: str, code: str) -> bool:
        """Cria código de recuperação"""
        try:
            self.cursor.execute(
                "DELETE FROM recovery_codes WHERE email = %s",
                (email,)
            )
            self.cursor.execute(
                "INSERT INTO recovery_codes (email, code, expires_at) "
                "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 15 MINUTE))",
                (email, code)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao criar código: {e}")
            return False
    
    def verify_recovery_code(self, email: str, code: str) -> bool:
        """Verifica código de recuperação"""
        try:
            self.cursor.execute(
                "SELECT 1 FROM recovery_codes "
                "WHERE email = %s AND code = %s AND expires_at > NOW() AND used = FALSE",
                (email, code)
            )
            if self.cursor.fetchone():
                self.cursor.execute(
                    "UPDATE recovery_codes SET used = TRUE "
                    "WHERE email = %s AND code = %s",
                    (email, code)
                )
                self.connection.commit()
                return True
            return False
        except Error as e:
            logger.error(f"Erro ao verificar código: {e}")
            return False
    
    def update_password(self, email: str, new_password: str) -> bool:
        """Atualiza senha"""
        try:
            password_hash = self.sha256(new_password)
            self.cursor.execute(
                "UPDATE users SET password_hash = %s WHERE email = %s",
                (password_hash, email)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao atualizar senha: {e}")
            return False
    
    def generate_auto_login_token(self, username: str) -> str:
        """Gera token de auto-login"""
        token = self.sha256(username + str(time.time()) + str(random.random()))
        try:
            self.cursor.execute(
                "UPDATE users SET auto_login_token = %s, "
                "token_expires = DATE_ADD(NOW(), INTERVAL 30 DAY) "
                "WHERE username = %s",
                (token, username)
            )
            self.connection.commit()
            return token
        except Error as e:
            logger.error(f"Erro ao gerar token: {e}")
            return ""
    
    def verify_auto_login_token(self, username: str, token: str) -> bool:
        """Verifica token de auto-login"""
        try:
            self.cursor.execute(
                "SELECT 1 FROM users "
                "WHERE username = %s AND auto_login_token = %s AND token_expires > NOW()",
                (username, token)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro ao verificar token: {e}")
            return False
    
    def log_security_event(self, username: str, event_type: str, 
                           ip: str, details: str = ""):
        """Registra evento de segurança"""
        try:
            self.cursor.execute(
                "INSERT INTO security_logs (username, ip, event_type, details) "
                "VALUES (%s, %s, %s, %s)",
                (username or None, ip, event_type, details)
            )
            self.connection.commit()
        except Error as e:
            logger.error(f"Erro ao registrar evento: {e}")
            return False
