/**
 * @file database_mysql.cpp
 * @brief Implementação da classe Database com Qt + MySQL
 * 
 * Utiliza Qt SQL para comunicação com MySQL no Docker.
 */

#include "database_mysql.hpp"
#include <QCoreApplication>
#include <QThread>
#include <QDebug>
#include <QJsonDocument>
#include <QFile>
#include <QTextStream>
#include <iostream>
#include <chrono>
#include <thread>

// ============================================
// CONSTRUTOR / DESTRUTOR
// ============================================

Database::Database(const std::string& host, const std::string& port,
                   const std::string& username, const std::string& password,
                   const std::string& database_name)
    : QObject(nullptr), 
      connected(false), 
      host(host), 
      port(port), 
      username(username), 
      password(password), 
      database_name(database_name),
      reconnect_attempts(0) {
    
    // 🔥 IMPORTANTE: Usar um nome de conexão único
    QString connectionName = QString("chat_connection_%1").arg(
        QDateTime::currentMSecsSinceEpoch()
    );
    
    db = QSqlDatabase::addDatabase("QMYSQL", connectionName);
    db.setConnectOptions("MYSQL_OPT_CONNECT_TIMEOUT=5");
    
    // Conectar ao banco
    connectToDatabase();
    
    // Configurar reconexão automática
    startTimer(5000); // Verificar conexão a cada 5 segundos
}

Database::~Database() {
    disconnectFromDatabase();
}

// ============================================
// TIMER EVENT - RECONEXÃO AUTOMÁTICA
// ============================================

void Database::timerEvent(QTimerEvent* event) {
    Q_UNUSED(event);
    
    if (!isConnected() && !host.empty()) {
        std::cout << "[DB] 🔄 Tentando reconectar..." << std::endl;
        connectToDatabase();
    }
}

// ============================================
// CONEXÃO
// ============================================

bool Database::connectToDatabase() {
    QMutexLocker locker(&mutex);
    
    if (db.isOpen()) {
        return true;
    }
    
    db.setHostName(QString::fromStdString(host));
    db.setDatabaseName(QString::fromStdString(database_name));
    db.setUserName(QString::fromStdString(username));
    db.setPassword(QString::fromStdString(password));
    db.setPort(port.empty() ? 3306 : std::stoi(port));
    
    std::cout << "[DB] Conectando ao MySQL: " << host << ":" << port 
              << "/" << database_name << std::endl;
    
    if (db.open()) {
        connected = true;
        reconnect_attempts = 0;
        std::cout << "[DB] ✅ Conectado ao MySQL!" << std::endl;
        
        // 🔥 INICIALIZAR BANCO APÓS CONEXÃO
        initializeDatabase();
        
        return true;
    } else {
        connected = false;
        reconnect_attempts++;
        std::cerr << "[DB] ❌ Falha ao conectar (tentativa " 
                  << reconnect_attempts << "): " 
                  << db.lastError().text().toStdString() << std::endl;
        return false;
    }
}

bool Database::disconnectFromDatabase() {
    QMutexLocker locker(&mutex);
    
    if (db.isOpen()) {
        db.close();
        connected = false;
        std::cout << "[DB] Desconectado do MySQL" << std::endl;
    }
    
    // Remover conexão do pool
    QString connectionName = db.connectionName();
    if (!connectionName.isEmpty()) {
        db = QSqlDatabase();
        QSqlDatabase::removeDatabase(connectionName);
    }
    
    return true;
}

bool Database::ensureConnection() {
    if (!isConnected()) {
        connectToDatabase();
    }
    return isConnected();
}

bool Database::isConnected() const {
    QMutexLocker locker(&mutex);
    return connected && db.isOpen();
}

