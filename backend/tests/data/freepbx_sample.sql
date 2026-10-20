-- MySQL dump 10.19  Distrib 10.3.39-MariaDB, for Linux (x86_64)
-- Host: localhost    Database: asterisk (example values, not a real site)
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
  `extension` varchar(20) NOT NULL DEFAULT '',
  `password` varchar(20) DEFAULT NULL,
  `name` varchar(50) DEFAULT NULL,
  `voicemail` varchar(50) DEFAULT NULL,
  `ringtimer` int(3) DEFAULT NULL,
  `noanswer` varchar(100) DEFAULT NULL,
  `recording` varchar(50) DEFAULT NULL,
  `outboundcid` varchar(50) DEFAULT NULL,
  `sipname` varchar(50) DEFAULT NULL,
  `mohclass` varchar(80) DEFAULT 'default',
  PRIMARY KEY (`extension`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
INSERT INTO `users` VALUES ('1101','','Front Office','default',0,'','','\"Example School\" <5735550100>','','default'),('1102','','Nurse O\'Brien','novm',0,'','','','','default'),('abc','','Bad','novm',0,'','','','','default');
DROP TABLE IF EXISTS `devices`;
CREATE TABLE `devices` (
  `id` varchar(20) NOT NULL DEFAULT '',
  `tech` varchar(10) NOT NULL DEFAULT '',
  `dial` varchar(255) NOT NULL DEFAULT '',
  `devicetype` varchar(5) NOT NULL DEFAULT '',
  `user` varchar(50) DEFAULT NULL,
  `description` varchar(50) DEFAULT NULL,
  `emergency_cid` varchar(100) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
INSERT INTO `devices` VALUES ('1101','pjsip','PJSIP/1101','fixed','1101','Front Office','5735550199'),('1102','iax2','IAX2/1102','fixed','1102','Nurse','');
CREATE TABLE `sip` (
  `id` varchar(20) NOT NULL DEFAULT '-1',
  `keyword` varchar(30) NOT NULL DEFAULT '',
  `data` varchar(255) NOT NULL,
  `flags` int(1) NOT NULL DEFAULT 0
);
INSERT INTO `sip` VALUES ('1101','secret','s3cr3t-never-copied',0),('1101','callerid','Front Desk <1101>',0);
CREATE TABLE `ringgroups` (
  `grpnum` varchar(20) NOT NULL,
  `strategy` varchar(50) NOT NULL,
  `grptime` smallint(6) NOT NULL,
  `grppre` varchar(100) DEFAULT NULL,
  `grplist` varchar(255) NOT NULL,
  `annmsg_id` int(11) DEFAULT NULL,
  `postdest` varchar(255) DEFAULT NULL,
  `description` varchar(35) NOT NULL
);
INSERT INTO `ringgroups` VALUES ('6600','hunt','25','OFC:','1101-1102-5735550123#',NULL,'ext-local,vmu1101,1','Office'),('6601','ringall','20',NULL,'1101',NULL,'timeconditions,3,1','After hours');
CREATE TABLE `incoming` (
  `cidnum` varchar(20) DEFAULT NULL,
  `extension` varchar(50) NOT NULL,
  `destination` varchar(50) DEFAULT NULL,
  `description` varchar(80) DEFAULT NULL
);
INSERT INTO `incoming` VALUES ('','5735550100','ext-group,6600,1','Main line'),('','5735550101','ivr-2,s,1','Attendant'),('','','from-did-direct,1101,1','Catch all'),('5551234','5735550102','app-blackhole,hangup,1','Blocked');
CREATE TABLE `ivr_details` (`id` int(11) NOT NULL, `name` varchar(50) DEFAULT NULL);
INSERT INTO `ivr_details` VALUES (2,'Main menu');
CREATE TABLE `queues_config` (
  `extension` varchar(20) NOT NULL DEFAULT '',
  `descr` varchar(35) NOT NULL DEFAULT '',
  `grppre` varchar(100) NOT NULL DEFAULT '',
  `maxwait` varchar(8) NOT NULL DEFAULT '',
  `dest` varchar(50) NOT NULL DEFAULT ''
);
INSERT INTO `queues_config` VALUES ('7700','Attendance','','600','ext-local,vmu1101,1');
CREATE TABLE `queues_details` (
  `id` varchar(45) NOT NULL DEFAULT '-1',
  `keyword` varchar(30) NOT NULL DEFAULT '',
  `data` varchar(150) NOT NULL DEFAULT '',
  `flags` int(1) NOT NULL DEFAULT 0
);
INSERT INTO `queues_details` VALUES ('7700','strategy','rrordered',0),('7700','timeout','20',0),('7700','member','Local/1101@from-queue/n,0',1),('7700','member','Local/1102@from-queue/n,0',2),('7700','joinempty','yes',0);
