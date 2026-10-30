-- Separate database for the pytest suite, so tests never write into dev data.
-- Runs only when the MySQL volume is first created.
CREATE DATABASE IF NOT EXISTS xuanwu_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL ON xuanwu_test.* TO 'rv'@'%';