void Database::handleError(const QSqlError& error) {
    std::cerr << "[DB ERRO] " << error.text().toStdString() << std::endl;
    std::cerr << "  Tipo: " << error.type() << std::endl;
    if (error.number() != -1) {
        std::cerr << "  Código: " << error.number() << std::endl;
    }
    
    // Se for erro de conexão, marcar como desconectado
    if (error.type() == QSqlError::ConnectionError) {
        connected = false;
    }
}

// ============================================
// SHA256 HASH
// ============================================

std::string Database::sha256(const std::string& input) {
    QString hash = sha256(QString::fromStdString(input));
    return hash.toStdString();
}

QString Database::sha256(const QString& input) {
    QByteArray hash = QCryptographicHash::hash(input.toUtf8(), QCryptographicHash::Sha256);
    return QString(hash.toHex());
}

// ============================================
// INICIALIZAÇÃO DO BANCO - CORRIGIDA
// ============================================

bool Database::initializeDatabase() {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não foi possível inicializar: sem conexão" << std::endl;
        return false;
    }
    
    std::cout << "[DB] 🔧 Verificando/ Criando tabelas..." << std::endl;
    
    // 🔥 LISTA DE TABELAS PARA VERIFICAR
    QStringList requiredTables = {"users", "messages", "rooms", "room_members", 
                                  "recovery_codes", "security_logs"};
    
    QStringList existingTables = db.tables();
    
    QSqlQuery query(db);
    
    // Verificar se todas as tabelas existem
    bool needsInit = false;
    for (const QString& table : requiredTables) {
        if (!existingTables.contains(table, Qt::CaseInsensitive)) {
            needsInit = true;
            break;
        }
    }
    
    if (!needsInit) {
        std::cout << "[DB] ✅ Todas as tabelas já existem" << std::endl;
        return true;
    }
    
    std::cout << "[DB] 📦 Criando estrutura do banco..." << std::endl;
    
    // 🔥 USAR TRANSACTION PARA INICIALIZAÇÃO
    if (!db.transaction()) {
        handleError(db.lastError());
        return false;
    }
    
    bool success = true;
    
    // Tabela users
    if (!existingTables.contains("users")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS users ("
            "id INT AUTO_INCREMENT PRIMARY KEY,"
            "username VARCHAR(50) UNIQUE NOT NULL,"
            "password_hash VARCHAR(255) NOT NULL,"
            "email VARCHAR(100),"
            "full_name VARCHAR(100),"
            "avatar_url VARCHAR(255),"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "is_online BOOLEAN DEFAULT FALSE,"
            "last_ip VARCHAR(45),"
            "user_agent TEXT,"
            "auto_login_token VARCHAR(255),"
            "token_expires TIMESTAMP,"
            "INDEX idx_username (username),"
            "INDEX idx_email (email),"
            "INDEX idx_online (is_online)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // Tabela messages
    if (success && !existingTables.contains("messages")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS messages ("
            "id INT AUTO_INCREMENT PRIMARY KEY,"
            "from_user VARCHAR(50) NOT NULL,"
            "to_user VARCHAR(50) NULL,"
            "room_name VARCHAR(50) NULL,"
            "message TEXT NOT NULL,"
            "timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "file_path VARCHAR(255),"
            "file_name VARCHAR(255),"
            "file_size BIGINT DEFAULT 0,"
            "mime_type VARCHAR(100),"
            "message_type ENUM('text','file','image','video','audio','system') DEFAULT 'text',"
            "is_read BOOLEAN DEFAULT FALSE,"
            "INDEX idx_room_timestamp (room_name, timestamp),"
            "INDEX idx_user_timestamp (from_user, timestamp),"
            "INDEX idx_unread (to_user, is_read),"
            "FOREIGN KEY (from_user) REFERENCES users(username) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // Tabela rooms
    if (success && !existingTables.contains("rooms")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS rooms ("
            "id INT AUTO_INCREMENT PRIMARY KEY,"
            "name VARCHAR(50) UNIQUE NOT NULL,"
            "created_by VARCHAR(50) NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "is_private BOOLEAN DEFAULT FALSE,"
            "password_hash VARCHAR(255),"
            "description TEXT,"
            "INDEX idx_name (name),"
            "FOREIGN KEY (created_by) REFERENCES users(username) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // Tabela room_members
    if (success && !existingTables.contains("room_members")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS room_members ("
            "room_id INT NOT NULL,"
            "username VARCHAR(50) NOT NULL,"
            "joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "role ENUM('admin','moderator','member') DEFAULT 'member',"
            "PRIMARY KEY (room_id, username),"
            "INDEX idx_username (username),"
            "FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,"
            "FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // Tabela recovery_codes
    if (success && !existingTables.contains("recovery_codes")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS recovery_codes ("
            "id INT AUTO_INCREMENT PRIMARY KEY,"
            "email VARCHAR(100) NOT NULL,"
            "code VARCHAR(6) NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "expires_at TIMESTAMP NOT NULL,"
            "used BOOLEAN DEFAULT FALSE,"
            "INDEX idx_email_code (email, code)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // Tabela security_logs
    if (success && !existingTables.contains("security_logs")) {
        QString sql = 
            "CREATE TABLE IF NOT EXISTS security_logs ("
            "id INT AUTO_INCREMENT PRIMARY KEY,"
            "username VARCHAR(50) NULL,"
            "ip VARCHAR(45) NOT NULL,"
            "event_type ENUM('login','logout','failed_login','recovery_request','password_change','register') NOT NULL,"
            "details TEXT,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_username_time (username, created_at),"
            "INDEX idx_event (event_type)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci";
        
        if (!query.exec(sql)) {
            handleError(query.lastError());
            success = false;
        }
    }
    
    // 🔥 VERIFICAR E CRIAR USUÁRIO ADMIN
    if (success) {
        QSqlQuery checkAdmin(db);
        checkAdmin.prepare("SELECT COUNT(*) FROM users WHERE username = 'admin'");
        if (checkAdmin.exec() && checkAdmin.next() && checkAdmin.value(0).toInt() == 0) {
            std::cout << "[DB] 👤 Criando usuário admin..." << std::endl;
            
            QString adminPassword = sha256(QString("admin123"));
            QSqlQuery insertAdmin(db);
            insertAdmin.prepare(
                "INSERT INTO users (username, password_hash, email, full_name, is_online) "
                "VALUES ('admin', ?, 'admin@chat.com', 'Administrador', TRUE)"
            );
            insertAdmin.bindValue(0, adminPassword);
            
            if (!insertAdmin.exec()) {
                handleError(insertAdmin.lastError());
                success = false;
            }
        }
    }
    
    // 🔥 VERIFICAR E CRIAR SALA GERAL
    if (success) {
        QSqlQuery checkRoom(db);
        checkRoom.prepare("SELECT COUNT(*) FROM rooms WHERE name = 'geral'");
        if (checkRoom.exec() && checkRoom.next() && checkRoom.value(0).toInt() == 0) {
            std::cout << "[DB] 🏠 Criando sala geral..." << std::endl;
            
            QSqlQuery insertRoom(db);
            insertRoom.prepare(
                "INSERT INTO rooms (name, created_by, description) "
                "VALUES ('geral', 'admin', 'Sala geral de conversas')"
            );
            
            if (!insertRoom.exec()) {
                handleError(insertRoom.lastError());
                success = false;
            } else {
                // Adicionar admin à sala geral
                QSqlQuery addMember(db);
                addMember.prepare(
                    "INSERT INTO room_members (room_id, username, role) "
                    "SELECT id, 'admin', 'admin' FROM rooms WHERE name = 'geral'"
                );
                
                if (!addMember.exec()) {
                    handleError(addMember.lastError());
                    success = false;
                }
            }
        }
    }
    
    // 🔥 COMMIT DA TRANSACTION
    if (success) {
        if (!db.commit()) {
            handleError(db.lastError());
            success = false;
        }
    } else {
        db.rollback();
    }
    
    if (success) {
        std::cout << "[DB] ✅ Banco de dados inicializado com sucesso!" << std::endl;
        std::cout << "[DB] 👤 Admin: admin / admin123" << std::endl;
    } else {
        std::cerr << "[DB] ❌ Falha na inicialização do banco" << std::endl;
    }
    
    return success;
}

// ============================================
// AUTENTICAÇÃO
// ============================================

bool Database::authenticate_user(const std::string& username, const std::string& password) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QString hash = sha256(QString::fromStdString(password));
    
    QSqlQuery query(db);
    query.prepare("SELECT id FROM users WHERE username = ? AND password_hash = ?");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, hash);
    
    if (!query.exec()) {
        handleError(query.lastError());
        return false;
    }
    
    bool authenticated = query.next();
    
    if (authenticated) {
        std::cout << "[DB] ✅ Usuário autenticado: " << username << std::endl;
    } else {
        std::cout << "[DB] ❌ Falha na autenticação: " << username << std::endl;
    }
    
    return authenticated;
}

bool Database::register_user(const std::string& username, const std::string& password,
                             const std::string& email, const std::string& full_name) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    // Verificar se o usuário já existe
    QSqlQuery checkQuery(db);
    checkQuery.prepare("SELECT id FROM users WHERE username = ?");
    checkQuery.bindValue(0, QString::fromStdString(username));
    
    if (!checkQuery.exec()) {
        handleError(checkQuery.lastError());
        return false;
    }
    
    if (checkQuery.next()) {
        std::cout << "[DB] ❌ Usuário já existe: " << username << std::endl;
        return false;
    }
    
    // Inserir novo usuário
    QString hash = sha256(QString::fromStdString(password));
    QSqlQuery query(db);
    query.prepare("INSERT INTO users (username, password_hash, email, full_name, is_online) "
                  "VALUES (?, ?, ?, ?, TRUE)");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, hash);
    query.bindValue(2, QString::fromStdString(email));
    query.bindValue(3, QString::fromStdString(full_name));
    
    if (!query.exec()) {
        handleError(query.lastError());
        return false;
    }
    
    // Adicionar à sala geral
    QSqlQuery roomQuery(db);
    roomQuery.prepare("INSERT INTO room_members (room_id, username) "
                      "SELECT id, ? FROM rooms WHERE name = 'geral'");
    roomQuery.bindValue(0, QString::fromStdString(username));
    
    if (!roomQuery.exec()) {
        handleError(roomQuery.lastError());
        std::cerr << "[DB] ⚠️ Usuário criado mas não adicionado à sala geral" << std::endl;
    }
    
    std::cout << "[DB] ✅ Usuário registrado: " << username << std::endl;
    return true;
}

bool Database::update_user_status(const std::string& username, bool online,
                                  const std::string& ip, const std::string& user_agent) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    QString sql = "UPDATE users SET is_online = ?, last_seen = CURRENT_TIMESTAMP";
    
    if (!ip.empty()) {
        sql += ", last_ip = ?";
    }
    if (!user_agent.empty()) {
        sql += ", user_agent = ?";
    }
    sql += " WHERE username = ?";
    
    query.prepare(sql);
    query.bindValue(0, online ? 1 : 0);
    
    int idx = 1;
    if (!ip.empty()) {
        query.bindValue(idx++, QString::fromStdString(ip));
    }
    if (!user_agent.empty()) {
        query.bindValue(idx++, QString::fromStdString(user_agent));
    }
    query.bindValue(idx, QString::fromStdString(username));
    
    if (!query.exec()) {
        handleError(query.lastError());
        return false;
    }
    
    return true;
}

// ============================================
// MENSAGENS - CORRIGIDO
// ============================================

bool Database::save_message(const std::string& from, const std::string& to,
                            const std::string& room, const std::string& message,
                            const std::string& file_path, const std::string& file_name,
                            const std::string& file_size, const std::string& mime_type,
                            const std::string& message_type) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("INSERT INTO messages (from_user, to_user, room_name, message, "
                  "file_path, file_name, file_size, mime_type, message_type, timestamp) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)");
    query.bindValue(0, QString::fromStdString(from));
    query.bindValue(1, to.empty() ? QVariant() : QString::fromStdString(to));
    query.bindValue(2, room.empty() ? QVariant() : QString::fromStdString(room));
    query.bindValue(3, QString::fromStdString(message));
    query.bindValue(4, file_path.empty() ? QVariant() : QString::fromStdString(file_path));
    query.bindValue(5, file_name.empty() ? QVariant() : QString::fromStdString(file_name));
    query.bindValue(6, QString::fromStdString(file_size));
    query.bindValue(7, QString::fromStdString(mime_type));
    query.bindValue(8, QString::fromStdString(message_type));
    
    if (!query.exec()) {
        handleError(query.lastError());
        return false;
    }
    
    return true;
}

std::vector<std::map<std::string, std::string>> Database::get_message_history(
    const std::string& username, const std::string& room, int limit) {
    
    std::vector<std::map<std::string, std::string>> messages;
    
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return messages;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    QString sql;
    
    if (!room.empty()) {
        sql = "SELECT from_user, to_user, room_name, message, timestamp, "
              "file_path, file_name, message_type, is_read "
              "FROM messages WHERE room_name = ? "
              "ORDER BY timestamp DESC LIMIT ?";
        query.prepare(sql);
        query.bindValue(0, QString::fromStdString(room));
        query.bindValue(1, limit);
    } else {
        sql = "SELECT from_user, to_user, room_name, message, timestamp, "
              "file_path, file_name, message_type, is_read "
              "FROM messages WHERE (to_user IS NULL OR to_user = ? OR from_user = ?) "
              "ORDER BY timestamp DESC LIMIT ?";
        query.prepare(sql);
        query.bindValue(0, QString::fromStdString(username));
        query.bindValue(1, QString::fromStdString(username));
        query.bindValue(2, limit);
    }
    
    if (!query.exec()) {
        handleError(query.lastError());
        return messages;
    }
    
    while (query.next()) {
        std::map<std::string, std::string> msg;
        msg["from"] = query.value("from_user").toString().toStdString();
        msg["to"] = query.value("to_user").isNull() ? "" : query.value("to_user").toString().toStdString();
        msg["room"] = query.value("room_name").isNull() ? "" : query.value("room_name").toString().toStdString();
        msg["message"] = query.value("message").toString().toStdString();
        msg["timestamp"] = query.value("timestamp").toString().toStdString();
        msg["file_path"] = query.value("file_path").isNull() ? "" : query.value("file_path").toString().toStdString();
        msg["file_name"] = query.value("file_name").isNull() ? "" : query.value("file_name").toString().toStdString();
        msg["message_type"] = query.value("message_type").toString().toStdString();
        msg["is_read"] = query.value("is_read").toBool() ? "1" : "0";
        messages.push_back(msg);
    }
    
    return messages;
}

bool Database::mark_messages_as_read(const std::string& username, const std::string& from_user) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("UPDATE messages SET is_read = TRUE "
                  "WHERE to_user = ? AND from_user = ? AND is_read = FALSE");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, QString::fromStdString(from_user));
    
    return query.exec();
}

int Database::get_unread_count(const std::string& username) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return 0;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT COUNT(*) as count FROM messages "
                  "WHERE to_user = ? AND is_read = FALSE");
    query.bindValue(0, QString::fromStdString(username));
    
    if (query.exec() && query.next()) {
        return query.value("count").toInt();
    }
    
    return 0;
}

