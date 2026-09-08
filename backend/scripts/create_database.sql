-- Development database bootstrap (PRD §6.5: InnoDB, utf8mb4 throughout).
--
-- 1. Replace CHANGE_THIS_PASSWORD below (both places) with a password you pick.
-- 2. Run it as root:
--
--      # macOS / Linux:
--      mysql -h 127.0.0.1 -P 3307 -u root -p < backend/scripts/create_database.sql
--
--      # Windows:
--      "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" \
--        -h 127.0.0.1 -P 3307 -u root -p -e "source backend/scripts/create_database.sql"
--
-- 3. Put the same password in backend/.env:
--      DATABASE_URL=mysql://ecom:THAT_PASSWORD@127.0.0.1:3307/ecom
--
-- Two accounts are created on purpose. MySQL resolves a 127.0.0.1 connection
-- back to the hostname 'localhost' unless skip-name-resolve is on, so a user
-- granted only on '127.0.0.1' is refused with "Access denied". Creating both
-- makes the connection work either way.

CREATE DATABASE IF NOT EXISTS ecom
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'ecom'@'localhost' IDENTIFIED BY 'CHANGE_THIS_PASSWORD';
CREATE USER IF NOT EXISTS 'ecom'@'127.0.0.1' IDENTIFIED BY 'CHANGE_THIS_PASSWORD';

GRANT ALL PRIVILEGES ON ecom.* TO 'ecom'@'localhost';
GRANT ALL PRIVILEGES ON ecom.* TO 'ecom'@'127.0.0.1';

-- pytest-django creates and drops a parallel test database.
GRANT ALL PRIVILEGES ON `test_ecom`.* TO 'ecom'@'localhost';
GRANT ALL PRIVILEGES ON `test_ecom`.* TO 'ecom'@'127.0.0.1';

FLUSH PRIVILEGES;

SELECT 'ecom database and user ready' AS status;
