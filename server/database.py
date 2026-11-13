#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file database.py
@brief Classe Database para MySQL — DeepCord
       Inclui: usuários, mensagens, salas (públicas e privadas),
               eventos de agenda, disciplinas e perfis.
"""

import mysql.connector
from mysql.connector import Error
import hashlib
import logging
from typing import Dict, List, Optional
import time
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    """Gerencia conexão e operações no MySQL."""

    def __init__(self, host="127.0.0.1", port=3306, user="usuario",
                 password="senha", database="bancodedados"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self.cursor = None

    # ============================================
    # CONEXÃO
    # ============================================
    def connect(self) -> bool:
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                use_pure=True,
                autocommit=False
            )
            self.cursor = self.connection.cursor(dictionary=True)
            logger.info(f"Conectado ao MySQL: {self.host}:{self.port}/{self.database}")
            self.init_database()
            return True
        except Error as e:
            logger.error(f"Erro ao conectar MySQL: {e}")
            return False

    def disconnect(self):
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection and self.connection.is_connected():
                self.connection.close()
            logger.info("Desconectado do MySQL")
        except Error as e:
            logger.error(f"Erro ao desconectar: {e}")

    def _reconnect_if_needed(self):
        """Reconecta se a conexão cair."""
        try:
            if not self.connection or not self.connection.is_connected():
                self.connect()
        except Exception:
            self.connect()

    # ============================================
    # INICIALIZAÇÃO DAS TABELAS
    # ============================================
    def init_database(self):
        """Cria todas as tabelas necessárias."""
        tables = [
            # --------- users ---------
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
                token_expires TIMESTAMP NULL DEFAULT NULL,
                is_admin BOOLEAN DEFAULT FALSE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- messages ---------
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
                INDEX idx_to_user (to_user)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- rooms ---------
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                created_by VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_private BOOLEAN DEFAULT FALSE,
                password_hash VARCHAR(255),
                description TEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- room_members ---------
            """
            CREATE TABLE IF NOT EXISTS room_members (
                room_id INT NOT NULL,
                username VARCHAR(50) NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role ENUM('admin','moderator','member') DEFAULT 'member',
                PRIMARY KEY (room_id, username),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- recovery_codes ---------
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
            # --------- security_logs ---------
            """
            CREATE TABLE IF NOT EXISTS security_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NULL,
                ip VARCHAR(45) NOT NULL,
                event_type ENUM('login','logout','failed_login','recovery_request','password_change','register') NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- user_events (AGENDA) ---------
            """
            CREATE TABLE IF NOT EXISTS user_events (
                id VARCHAR(16) PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(120) NOT NULL,
                event_date DATE NULL,
                event_time TIME NULL,
                discipline VARCHAR(60) NULL,
                description TEXT,
                reminder INT DEFAULT 0,
                done BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_events_user (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- user_disciplines ---------
            """
            CREATE TABLE IF NOT EXISTS user_disciplines (
                id VARCHAR(16) PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                name VARCHAR(80) NOT NULL,
                professor VARCHAR(80),
                color VARCHAR(7) DEFAULT '#4facfe',
                schedule VARCHAR(80),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_disc_user (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # --------- user_profiles ---------
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                username VARCHAR(50) PRIMARY KEY,
                display_name VARCHAR(60),
                photo_base64 LONGTEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        ]

        for sql in tables:
            try:
                self.cursor.execute(sql)
                self.connection.commit()
            except Error as e:
                logger.error(f"Erro ao criar tabela: {e}")

        # Garantir coluna is_admin em bases antigas
        try:
            self.cursor.execute("SHOW COLUMNS FROM users LIKE 'is_admin'")
            if not self.cursor.fetchone():
                self.cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
                self.connection.commit()
                logger.info("✅ Coluna 'is_admin' adicionada em users")
        except Error:
            pass

        # ============================================
        # DADOS INICIAIS
        # ============================================
        try:
            # Admin
            admin_password = self.sha256("admin123")
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name, is_admin) "
                "VALUES ('admin', %s, 'admin@chat.com', 'Administrador', TRUE)",
                (admin_password,)
            )
            # Se já existia sem is_admin, força TRUE
            self.cursor.execute(
                "UPDATE users SET is_admin = TRUE WHERE username = 'admin'"
            )
            self.connection.commit()

            # Sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO rooms (name, created_by, description) "
                "VALUES ('geral', 'admin', 'Sala geral de conversas')"
            )
            self.connection.commit()

            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, 'admin', 'admin' FROM rooms WHERE name = 'geral'"
            )
            self.connection.commit()

            # Demo
            demo_password = self.sha256("demo123")
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name) "
                "VALUES ('demo', %s, 'demo@chat.com', 'Usuário Demo')",
                (demo_password,)
            )
            self.connection.commit()

            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, 'demo', 'member' FROM rooms WHERE name = 'geral'"
            )
            self.connection.commit()

            # Usuário IA (sem login)
            ai_user = "🤖 IA DeepCord"
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name, is_admin) "
                "VALUES (%s, %s, 'ai@chat.com', 'IA DeepCord', FALSE)",
                (ai_user, self.sha256('no_login_ai'))
            )
            self.connection.commit()

            # IA entra na sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, %s, 'member' FROM rooms WHERE name = 'geral'",
                (ai_user,)
            )
            self.connection.commit()

            logger.info("✅ Tabelas prontas e dados iniciais garantidos")
        except Error as e:
            logger.error(f"Erro ao inserir dados iniciais: {e}")

    # ============================================
    # UTIL
    # ============================================
    def sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    # ============================================
    # AUTENTICAÇÃO / USUÁRIOS
    # ============================================
    def authenticate_user(self, username: str, password: str) -> bool:
        try:
            self._reconnect_if_needed()
            password_hash = self.sha256(password)
            self.cursor.execute(
                "SELECT id FROM users WHERE username = %s AND password_hash = %s",
                (username, password_hash)
            )
            return self.cursor.fetchone() is not None
        except Error as e:
            logger.error(f"Erro na autenticação: {e}")
            return False

    def authenticate_user_ex(self, username: str, password: str):
        """Retorna (sucesso, is_admin)"""
        try:
            self._reconnect_if_needed()
            password_hash = self.sha256(password)
            self.cursor.execute(
                "SELECT is_admin FROM users WHERE username = %s AND password_hash = %s",
                (username, password_hash)
            )
            row = self.cursor.fetchone()
            if row:
                return (True, bool(row['is_admin']))
            return (False, False)
        except Error as e:
            logger.error(f"Erro na autenticação: {e}")
            return (False, False)

    def register_user(self, username: str, password: str,
                      email: str = "", full_name: str = "",
                      is_admin: bool = False) -> bool:
        try:
            self.cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if self.cursor.fetchone():
                return False

            password_hash = self.sha256(password)
            self.cursor.execute(
                "INSERT INTO users (username, password_hash, email, full_name, is_online, is_admin) "
                "VALUES (%s, %s, %s, %s, FALSE, %s)",
                (username, password_hash, email, full_name, is_admin)
            )
            self.connection.commit()

            # Adicionar à sala geral
            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username) "
                "SELECT id, %s FROM rooms WHERE name = 'geral'",
                (username,)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro no registro: {e}")
            return False

    def ensure_user_exists(self, username: str, email: str = "",
                           full_name: str = "", is_admin: bool = False) -> bool:
        try:
            self.cursor.execute(
                "INSERT IGNORE INTO users (username, password_hash, email, full_name, is_admin) "
                "VALUES (%s, %s, %s, %s, %s)",
                (username, self.sha256('no_login_' + username), email, full_name, is_admin)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao garantir usuário: {e}")
            return False

    def user_exists(self, username: str) -> bool:
        try:
            self._reconnect_if_needed()
            self.cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            return self.cursor.fetchone() is not None
        except Error:
            return False

    def user_exists_by_email(self, email: str) -> bool:
        try:
            self.cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            return self.cursor.fetchone() is not None
        except Error:
            return False

    def is_admin(self, username: str) -> bool:
        try:
            self._reconnect_if_needed()
            self.cursor.execute("SELECT is_admin FROM users WHERE username = %s", (username,))
            row = self.cursor.fetchone()
            return bool(row and row['is_admin'])
        except Error:
            return False

    def update_user_status(self, username: str, online: bool,
                           ip: str = "", user_agent: str = ""):
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

    def get_all_users(self, exclude: List[str] = None) -> List[Dict]:
        try:
            sql = ("SELECT username, email, full_name, is_online, is_admin, created_at "
                   "FROM users")
            params = []
            if exclude:
                placeholders = ",".join(["%s"] * len(exclude))
                sql += f" WHERE username NOT IN ({placeholders})"
                params.extend(exclude)
            sql += " ORDER BY created_at ASC"
            self.cursor.execute(sql, params)
            result = []
            for row in self.cursor.fetchall():
                result.append({
                    'username': row['username'],
                    'email': row['email'] or '',
                    'full_name': row['full_name'] or '',
                    'is_online': bool(row['is_online']),
                    'is_admin': bool(row['is_admin']),
                    'created_at': str(row['created_at'])
                })
            return result
        except Error as e:
            logger.error(f"Erro ao buscar usuários: {e}")
            return []

    def delete_user(self, username: str) -> bool:
        try:
            # Limpa dados relacionados (caso não haja FK em cascade)
            self.cursor.execute("DELETE FROM user_events WHERE username = %s", (username,))
            self.cursor.execute("DELETE FROM user_disciplines WHERE username = %s", (username,))
            self.cursor.execute("DELETE FROM user_profiles WHERE username = %s", (username,))
            self.cursor.execute("DELETE FROM room_members WHERE username = %s", (username,))
            self.cursor.execute("DELETE FROM messages WHERE from_user = %s", (username,))
            self.cursor.execute("DELETE FROM users WHERE username = %s", (username,))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error as e:
            logger.error(f"Erro ao deletar usuário: {e}")
            return False

    def update_password_by_username(self, username: str, new_password: str) -> bool:
        try:
            password_hash = self.sha256(new_password)
            self.cursor.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (password_hash, username)
            )
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error as e:
            logger.error(f"Erro ao atualizar senha: {e}")
            return False

    def update_password(self, email: str, new_password: str) -> bool:
        try:
            password_hash = self.sha256(new_password)
            self.cursor.execute(
                "UPDATE users SET password_hash = %s WHERE email = %s",
                (password_hash, email)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro: {e}")
            return False

    def create_recovery_code(self, email: str, code: str) -> bool:
        try:
            self.cursor.execute("DELETE FROM recovery_codes WHERE email = %s", (email,))
            self.cursor.execute(
                "INSERT INTO recovery_codes (email, code, expires_at) "
                "VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 15 MINUTE))",
                (email, code)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro: {e}")
            return False

    def verify_recovery_code(self, email: str, code: str) -> bool:
        try:
            self.cursor.execute(
                "SELECT 1 FROM recovery_codes "
                "WHERE email = %s AND code = %s AND expires_at > NOW() AND used = FALSE",
                (email, code)
            )
            if self.cursor.fetchone():
                self.cursor.execute(
                    "UPDATE recovery_codes SET used = TRUE WHERE email = %s AND code = %s",
                    (email, code)
                )
                self.connection.commit()
                return True
            return False
        except Error:
            return False

    # ============================================
    # PERFIS (nome de exibição + foto)
    # ============================================
    def update_profile(self, username: str, display_name: str = None,
                       photo_base64: str = None) -> bool:
        try:
            self.cursor.execute(
                "INSERT INTO user_profiles (username, display_name, photo_base64) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "display_name = COALESCE(VALUES(display_name), display_name), "
                "photo_base64 = COALESCE(VALUES(photo_base64), photo_base64)",
                (username, display_name, photo_base64)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao atualizar perfil: {e}")
            return False

    def get_profile(self, username: str) -> Dict:
        try:
            self.cursor.execute(
                "SELECT display_name, photo_base64 FROM user_profiles WHERE username = %s",
                (username,)
            )
            row = self.cursor.fetchone()
            if row:
                return {
                    'display_name': row['display_name'] or username,
                    'photo_base64': row['photo_base64'] or ''
                }
            return {'display_name': username, 'photo_base64': ''}
        except Error:
            return {'display_name': username, 'photo_base64': ''}

    def get_all_display_names(self) -> Dict[str, str]:
        try:
            self.cursor.execute("SELECT username, display_name FROM user_profiles")
            return {r['username']: r['display_name']
                    for r in self.cursor.fetchall() if r['display_name']}
        except Error:
            return {}

    # ============================================
    # SALAS
    # ============================================
    def create_room(self, name: str, creator: str, is_private: bool = False,
                    password: str = "", description: str = "") -> bool:
        try:
            password_hash = self.sha256(password) if is_private and password else None
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

    def add_room_member(self, room_name: str, username: str,
                        role: str = "member") -> bool:
        try:
            self.cursor.execute(
                "INSERT IGNORE INTO room_members (room_id, username, role) "
                "SELECT id, %s, %s FROM rooms WHERE name = %s",
                (username, role, room_name)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao adicionar membro: {e}")
            return False

    def remove_room_member(self, room_name: str, username: str) -> bool:
        try:
            self.cursor.execute(
                "DELETE rm FROM room_members rm "
                "JOIN rooms r ON rm.room_id = r.id "
                "WHERE r.name = %s AND rm.username = %s",
                (room_name, username)
            )
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error as e:
            logger.error(f"Erro ao remover membro: {e}")
            return False

    def is_room_member(self, room_name: str, username: str) -> bool:
        try:
            self._reconnect_if_needed()
            self.cursor.execute(
                "SELECT 1 FROM room_members rm "
                "JOIN rooms r ON rm.room_id = r.id "
                "WHERE r.name = %s AND rm.username = %s",
                (room_name, username)
            )
            return self.cursor.fetchone() is not None
        except Error:
            return False

    def get_room_members(self, room_name: str) -> List[str]:
        try:
            self.cursor.execute(
                "SELECT rm.username FROM room_members rm "
                "JOIN rooms r ON rm.room_id = r.id "
                "WHERE r.name = %s",
                (room_name,)
            )
            return [row['username'] for row in self.cursor.fetchall()]
        except Error:
            return []

    def get_room_owner(self, room_name: str) -> str:
        try:
            self.cursor.execute("SELECT created_by FROM rooms WHERE name = %s", (room_name,))
            row = self.cursor.fetchone()
            return row['created_by'] if row else ''
        except Error:
            return ''

    def get_room_details(self, room_name: str) -> Optional[Dict]:
        try:
            self._reconnect_if_needed()
            self.cursor.execute(
                "SELECT name, created_by, created_at, is_private, password_hash, description "
                "FROM rooms WHERE name = %s",
                (room_name,)
            )
            row = self.cursor.fetchone()
            if not row:
                return None
            members = self.get_room_members(room_name)
            return {
                'name': row['name'],
                'owner': row['created_by'],
                'created_at': str(row['created_at']),
                'is_private': bool(row['is_private']),
                'password_hash': row['password_hash'],
                'description': row['description'] or '',
                'members': members,
                'member_count': len(members)
            }
        except Error as e:
            logger.error(f"Erro ao buscar sala: {e}")
            return None

    def get_all_rooms(self) -> List[Dict]:
        try:
            self.cursor.execute(
                "SELECT r.name, r.created_by, r.created_at, r.is_private, "
                "(SELECT COUNT(*) FROM room_members WHERE room_id = r.id) AS member_count "
                "FROM rooms r ORDER BY r.created_at ASC"
            )
            result = []
            for row in self.cursor.fetchall():
                result.append({
                    'name': row['name'],
                    'owner': row['created_by'],
                    'created_at': str(row['created_at']),
                    'is_private': bool(row['is_private']),
                    'member_count': int(row['member_count'] or 0)
                })
            return result
        except Error as e:
            logger.error(f"Erro: {e}")
            return []

    def delete_room(self, room_name: str) -> bool:
        try:
            self.cursor.execute("DELETE FROM rooms WHERE name = %s", (room_name,))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error as e:
            logger.error(f"Erro ao deletar sala: {e}")
            return False

    def verify_room_password(self, room_name: str, password: str) -> bool:
        try:
            self.cursor.execute(
                "SELECT password_hash FROM rooms WHERE name = %s AND is_private = TRUE",
                (room_name,)
            )
            row = self.cursor.fetchone()
            if not row or not row['password_hash']:
                return False
            return row['password_hash'] == self.sha256(password)
        except Error:
            return False

    def get_user_rooms(self, username: str) -> List[str]:
        try:
            self.cursor.execute(
                "SELECT r.name FROM rooms r "
                "JOIN room_members rm ON r.id = rm.room_id "
                "WHERE rm.username = %s",
                (username,)
            )
            return [row['name'] for row in self.cursor.fetchall()]
        except Error:
            return []

    # ============================================
    # MENSAGENS
    # ============================================
    def save_message(self, from_user: str, to_user: str, room: str,
                     message: str, file_path: str = "", file_name: str = "",
                     file_size: int = 0, mime_type: str = "text/plain",
                     message_type: str = "text") -> Optional[int]:
        try:
            self.cursor.execute(
                "INSERT INTO messages (from_user, to_user, room_name, message, "
                "file_path, file_name, file_size, mime_type, message_type) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (from_user, to_user or None, room or None, message,
                 file_path or None, file_name or None,
                 int(file_size) if file_size else 0,
                 mime_type, message_type)
            )
            self.connection.commit()
            return self.cursor.lastrowid
        except Error as e:
            logger.error(f"Erro ao salvar mensagem: {e}")
            return None

    def get_room_messages(self, room_name: str, limit: int = 100) -> List[Dict]:
        try:
            self.cursor.execute(
                "SELECT id, from_user, message, timestamp, file_path, file_name, "
                "file_size, message_type "
                "FROM messages WHERE room_name = %s "
                "ORDER BY timestamp ASC LIMIT %s",
                (room_name, limit)
            )
            messages = []
            for row in self.cursor.fetchall():
                mtype = row['message_type'] or 'text'
                msg = {
                    'id': str(row['id']),
                    'type': 'file' if mtype in ('file', 'image', 'video', 'audio') else 'message',
                    'from': row['from_user'],
                    'content': row['message'] or '',
                    'timestamp': row['timestamp'].strftime('%H:%M:%S') if row['timestamp'] else '',
                    'room': room_name
                }
                if mtype in ('file', 'image', 'video', 'audio'):
                    msg['file_path'] = row['file_path'] or ''
                    msg['file_name'] = row['file_name'] or ''
                    msg['file_size'] = int(row['file_size'] or 0)
                messages.append(msg)
            return messages
        except Error as e:
            logger.error(f"Erro ao buscar mensagens: {e}")
            return []

    def get_message_by_id(self, msg_id: int) -> Optional[Dict]:
        try:
            self.cursor.execute(
                "SELECT id, from_user, room_name, file_path, file_name "
                "FROM messages WHERE id = %s",
                (msg_id,)
            )
            return self.cursor.fetchone()
        except Error:
            return None

    def delete_message_by_id(self, msg_id: int) -> bool:
        try:
            self.cursor.execute("DELETE FROM messages WHERE id = %s", (msg_id,))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error as e:
            logger.error(f"Erro ao deletar mensagem: {e}")
            return False

    def clear_room_messages(self, room_name: str, hours: int = 0) -> int:
        try:
            if hours > 0:
                self.cursor.execute(
                    "DELETE FROM messages WHERE room_name = %s "
                    "AND timestamp < DATE_SUB(NOW(), INTERVAL %s HOUR)",
                    (room_name, hours)
                )
            else:
                self.cursor.execute(
                    "DELETE FROM messages WHERE room_name = %s", (room_name,)
                )
            self.connection.commit()
            return self.cursor.rowcount
        except Error as e:
            logger.error(f"Erro: {e}")
            return 0

    def get_message_history(self, username: str, room: str = "",
                            limit: int = 100):
        return self.get_room_messages(room, limit) if room else []

    def get_online_users(self) -> List[str]:
        try:
            self.cursor.execute("SELECT username FROM users WHERE is_online = TRUE")
            return [row['username'] for row in self.cursor.fetchall()]
        except Error:
            return []

    # ============================================
    # AGENDA (eventos)
    # ============================================
    def add_event(self, username: str, event_id: str, title: str,
                  date: str, time: str, discipline: str,
                  description: str, reminder: int) -> bool:
        try:
            self.cursor.execute(
                "INSERT INTO user_events (id, username, title, event_date, event_time, "
                "discipline, description, reminder) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (event_id, username, title,
                 date or None, time or None,
                 discipline or None, description or None, int(reminder or 0))
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao adicionar evento: {e}")
            return False

    def get_events(self, username: str) -> List[Dict]:
        try:
            self.cursor.execute(
                "SELECT id, title, event_date, event_time, discipline, "
                "description, reminder, done, created_at "
                "FROM user_events WHERE username = %s "
                "ORDER BY event_date ASC, event_time ASC",
                (username,)
            )
            events = []
            for row in self.cursor.fetchall():
                events.append({
                    'id': row['id'],
                    'title': row['title'],
                    'date': row['event_date'].strftime('%Y-%m-%d') if row['event_date'] else '',
                    'time': str(row['event_time'])[:5] if row['event_time'] else '',
                    'discipline': row['discipline'] or '',
                    'description': row['description'] or '',
                    'reminder': int(row['reminder'] or 0),
                    'done': bool(row['done']),
                    'created_at': str(row['created_at'])
                })
            return events
        except Error as e:
            logger.error(f"Erro ao buscar eventos: {e}")
            return []

    def delete_event(self, username: str, event_id: str) -> bool:
        try:
            self.cursor.execute(
                "DELETE FROM user_events WHERE id = %s AND username = %s",
                (event_id, username)
            )
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error:
            return False

    def toggle_event(self, username: str, event_id: str) -> bool:
        try:
            self.cursor.execute(
                "UPDATE user_events SET done = NOT done "
                "WHERE id = %s AND username = %s",
                (event_id, username)
            )
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error:
            return False

    # ============================================
    # DISCIPLINAS
    # ============================================
    def add_discipline(self, username: str, disc_id: str, name: str,
                       professor: str, color: str, schedule: str) -> bool:
        try:
            self.cursor.execute(
                "INSERT INTO user_disciplines "
                "(id, username, name, professor, color, schedule) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (disc_id, username, name, professor or None,
                 color or '#4facfe', schedule or None)
            )
            self.connection.commit()
            return True
        except Error as e:
            logger.error(f"Erro ao adicionar disciplina: {e}")
            return False

    def get_disciplines(self, username: str) -> List[Dict]:
        try:
            self.cursor.execute(
                "SELECT id, name, professor, color, schedule, created_at "
                "FROM user_disciplines WHERE username = %s ORDER BY name ASC",
                (username,)
            )
            return [{
                'id': r['id'],
                'name': r['name'],
                'professor': r['professor'] or '',
                'color': r['color'] or '#4facfe',
                'schedule': r['schedule'] or '',
                'created_at': str(r['created_at'])
            } for r in self.cursor.fetchall()]
        except Error as e:
            logger.error(f"Erro: {e}")
            return []

    def delete_discipline(self, username: str, disc_id: str) -> bool:
        try:
            self.cursor.execute(
                "DELETE FROM user_disciplines WHERE id = %s AND username = %s",
                (disc_id, username)
            )
            self.connection.commit()
            return self.cursor.rowcount > 0
        except Error:
            return False

    # ============================================
    # LOGS / TOKENS
    # ============================================
    def log_security_event(self, username: str, event_type: str,
                           ip: str, details: str = ""):
        try:
            self.cursor.execute(
                "INSERT INTO security_logs (username, ip, event_type, details) "
                "VALUES (%s, %s, %s, %s)",
                (username or None, ip, event_type, details)
            )
            self.connection.commit()
        except Error as e:
            logger.error(f"Erro ao registrar evento: {e}")

    def generate_auto_login_token(self, username: str) -> str:
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
        try:
            self.cursor.execute(
                "SELECT 1 FROM users "
                "WHERE username = %s AND auto_login_token = %s "
                "AND token_expires > NOW()",
                (username, token)
            )
            return self.cursor.fetchone() is not None
        except Error:
            return False


# ============================================
# TESTE RÁPIDO
# ============================================
if __name__ == '__main__':
    db = Database()
    if db.connect():
        print("\n✅ CONECTADO COM SUCESSO!\n")
        print("Usuários:")
        for u in db.get_all_users():
            print(f"  - {u['username']} (admin={u['is_admin']})")
        print("\nSalas:")
        for r in db.get_all_rooms():
            print(f"  - {r['name']} (owner={r['owner']})")
        db.disconnect()
    else:
        print("\n❌ FALHA NA CONEXÃO\n")