// ============================================
// SALAS
// ============================================

bool Database::create_room(const std::string& name, const std::string& creator,
                           bool is_private, const std::string& password,
                           const std::string& description) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("INSERT INTO rooms (name, created_by, is_private, password_hash, description) "
                  "VALUES (?, ?, ?, ?, ?)");
    query.bindValue(0, QString::fromStdString(name));
    query.bindValue(1, QString::fromStdString(creator));
    query.bindValue(2, is_private ? 1 : 0);
    query.bindValue(3, is_private ? sha256(QString::fromStdString(password)) : "");
    query.bindValue(4, QString::fromStdString(description));
    
    if (!query.exec()) {
        handleError(query.lastError());
        return false;
    }
    
    add_room_member(name, creator, "admin");
    return true;
}

bool Database::add_room_member(const std::string& room_name, const std::string& username,
                               const std::string& role) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("INSERT INTO room_members (room_id, username, role) "
                  "SELECT id, ?, ? FROM rooms WHERE name = ?");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, QString::fromStdString(role));
    query.bindValue(2, QString::fromStdString(room_name));
    
    return query.exec();
}

bool Database::remove_room_member(const std::string& room_name, const std::string& username) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("DELETE rm FROM room_members rm "
                  "JOIN rooms r ON rm.room_id = r.id "
                  "WHERE r.name = ? AND rm.username = ?");
    query.bindValue(0, QString::fromStdString(room_name));
    query.bindValue(1, QString::fromStdString(username));
    
    return query.exec();
}

