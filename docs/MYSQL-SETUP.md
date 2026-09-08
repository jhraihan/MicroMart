# Setting up MySQL for MicroMart

What this gets you: a database called `ecom`, a user called `ecom` that owns it,
and a `.env` file pointing at them. After that the project runs and its ~1,000
tests can execute.

## What is on your machine right now

Checked on 2026-09-07:

| Thing | State |
|---|---|
| MySQL **8.0.42** | Running as the Windows service `MySQL80`, on port **3306** |
| Its `root` password | Set, and currently unknown |
| MySQL Workbench 8.0 | Installed |
| XAMPP (with MariaDB) | Installed, not holding the port |
| `ecom` database | Does not exist yet |
| `backend/.env` | Exists, but points at port 3307 where nothing is listening |

Two things worth knowing before you start:

- **The port in the docs is wrong.** `scripts/create_database.sql` and
  `.env.example` say 3307. Your server is on **3306**. Use 3306 everywhere
  below.
- **Do not start XAMPP's MySQL.** It is MariaDB, a different database. It wants
  the same port, and the project needs real MySQL 8.

---

## Step 1 — Find or reset the root password

Try these in order. Stop as soon as one works.

### Option A — You remember it

Skip to Step 2.

### Option B — Ask MySQL Workbench (try this first)

Workbench usually saves the password from when you installed MySQL.

1. Open **MySQL Workbench** from the Start menu.
2. On the home screen there should be a connection tile, often called
   `Local instance MySQL80`. Double-click it.
3. If it opens without asking for a password, the password is saved on this
   machine. To read it back:
   - **Database → Manage Server Connections**
   - Pick the connection, then the **Connection** tab
   - Next to Password, click **Store in Vault** — it shows the saved value

If that works, you have the password. Go to Step 2.

### Option C — Reset it

Use this if A and B failed. It takes about three minutes.

**What it does:** changes the `root` password and nothing else. Every database,
table and row stays exactly as it is.

**Before you start:** close MySQL Workbench, and stop XAMPP's MySQL if it is
running. Nothing else should be using the database.

---

#### C1. Open PowerShell as Administrator

Press **Start**, type `powershell`, right-click **Windows PowerShell**, choose
**Run as administrator**, and click Yes.

The window title must begin with **Administrator:**. If it does not, the
commands below will fail with "Access is denied".

---

#### C2. Stop the MySQL service

Copy this line, paste it, press Enter:

```powershell
Stop-Service MySQL80
```

Nothing prints if it works. Confirm with:

```powershell
Get-Service MySQL80
```

Status must say **Stopped**. If it says "Cannot find any service", you are not
in an Administrator window — go back to C1.

---

#### C3. Create the password file

**Decide your new root password now.** Below it is `NewPass123!` — replace it
with yours in the first line, keeping the single quotes around it.

Paste this whole block at once, then press Enter:

```powershell
Set-Content -Path C:\mysql-reset.sql -Encoding ascii -Value "ALTER USER 'root'@'localhost' IDENTIFIED BY 'NewPass123!';"
```

Check the file is there and reads back correctly:

```powershell
Get-Content C:\mysql-reset.sql
```

It should print your line, with your password visible. If it prints nothing,
the file did not save — re-run the command above.

---

#### C4. Start MySQL so it runs that file

This is the step that trips people up, so read it before pasting.

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" --defaults-file="C:\ProgramData\MySQL\MySQL Server 8.0\my.ini" --init-file="C:\mysql-reset.sql" --console
```

**What you will see:** a wall of log lines. The window **will not return to a
prompt**, and that is correct — the server is running inside this window.

Wait until the scrolling stops and you can see a line ending in
**`ready for connections`**. That usually takes 10-30 seconds.

> **Why `--defaults-file` matters:** it points MySQL at your existing config so
> it uses your real data folder. Leaving it out makes MySQL look somewhere else
> and the reset does not apply to your actual server.

---

#### C5. Stop that temporary server

With that same window focused, press **Ctrl + C**.

If the prompt does not come back after a few seconds, just close the window.

---

#### C6. Delete the password file

It holds your password in plain text, so remove it:

```powershell
Remove-Item C:\mysql-reset.sql
```

---

#### C7. Start the service normally

```powershell
Start-Service MySQL80
Get-Service MySQL80
```

Status must say **Running**.

---

#### C8. Confirm the new password works

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p -e "SELECT VERSION();"
```

Type your new password and press Enter. **The screen shows nothing while you
type — no dots, no stars. That is normal.**

Seeing `8.0.42` means it worked. Go to Step 2.

---

#### If C4 fails

**"Access is denied"** — not an Administrator window. Redo C1.

