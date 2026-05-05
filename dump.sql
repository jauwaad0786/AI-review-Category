-- MySQL dump 10.13  Distrib 8.0.45, for Win64 (x86_64)
--
-- Host: localhost    Database: easemydeal_reviews
-- ------------------------------------------------------
-- Server version	8.0.45

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `tbl_seller_category_rating`
--

DROP TABLE IF EXISTS `tbl_seller_category_rating`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tbl_seller_category_rating` (
  `id` int NOT NULL AUTO_INCREMENT,
  `seller_profile_id` int DEFAULT NULL,
  `category` varchar(150) NOT NULL,
  `avg_star` decimal(3,2) DEFAULT NULL,
  `total_reviews` int DEFAULT '0',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `seller_id` (`seller_profile_id`,`category`),
  UNIQUE KEY `idx_scr_seller_category` (`seller_profile_id`,`category`)
) ENGINE=InnoDB AUTO_INCREMENT=38 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tbl_seller_category_rating`
--

LOCK TABLES `tbl_seller_category_rating` WRITE;
/*!40000 ALTER TABLE `tbl_seller_category_rating` DISABLE KEYS */;
INSERT INTO `tbl_seller_category_rating` VALUES (1,1,'Product Quality',4.57,7,'2026-04-23 15:48:09'),(2,1,'App / Platform UX',4.75,4,'2026-04-23 14:44:44'),(3,1,'Overall Experience',2.50,4,'2026-04-23 14:44:44'),(4,1,'Agent Communication',1.00,2,'2026-04-17 14:12:15'),(5,1,'Delivery & Shipping',4.00,2,'2026-04-17 14:12:31'),(6,1,'Pricing & Value',3.00,2,'2026-04-17 14:12:31'),(7,1,'Customer Support',1.00,2,'2026-04-17 14:12:31'),(8,2,'Overall Experience',2.89,9,'2026-04-20 16:21:27'),(25,3,'App / Platform UX',3.00,5,'2026-04-23 14:37:27'),(26,3,'Transaction Speed',5.00,1,'2026-04-17 15:29:18'),(27,3,'Compensation',3.66,9,'2026-04-20 12:08:34'),(28,3,'Return & Refund',3.00,2,'2026-04-23 14:29:39'),(29,3,'Overall Experience',3.33,3,'2026-04-23 14:51:15'),(30,3,'Customer Support',4.50,2,'2026-04-23 14:29:39'),(31,2,'App / Platform UX',1.00,1,'2026-04-20 15:04:46'),(32,3,'Pricing & Value',1.00,1,'2026-04-23 14:37:27'),(33,3,'Product Quality',5.00,1,'2026-04-23 14:51:15'),(34,1,'Service',3.00,1,'2026-04-23 15:48:09'),(35,1,'__overall__',3.09,11,'2026-04-27 10:29:27'),(36,2,'__overall__',2.40,8,'2026-04-27 10:29:27'),(37,3,'__overall__',3.23,13,'2026-04-27 10:29:27');
/*!40000 ALTER TABLE `tbl_seller_category_rating` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tbl_seller_review`
--

DROP TABLE IF EXISTS `tbl_seller_review`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tbl_seller_review` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `comment` text,
  `rating` tinyint DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `is_processed` tinyint DEFAULT '0',
  `seller_profile_id` varchar(50) DEFAULT NULL,
  `status` tinyint DEFAULT '0',
  `remarks` text,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_reviews_status` (`status`),
  KEY `idx_reviews_status_processed` (`status`,`is_processed`),
  KEY `idx_reviews_seller_status` (`seller_profile_id`,`status`),
  KEY `idx_reviews_created` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=51 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tbl_seller_review`
--

LOCK TABLES `tbl_seller_review` WRITE;
/*!40000 ALTER TABLE `tbl_seller_review` DISABLE KEYS */;
INSERT INTO `tbl_seller_review` VALUES (1,1,'The product quality is amazing and delivery was super fast. Really happy with the service.',4,'2026-04-15 15:18:48',1,'1',1,NULL,'2026-04-17 14:12:15'),(2,1011,'worst service but product is good',3,'2026-04-15 16:59:08',1,'1',1,NULL,'2026-04-17 14:12:15'),(3,3,'worst service and product . just good not wow',2,'2026-04-16 14:09:42',1,'1',1,NULL,'2026-04-17 14:12:15'),(4,1011,'the product quality is good ..communication and service is not good',3,'2026-04-16 14:56:53',1,'1',1,NULL,'2026-04-17 14:12:15'),(5,5,'The product quality is really good and works well, but the service response was very slow and not helpful.',3,'2026-04-16 16:08:58',1,'1',1,NULL,'2026-04-17 14:12:15'),(6,6,'Delivery was super fast and packaging was nice, however the product did not meet expectations and feels average.',3,'2026-04-16 16:09:24',1,'1',1,NULL,'2026-04-17 14:12:31'),(7,7,'The product is decent and usable, but the communication and support team are not responsive at all.',2,'2026-04-16 16:09:51',1,'1',1,NULL,'2026-04-17 14:12:31'),(8,8,'Amazing product quality and smooth experience overall, though there is still some room for improvement in customer service',4,'2026-04-16 16:10:15',1,'1',1,NULL,'2026-04-17 14:12:31'),(9,1011,'good and best',4,'2026-04-16 17:44:38',1,'2',1,NULL,'2026-04-17 14:12:31'),(24,1,'I love this app so much. I am using this app from last 5-6 months and it gives me a great experience.. It is fast, efficient, and easy transaction app. This is one of the best app see in my life. I recommend this app to all for recharge and bill payment. This app is simple and easy to use for recharge and bill payments. Refund policy is also good, refund insant credit for failed transaction.',5,'2026-04-17 15:28:04',1,'3',1,NULL,'2026-04-17 15:29:18'),(25,2,'Best app for paying bills\nAnd mobile recharge It is fast, efficient, and easy transaction app. This is one of the best app see in my life. I recommend this app to all for recharge and bill payment. This app is simple and easy to use for recharge and bill payments Refund policy is also very good',5,'2026-04-17 15:28:25',1,'3',1,NULL,'2026-04-17 15:30:12'),(26,3,'Good application for payment, recharge and bill pay. Easy to use, smooth app functioning, and customer support is also very good. The charges or convience fees are slightly higher. If it is become less then it will surely become one of the best payment platform',5,'2026-04-17 15:28:50',1,'3',1,NULL,'2026-04-17 15:30:11'),(27,4,'I was looking for an easier way to pay my bills. I needed a simple, user-friendly and secure online payment system that could help me with my bill payments as well as offer other services like mobile recharge, shopping vouchers and cashback. Easymydeal is just what I was looking for! The service is very easy to use and has made paying all my bills very convenient.',5,'2026-04-17 15:29:34',1,'3',1,NULL,'2026-04-17 15:31:06'),(28,5,'EaseMyDeal is a versatile recharge and bill payment app offering convenience and efficiency. With its user-friendly interface, it enables hassle-free mobile, DTH, and data card recharges, as well as quick utility bill payments. Secure transactions, attractive discounts, and 24/7 customer support make it an excellent choice for managing financial transactions seamlessly.',5,'2026-04-17 15:29:55',1,'3',1,NULL,'2026-04-17 15:31:59'),(29,6,'Very very very worst app please dont use it.\nI personally suggest it is the worst app in my life i wish i can give it 0 star\n\nAlso if u r doing any bill payment then it got pending and they donot refund the money😠',1,'2026-04-17 15:30:40',1,'3',1,NULL,'2026-04-17 15:31:59'),(30,7,'I paid my Airtel bill form this app, but Airel did not get payment, money was deducted from account,pls be careful',1,'2026-04-17 15:30:59',1,'3',1,NULL,'2026-04-17 15:32:45'),(31,8,'This is one of the wrost recharge or bill payment ap please don\'t use it\nAlways recharge Failed and gateway charge is also not refunded',1,'2026-04-17 15:31:18',1,'3',1,NULL,'2026-04-17 15:32:45'),(32,1011,'nice payment apps',4,'2026-04-20 12:07:04',1,'3',1,NULL,'2026-04-20 12:08:34'),(33,1011,'six two 0 7 nine IV Vii nine 8',2,'2026-04-20 14:06:17',1,'3',1,NULL,'2026-04-20 14:08:08'),(34,786,'good product but slow apps',2,'2026-04-20 15:03:02',1,'2',1,NULL,'2026-04-20 15:04:46'),(35,3,'six nine 2 3 VII IX',2,'2026-04-20 15:22:13',1,'2',1,NULL,'2026-04-20 15:23:21'),(36,1011,'six nine VII please connect 9 8',3,'2026-04-20 15:25:52',1,'2',1,NULL,'2026-04-20 15:27:16'),(37,12,'nine eight seven VII IX 9 2',1,'2026-04-20 15:28:07',1,'2',1,NULL,'2026-04-20 15:29:09'),(38,1011,'nine eight 2 4 five 9',1,'2026-04-20 15:32:21',1,'2',1,NULL,'2026-04-20 15:33:33'),(39,121,'nine 7 6 two three four VII',3,'2026-04-20 15:41:41',1,'2',1,NULL,'2026-04-20 15:42:59'),(40,131,'nine six 6 two three 5 VII 8 9 2',1,'2026-04-20 15:43:26',0,'2',2,NULL,'2026-04-20 15:43:30'),(41,1234,'nine 7 six V VI eight',3,'2026-04-20 16:20:09',1,'2',1,NULL,'2026-04-20 16:21:27'),(42,89,'nice app extremely happy with customer service and easy to use . but refund amount is slow and take lots of days.',3,'2026-04-23 14:21:16',1,'3',1,NULL,'2026-04-23 14:29:39'),(43,101111,'nice app but service is not good . price is good',2,'2026-04-23 14:36:38',1,'3',1,NULL,'2026-04-23 14:37:27'),(44,101123,'nice experince and good UI but take so much time to open',3,'2026-04-23 14:41:56',1,'1',1,NULL,'2026-04-23 14:42:44'),(45,101145,'nice and easy to use app',4,'2026-04-23 14:44:07',1,'1',1,NULL,'2026-04-23 14:44:44'),(46,10112434,'nice product wow',3,'2026-04-23 14:50:26',1,'3',1,NULL,'2026-04-23 14:51:15'),(47,1011,'spam spam spam spam',1,'2026-04-23 15:16:35',0,'1',2,NULL,'2026-04-23 15:17:05'),(48,10111234,'nice prodcut and service is good .',3,'2026-04-23 15:41:15',1,'1',1,NULL,'2026-04-23 15:48:09'),(49,101123,'spam spam spam spam',1,'2026-04-23 15:41:34',0,'1',2,'spam_intent_detected:spam','2026-04-23 15:47:37'),(50,1011345,'spam spam spam',1,'2026-04-23 15:43:55',0,'1',2,'spam_intent_detected:spam','2026-04-23 15:47:37');
/*!40000 ALTER TABLE `tbl_seller_review` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tbl_seller_review_analysis`
--

DROP TABLE IF EXISTS `tbl_seller_review_analysis`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tbl_seller_review_analysis` (
  `id` int NOT NULL AUTO_INCREMENT,
  `review_id` int NOT NULL,
  `category` varchar(150) NOT NULL,
  `category_star` tinyint NOT NULL,
  `processed_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `seller_profile_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ra_review_id` (`review_id`),
  KEY `idx_ra_seller_id` (`seller_profile_id`),
  CONSTRAINT `tbl_seller_review_analysis_ibfk_1` FOREIGN KEY (`review_id`) REFERENCES `tbl_seller_review` (`id`),
  CONSTRAINT `tbl_seller_review_analysis_chk_1` CHECK ((`category_star` between 1 and 5))
) ENGINE=InnoDB AUTO_INCREMENT=151 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tbl_seller_review_analysis`
--

LOCK TABLES `tbl_seller_review_analysis` WRITE;
/*!40000 ALTER TABLE `tbl_seller_review_analysis` DISABLE KEYS */;
INSERT INTO `tbl_seller_review_analysis` VALUES (3,1,'Product Quality',5,'2026-04-15 15:20:11',1),(4,1,'App / Platform UX',5,'2026-04-15 15:20:11',1),(5,2,'Overall Experience',4,'2026-04-15 17:00:53',1),(6,3,'Overall Experience',1,'2026-04-16 14:11:18',1),(7,4,'Product Quality',4,'2026-04-16 14:58:17',1),(8,4,'Agent Communication',1,'2026-04-16 14:58:17',1),(9,5,'Product Quality',4,'2026-04-16 16:10:22',1),(10,6,'Delivery & Shipping',4,'2026-04-16 16:11:15',1),(11,6,'Pricing & Value',3,'2026-04-16 16:11:15',1),(12,7,'Customer Support',1,'2026-04-16 16:11:15',1),(13,8,'Product Quality',5,'2026-04-16 16:12:01',1),(14,9,'Overall Experience',5,'2026-04-16 17:51:14',2),(25,4,'Product Quality',4,'2026-04-17 14:12:16',1),(26,1,'Product Quality',5,'2026-04-17 14:12:16',1),(27,2,'Overall Experience',4,'2026-04-17 14:12:16',1),(28,5,'Product Quality',4,'2026-04-17 14:12:16',1),(29,3,'Overall Experience',1,'2026-04-17 14:12:16',1),(30,1,'App / Platform UX',5,'2026-04-17 14:12:16',1),(31,4,'Agent Communication',1,'2026-04-17 14:12:16',1),(32,9,'Overall Experience',5,'2026-04-17 14:12:31',2),(33,7,'Customer Support',1,'2026-04-17 14:12:31',1),(34,6,'Delivery & Shipping',4,'2026-04-17 14:12:31',1),(35,6,'Pricing & Value',3,'2026-04-17 14:12:31',1),(37,8,'Product Quality',5,'2026-04-17 14:12:32',1),(114,24,'App / Platform UX',5,'2026-04-17 15:29:18',3),(115,24,'Transaction Speed',5,'2026-04-17 15:29:18',3),(116,24,'Compensation',5,'2026-04-17 15:29:18',3),(117,24,'Return & Refund',5,'2026-04-17 15:29:18',3),(118,26,'Compensation',5,'2026-04-17 15:30:12',3),(119,25,'Compensation',5,'2026-04-17 15:30:12',3),(120,25,'App / Platform UX',5,'2026-04-17 15:30:12',3),(121,27,'Compensation',5,'2026-04-17 15:31:06',3),(122,27,'Overall Experience',5,'2026-04-17 15:31:06',3),(123,29,'App / Platform UX',1,'2026-04-17 15:32:00',3),(124,29,'Compensation',1,'2026-04-17 15:32:00',3),(125,28,'Compensation',5,'2026-04-17 15:32:00',3),(126,28,'Customer Support',5,'2026-04-17 15:32:00',3),(127,31,'Compensation',1,'2026-04-17 15:32:45',3),(128,30,'App / Platform UX',1,'2026-04-17 15:32:46',3),(129,30,'Compensation',1,'2026-04-17 15:32:46',3),(130,32,'Compensation',5,'2026-04-20 12:08:35',3),(131,33,'Overall Experience',2,'2026-04-20 14:08:08',3),(132,34,'Overall Experience',3,'2026-04-20 15:04:47',2),(133,34,'App / Platform UX',1,'2026-04-20 15:04:47',2),(134,35,'Overall Experience',2,'2026-04-20 15:23:21',2),(135,36,'Overall Experience',3,'2026-04-20 15:27:16',2),(136,37,'Overall Experience',1,'2026-04-20 15:29:09',2),(137,38,'Overall Experience',1,'2026-04-20 15:33:34',2),(138,39,'Overall Experience',3,'2026-04-20 15:43:00',2),(139,41,'Overall Experience',3,'2026-04-20 16:21:27',2),(140,42,'Customer Support',4,'2026-04-23 14:29:39',3),(141,42,'Return & Refund',1,'2026-04-23 14:29:39',3),(142,43,'App / Platform UX',3,'2026-04-23 14:37:27',3),(143,43,'Pricing & Value',1,'2026-04-23 14:37:27',3),(144,44,'App / Platform UX',4,'2026-04-23 14:42:45',1),(145,45,'App / Platform UX',5,'2026-04-23 14:44:44',1),(146,45,'Overall Experience',4,'2026-04-23 14:44:44',1),(147,46,'Product Quality',5,'2026-04-23 14:51:15',3),(148,46,'Overall Experience',3,'2026-04-23 14:51:15',3),(149,48,'Product Quality',4,'2026-04-23 15:48:09',1),(150,48,'Service',3,'2026-04-23 15:48:09',1);
/*!40000 ALTER TABLE `tbl_seller_review_analysis` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-05-05 16:13:13
