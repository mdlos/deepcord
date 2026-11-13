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
-- Table structure for table `room_members`
--

DROP TABLE IF EXISTS `room_members`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `room_members` (
  `room_id` int(11) NOT NULL COMMENT 'ID da sala',
  `username` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Nome do usuÃ¡rio',
  `joined_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Data de entrada',
  `role` enum('admin','moderator','member') COLLATE utf8mb4_unicode_ci DEFAULT 'member' COMMENT 'FunÃ§Ã£o na sala',
  `last_read` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Ãšltima leitura',
  PRIMARY KEY (`room_id`,`username`),
  KEY `idx_username` (`username`),
  KEY `idx_room` (`room_id`),
  CONSTRAINT `room_members_ibfk_1` FOREIGN KEY (`room_id`) REFERENCES `rooms` (`id`) ON DELETE CASCADE,
  CONSTRAINT `room_members_ibfk_2` FOREIGN KEY (`username`) REFERENCES `users` (`username`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Membros das salas';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `room_members`
--

LOCK TABLES `room_members` WRITE;
/*!40000 ALTER TABLE `room_members` DISABLE KEYS */;
INSERT INTO `room_members` VALUES (7,'admin','2026-10-13 21:26:18','admin','2026-10-13 21:26:18'),(7,'demo','2026-10-14 13:33:24','member','2026-10-14 13:33:24'),(7,'marcio','2026-10-13 21:27:18','member','2026-10-13 21:27:18'),(7,'? IA DeepCord','2026-10-14 13:33:24','member','2026-10-14 13:33:24');
/*!40000 ALTER TABLE `room_members` ENABLE KEYS */;
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
