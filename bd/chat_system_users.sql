-- MySQL dump 10.13  Distrib 8.4.11, for Linux (x86_64)
--
-- Host: 10.20.4.148    Database: chat_system
-- ------------------------------------------------------
-- Server version	5.7.44

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Nome de usuÃ¡rio Ãºnico',
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Hash da senha (SHA-256)',
  `email` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Email do usuÃ¡rio',
  `full_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Nome completo',
  `avatar_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'URL do avatar',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Data de criaÃ§Ã£o',
  `last_seen` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Ãšltima atividade',
  `is_online` tinyint(1) DEFAULT '0' COMMENT 'Status online/offline',
  `last_ip` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Ãšltimo IP de acesso',
  `user_agent` text COLLATE utf8mb4_unicode_ci COMMENT 'User-Agent do navegador',
  `auto_login_token` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Token para login automÃ¡tico',
  `token_expires` timestamp NULL DEFAULT NULL COMMENT 'Data de expiraÃ§Ã£o do token',
  `is_admin` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  KEY `idx_username` (`username`),
  KEY `idx_online` (`is_online`),
  KEY `idx_email` (`email`),
  KEY `idx_last_seen` (`last_seen`)
) ENGINE=InnoDB AUTO_INCREMENT=58 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Tabela de usuÃ¡rios do sistema';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'admin','a09453b8c2cabb29d60438e08b1285d4597df40469e9a8c789bb9cd3939b860d','admin@chat.com','Administrador do Sistema',NULL,'2026-07-23 21:48:35','2026-10-28 13:33:16',0,'10.20.4.148',NULL,NULL,NULL,1),(7,'Marcio','a09453b8c2cabb29d60438e08b1285d4597df40469e9a8c789bb9cd3939b860d','mbiologo7@gmail.com','',NULL,'2026-07-28 13:47:44','2026-10-20 13:08:33',0,'192.168.0.123',NULL,NULL,NULL,0),(10,'? IA DeepCord','d2a843562907577bb703df9e9f8cce4028c51d1877796aefdbb6b375838290ba','ai@chat.com','IA DeepCord',NULL,'2026-09-13 05:39:32','2026-09-13 05:39:32',0,NULL,NULL,NULL,NULL,0),(12,'alessandro','8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92','alessandro@gmail.com','',NULL,'2026-09-13 05:49:27','2026-09-13 05:49:27',0,NULL,NULL,NULL,NULL,0),(28,'demo','d3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791','demo@chat.com','Usuário Demo',NULL,'2026-09-30 11:33:09','2026-09-30 11:33:09',0,NULL,NULL,NULL,NULL,0),(46,'? Orquestrador','1e7b7eaf1dd88dd2d1e1cec92538a342056ecd6142ef9022fef84f3f0de3e1fe','orq@chat.com','Orquestrador DeepCord',NULL,'2026-10-08 21:43:20','2026-10-08 21:43:20',0,NULL,NULL,NULL,NULL,0),(57,'admin2','a09453b8c2cabb29d60438e08b1285d4597df40469e9a8c789bb9cd3939b860d','admin2@chat.com','',NULL,'2026-10-09 14:20:36','2026-10-13 20:40:15',0,'192.168.0.125',NULL,NULL,NULL,1);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-11-03 11:25:44
