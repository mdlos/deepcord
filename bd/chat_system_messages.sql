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
-- Table structure for table `messages`
--

DROP TABLE IF EXISTS `messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `messages` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `from_user` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Remetente',
  `to_user` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'DestinatÃ¡rio (NULL para geral)',
  `room_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Sala (NULL para geral)',
  `message` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'ConteÃºdo da mensagem',
  `timestamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Data/hora da mensagem',
  `file_path` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Caminho do arquivo',
  `file_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Nome do arquivo',
  `file_size` bigint(20) DEFAULT '0' COMMENT 'Tamanho do arquivo em bytes',
  `mime_type` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Tipo MIME do arquivo',
  `message_type` enum('text','file','image','video','audio','location') COLLATE utf8mb4_unicode_ci DEFAULT 'text' COMMENT 'Tipo da mensagem',
  `is_read` tinyint(1) DEFAULT '0' COMMENT 'Mensagem lida',
  `is_delivered` tinyint(1) DEFAULT '0' COMMENT 'Mensagem entregue',
  PRIMARY KEY (`id`),
  KEY `idx_from_user` (`from_user`),
  KEY `idx_to_user` (`to_user`),
  KEY `idx_room` (`room_name`),
  KEY `idx_timestamp` (`timestamp`),
  KEY `idx_to_user_read` (`to_user`,`is_read`),
  CONSTRAINT `messages_ibfk_1` FOREIGN KEY (`from_user`) REFERENCES `users` (`username`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=37 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Tabela de mensagens do chat';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `messages`
--

LOCK TABLES `messages` WRITE;
/*!40000 ALTER TABLE `messages` DISABLE KEYS */;
INSERT INTO `messages` VALUES (2,'admin',NULL,'Biologia','oi','2026-09-13 06:02:58',NULL,NULL,0,'text/plain','text',0,0),(18,'admin','marcos',NULL,'oi','2026-10-01 02:01:46',NULL,NULL,0,'text/plain','text',0,0),(26,'? Orquestrador',NULL,'Engenharia de Software','❌ O orquestrador não conseguiu decidir uma ação. Tente reformular a pergunta.','2026-10-12 19:14:21',NULL,NULL,0,'text/plain','text',0,0),(27,'? Orquestrador',NULL,'Engenharia de Software','','2026-10-12 19:29:44',NULL,NULL,0,'text/plain','text',0,0),(28,'? Orquestrador',NULL,'Engenharia de Software','','2026-10-12 19:53:09',NULL,NULL,0,'text/plain','text',0,0),(29,'? Orquestrador',NULL,'Engenharia de Software','❌ Não foi possível analisar a imagem. Rode: ollama pull qwen3-vl:2b','2026-10-13 18:04:05',NULL,NULL,0,'text/plain','text',0,0),(30,'? Orquestrador',NULL,'Engenharia de Software','❌ Não foi possível analisar a imagem. Rode: ollama pull qwen3-vl:2b','2026-10-13 18:08:03',NULL,NULL,0,'text/plain','text',0,0),(31,'marcio','admin2',NULL,'Oi','2026-10-13 20:34:54',NULL,NULL,0,'text/plain','text',0,0),(32,'marcio','admin2',NULL,'Oi','2026-10-13 20:34:54',NULL,NULL,0,'text/plain','text',0,0),(33,'marcio','admin2',NULL,'Como vai?','2026-10-13 20:35:32',NULL,NULL,0,'text/plain','text',0,0),(34,'marcio','admin2',NULL,'Como vai?','2026-10-13 20:35:32',NULL,NULL,0,'text/plain','text',0,0),(35,'marcio','admin2',NULL,'Bem','2026-10-13 20:35:42',NULL,NULL,0,'text/plain','text',0,0),(36,'marcio','admin2',NULL,'Bem','2026-10-13 20:35:42',NULL,NULL,0,'text/plain','text',0,0);
/*!40000 ALTER TABLE `messages` ENABLE KEYS */;
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