**"Can't start server: Bind on TCP/IP port: Address already in use"** — MySQL
is still running. Press Ctrl+C, run `Stop-Service MySQL80`, and check XAMPP is
not running its own MySQL. Then retry C4.

**The window closes immediately** — usually a typo in the path. Copy the C4
line again exactly; the quotes around both paths are required because the
folder names contain spaces.

**"Table 'mysql.user' doesn't exist"** — `--defaults-file` was missing or
misspelled, so MySQL started against an empty data folder. Press Ctrl+C and
retry C4 with the full line.

---

## Step 2 — Create the database and user

You can do this in Workbench or on the command line. Either is fine.

Choose a password for the **application** user. It is separate from the root
password and is the one that goes in `.env`.

### In Workbench

Open your connection, click the SQL editor tab, paste this, and press the
lightning-bolt button to run it. Change `AppPassword123!` first.

```sql
CREATE DATABASE IF NOT EXISTS ecom
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'ecom'@'localhost' IDENTIFIED BY 'AppPassword123!';
CREATE USER IF NOT EXISTS 'ecom'@'127.0.0.1' IDENTIFIED BY 'AppPassword123!';

GRANT ALL PRIVILEGES ON ecom.* TO 'ecom'@'localhost';
GRANT ALL PRIVILEGES ON ecom.* TO 'ecom'@'127.0.0.1';

GRANT ALL PRIVILEGES ON `test_ecom`.* TO 'ecom'@'localhost';
GRANT ALL PRIVILEGES ON `test_ecom`.* TO 'ecom'@'127.0.0.1';

FLUSH PRIVILEGES;
```

### On the command line

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p
```

Enter the root password, then paste the same SQL, then type `exit`.

### Why each part is there

- **Two users, `localhost` and `127.0.0.1`.** MySQL treats them as different
  accounts. Django connects to `127.0.0.1`, but MySQL often resolves that back
  to the name `localhost`. Creating both means it works either way — this is a
  classic hour-wasting error.
- **`test_ecom` grant.** When the test suite runs, Django creates a throwaway
  database called `test_ecom`. Without this grant, every test fails with
  "Unknown database 'test_ecom'".
- **`utf8mb4`.** Full Unicode, so Bengali text and emoji store correctly.

---

## Step 3 — Point the project at it

Open `backend/.env` and set this one line, using your **application** password
from Step 2:

```
DATABASE_URL=mysql://ecom:AppPassword123!@127.0.0.1:3306/ecom
```

Note the port is **3306**, not the 3307 the older docs mention.

If your password contains `@`, `:`, `/` or `#`, those confuse the URL. Either
pick a password without them, or percent-encode them (`@` becomes `%40`).

`.env` is gitignored, so this password never reaches GitHub.

---

## Step 4 — Build the tables and check it works

From `backend/`, with the virtual environment active:

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py migrate
```

`migrate` creates every table. It should end with a list of applied migrations
and no errors.

Then load some data and create your admin login:

```powershell
.venv\Scripts\python.exe manage.py seed_demo      # logins, shipping zones, a few products
.venv\Scripts\python.exe manage.py seed_catalog   # the full 117-product catalogue
```

---

## Step 5 — Run the test suite

```powershell
.venv\Scripts\python.exe -m pytest -q
```

This is the part that has never run. Expect it to take several minutes. Some
tests deliberately open real database locks on real threads to prove the shop
cannot sell the same last item twice.

---

## If something goes wrong

**`Access denied for user 'ecom'@'localhost'`**
The password in `.env` does not match what you set in Step 2, or only one of
the two user accounts was created. Re-run the `CREATE USER` and `GRANT` lines.

**`Unknown database 'test_ecom'`**
The `test_ecom` grant in Step 2 was missed. Run those two `GRANT` lines.

**`Can't connect to MySQL server on '127.0.0.1'`**
The service is not running. In PowerShell: `Start-Service MySQL80`.

**`Unknown collation: 'utf8mb4_0900_ai_ci'`**
You are talking to MariaDB (XAMPP), not MySQL 8. Stop XAMPP's MySQL from its
control panel and make sure the `MySQL80` service is the one running.

**Port 3306 already in use**
Something else grabbed it, usually XAMPP. Stop XAMPP's MySQL, then
`Restart-Service MySQL80`.

**Checking which server you are actually talking to**

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p -e "SELECT VERSION();"
```

`8.0.42` is the right one. Anything saying `MariaDB` is XAMPP's.

---

## When you are done

Tell me the application password, or just say it is set up, and I will:

1. Confirm the connection and that the tables are built
2. Run the full test suite and report the real numbers
3. Verify the backend security fixes that are still waiting on a working
   database
4. Take the screenshots the README needs