bool Database::is_room_member(const std::string& room_name, const std::string& username) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT 1 FROM room_members rm "
                  "JOIN rooms r ON rm.room_id = r.id "
                  "WHERE r.name = ? AND rm.username = ?");
    query.bindValue(0, QString::fromStdString(room_name));
    query.bindValue(1, QString::fromStdString(username));
    
    if (query.exec()) {
        return query.next();
    }
    
    return false;
}

std::vector<std::string> Database::get_user_rooms(const std::string& username) {
    std::vector<std::string> rooms;
    
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return rooms;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT r.name FROM rooms r "
                  "JOIN room_members rm ON r.id = rm.room_id "
                  "WHERE rm.username = ?");
    query.bindValue(0, QString::fromStdString(username));
    
    if (query.exec()) {
        while (query.next()) {
            rooms.push_back(query.value(0).toString().toStdString());
        }
    }
    
    return rooms;
}

std::vector<std::string> Database::get_room_members(const std::string& room_name) {
    std::vector<std::string> members;
    
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return members;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT username FROM room_members rm "
                  "JOIN rooms r ON rm.room_id = r.id "
                  "WHERE r.name = ?");
    query.bindValue(0, QString::fromStdString(room_name));
    
    if (query.exec()) {
        while (query.next()) {
            members.push_back(query.value(0).toString().toStdString());
        }
    }
    
    return members;
}

