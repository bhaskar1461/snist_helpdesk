-- ==============================================================================
-- SNIST Helpdesk — MySQL Setup Script for Metabase Integration
-- ==============================================================================
-- Run this script in MySQL (as root or admin user) to grant necessary 
-- permissions for Metabase to query the `seg_demo` helpdesk database.
-- ==============================================================================

-- 1. Ensure seg_demo database exists and uses utf8mb4
CREATE DATABASE IF NOT EXISTS `seg_demo` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 2. Create dedicated Metabase internal application database (optional for production)
CREATE DATABASE IF NOT EXISTS `metabase_db` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 3. Create metabase_user DB user (if not already existing)
CREATE USER IF NOT EXISTS 'metabase_user'@'%' IDENTIFIED BY 'MetabasePass@123';
CREATE USER IF NOT EXISTS 'metabase_user'@'localhost' IDENTIFIED BY 'MetabasePass@123';

-- 4. Grant READ-ONLY privileges to `seg_demo` for analytics security
GRANT SELECT ON `seg_demo`.* TO 'metabase_user'@'%';
GRANT SELECT ON `seg_demo`.* TO 'metabase_user'@'localhost';

-- 5. Grant FULL privileges to `metabase_db` for Metabase internal metadata storage
GRANT ALL PRIVILEGES ON `metabase_db`.* TO 'metabase_user'@'%';
GRANT ALL PRIVILEGES ON `metabase_db`.* TO 'metabase_user'@'localhost';

-- 6. Apply privilege changes
FLUSH PRIVILEGES;

-- ==============================================================================
-- Summary Output
-- ==============================================================================
SELECT 'Metabase MySQL user & permissions successfully created!' AS `Status`;
