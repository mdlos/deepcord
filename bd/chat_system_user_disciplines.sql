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
-- Table structure for table `user_disciplines`
--

DROP TABLE IF EXISTS `user_disciplines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_disciplines` (
  `id` varchar(16) NOT NULL,
  `username` varchar(50) NOT NULL,
  `name` varchar(80) NOT NULL,
  `professor` varchar(80) DEFAULT NULL,
  `color` varchar(7) DEFAULT '#4facfe',
  `schedule` varchar(80) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_disc_user` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_disciplines`
--

LOCK TABLES `user_disciplines` WRITE;
/*!40000 ALTER TABLE `user_disciplines` DISABLE KEYS */;
INSERT INTO `user_disciplines` VALUES ('90da83c6','admin','Engenharia de Software','Gil','#4facfe','Qua/Sex 9:10-11h','2026-10-01 01:45:55'),('b19e1b91','admin','Banco de Dados II','Helio/Maiza','#8b5cf6','Seg/Sex 9:00/11:00','2026-10-12 16:44:07'),('cdf707ee','marcio','Álgebra Linear','Alessandra','#8b5cf6','Qua/Qui 11:00h','2026-10-13 19:39:03');
/*!40000 ALTER TABLE `user_disciplines` ENABLE KEYS */;
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