bool Database::update_room_member_role(const std::string& room_name,
                                      const std::string& username,
                                      const std::string& role) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("UPDATE room_members rm "
                  "JOIN rooms r ON rm.room_id = r.id "
                  "SET rm.role = ? "
                  "WHERE r.name = ? AND rm.username = ?");
    query.bindValue(0, QString::fromStdString(role));
    query.bindValue(1, QString::fromStdString(room_name));
    query.bindValue(2, QString::fromStdString(username));
    
    return query.exec();
}

// ============================================
// USUÁRIOS
// ============================================

std::vector<std::string> Database::get_online_users() {
    std::vector<std::string> users;
    
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return users;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT username FROM users WHERE is_online = TRUE");
    
    if (query.exec()) {
        while (query.next()) {
            users.push_back(query.value(0).toString().toStdString());
        }
    }
    
    return users;
}

bool Database::user_exists(const std::string& username) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT 1 FROM users WHERE username = ?");
    query.bindValue(0, QString::fromStdString(username));
    
    if (query.exec()) {
        return query.next();
    }
    
    return false;
}

bool Database::user_exists_by_email(const std::string& email) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT 1 FROM users WHERE email = ?");
    query.bindValue(0, QString::fromStdString(email));
    
    if (query.exec()) {
        return query.next();
    }
    
    return false;
}

bool Database::update_user_profile(const std::string& username,
                                  const std::string& email,
                                  const std::string& full_name,
                                  const std::string& avatar_url) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QString sql = "UPDATE users SET ";
    QStringList updates;
    
    if (!email.empty()) updates << "email = ?";
    if (!full_name.empty()) updates << "full_name = ?";
    if (!avatar_url.empty()) updates << "avatar_url = ?";
    
    if (updates.isEmpty()) return false;
    
    sql += updates.join(", ");
    sql += " WHERE username = ?";
    
    QSqlQuery query(db);
    query.prepare(sql);
    
    int idx = 0;
    if (!email.empty()) query.bindValue(idx++, QString::fromStdString(email));
    if (!full_name.empty()) query.bindValue(idx++, QString::fromStdString(full_name));
    if (!avatar_url.empty()) query.bindValue(idx++, QString::fromStdString(avatar_url));
    query.bindValue(idx, QString::fromStdString(username));
    
    return query.exec();
}

// ============================================
// RECUPERAÇÃO DE SENHA
// ============================================

bool Database::create_recovery_code(const std::string& email, const std::string& code) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    // Remover códigos antigos
    QSqlQuery deleteQuery(db);
    deleteQuery.prepare("DELETE FROM recovery_codes WHERE email = ?");
    deleteQuery.bindValue(0, QString::fromStdString(email));
    deleteQuery.exec();
    
    // Inserir novo código
    QSqlQuery query(db);
    query.prepare("INSERT INTO recovery_codes (email, code, expires_at) "
                  "VALUES (?, ?, DATE_ADD(NOW(), INTERVAL 15 MINUTE))");
    query.bindValue(0, QString::fromStdString(email));
    query.bindValue(1, QString::fromStdString(code));
    
    return query.exec();
}

bool Database::verify_recovery_code(const std::string& email, const std::string& code) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT 1 FROM recovery_codes "
                  "WHERE email = ? AND code = ? AND expires_at > NOW() "
                  "AND used = FALSE");
    query.bindValue(0, QString::fromStdString(email));
    query.bindValue(1, QString::fromStdString(code));
    
    if (query.exec() && query.next()) {
        // Marcar como usado
        QSqlQuery updateQuery(db);
        updateQuery.prepare("UPDATE recovery_codes SET used = TRUE "
                            "WHERE email = ? AND code = ?");
        updateQuery.bindValue(0, QString::fromStdString(email));
        updateQuery.bindValue(1, QString::fromStdString(code));
        updateQuery.exec();
        return true;
    }
    
    return false;
}

bool Database::update_password(const std::string& email, const std::string& new_password) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QString hash = sha256(QString::fromStdString(new_password));
    QSqlQuery query(db);
    query.prepare("UPDATE users SET password_hash = ? WHERE email = ?");
    query.bindValue(0, hash);
    query.bindValue(1, QString::fromStdString(email));
    
    return query.exec();
}

std::string Database::generate_auto_login_token(const std::string& username) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return "";
    }
    
    QMutexLocker locker(&mutex);
    
    QString token = sha256(QString::fromStdString(username) + 
                          QString::number(QDateTime::currentSecsSinceEpoch()) +
                          QString::number(QRandomGenerator::global()->generate()));
    
    QSqlQuery query(db);
    query.prepare("UPDATE users SET auto_login_token = ?, token_expires = DATE_ADD(NOW(), INTERVAL 30 DAY) "
                  "WHERE username = ?");
    query.bindValue(0, token);
    query.bindValue(1, QString::fromStdString(username));
    
    if (query.exec()) {
        return token.toStdString();
    }
    
    return "";
}

bool Database::verify_auto_login_token(const std::string& username, const std::string& token) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("SELECT 1 FROM users "
                  "WHERE username = ? AND auto_login_token = ? AND token_expires > NOW()");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, QString::fromStdString(token));
    
    if (query.exec()) {
        return query.next();
    }
    
    return false;
}

// ============================================
// LOGS DE SEGURANÇA
// ============================================

void Database::log_security_event(const std::string& username,
                                  const std::string& event_type,
                                  const std::string& ip,
                                  const std::string& details) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    query.prepare("INSERT INTO security_logs (username, ip, event_type, details) "
                  "VALUES (?, ?, ?, ?)");
    query.bindValue(0, QString::fromStdString(username));
    query.bindValue(1, QString::fromStdString(ip));
    query.bindValue(2, QString::fromStdString(event_type));
    query.bindValue(3, QString::fromStdString(details));
    query.exec();
}

// ============================================
// UTILITÁRIOS
// ============================================

bool Database::test_connection() {
    if (!ensureConnection()) {
        return false;
    }
    
    QMutexLocker locker(&mutex);
    
    QSqlQuery query(db);
    return query.exec("SELECT 1");
}

// ============================================
// BACKUP E RECUPERAÇÃO
// ============================================

bool Database::create_backup(const std::string& backup_path) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    std::cout << "[DB] 💾 Criando backup em: " << backup_path << std::endl;
    
    QFile file(QString::fromStdString(backup_path));
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        std::cerr << "[DB] ❌ Não foi possível criar arquivo de backup" << std::endl;
        return false;
    }
    
    QTextStream out(&file);
    
    // Obter todas as tabelas
    QSqlQuery query(db);
    query.exec("SHOW TABLES");
    
    QStringList tables;
    while (query.next()) {
        tables << query.value(0).toString();
    }
    
    // Para cada tabela, exportar dados
    for (const QString& table : tables) {
        out << "-- Tabela: " << table << "\n";
        
        // Obter estrutura da tabela
        QSqlQuery showQuery(db);
        showQuery.exec("SHOW CREATE TABLE " + table);
        if (showQuery.next()) {
            out << showQuery.value(1).toString() << ";\n\n";
        }
        
        // Obter dados
        QSqlQuery dataQuery(db);
        dataQuery.exec("SELECT * FROM " + table);
        
        QSqlRecord record = dataQuery.record();
        int columnCount = record.count();
        
        while (dataQuery.next()) {
            QStringList values;
            for (int i = 0; i < columnCount; ++i) {
                QString value = dataQuery.value(i).toString();
                values << "'" + value.replace("'", "''") + "'";
            }
            out << "INSERT INTO " << table << " VALUES (" << values.join(", ") << ");\n";
        }
        out << "\n";
    }
    
    file.close();
    std::cout << "[DB] ✅ Backup criado com sucesso!" << std::endl;
    return true;
}

bool Database::restore_backup(const std::string& backup_path) {
    if (!ensureConnection()) {
        std::cerr << "[DB] ❌ Não conectado ao banco" << std::endl;
        return false;
    }
    
    std::cout << "[DB] 🔄 Restaurando backup: " << backup_path << std::endl;
    
    QFile file(QString::fromStdString(backup_path));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        std::cerr << "[DB] ❌ Arquivo de backup não encontrado" << std::endl;
        return false;
    }
    
    QTextStream in(&file);
    QString content = in.readAll();
    file.close();
    
    // Executar cada comando SQL separadamente
    QStringList commands = content.split(";");
    
    QSqlQuery query(db);
    for (const QString& cmd : commands) {
        QString trimmed = cmd.trimmed();
        if (!trimmed.isEmpty()) {
            if (!query.exec(trimmed)) {
                handleError(query.lastError());
                std::cerr << "[DB] ⚠️ Falha ao executar: " << trimmed.left(100).toStdString() << std::endl;
            }
        }
    }
    
    std::cout << "[DB] ✅ Backup restaurado com sucesso!" << std::endl;
    return true;
}
