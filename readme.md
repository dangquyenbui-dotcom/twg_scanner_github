### 1. Updated `requirements.txt`

This file contains the necessary Python dependencies to run the Flask application and connect to the SQL Server database.

```text
flask
pyodbc
python-dotenv

```

### 2. Updated `README.md`

This document provides a comprehensive overview of the project, including its current phase, features, security logic, and the specific UI/UX behaviors implemented for the Zebra TC52.

```markdown
# TWG Warehouse Scanner (Web App)

## 📌 Current Project Status
**Phase:** 3 - Batch Scanning & Logic Validation  
**Current Mode:** 🟢 **LIVE COMMIT MODE** *The application validates all logic (Inventory, Order limits, Location checks) and performs live SQL `UPDATE` and `INSERT` operations to the database.*

---

## 🛠 Tech Stack
* **Backend:** Python (Flask)
* **Database:** SQL Server (via `pyodbc`)
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (ES6)
* **Target Device:** Zebra TC52 (Mobile Viewport)

---

## ⚙️ Configuration & Settings

### Environment Variables (`.env`)
The application relies on a `.env` file for database credentials and server settings.
```ini
DB_DRIVER={ODBC Driver 17 for SQL Server}
DB_SERVER=YOUR_SERVER_IP
DB_UID=YOUR_USER
DB_PWD=YOUR_PASSWORD
DB_AUTH=PRO12     # Authentication & Inventory DB
DB_ORDERS=PRO05   # Sales Order DB

```

### Smart Column Detection

On login, the app runs `detect_columns()` to identify schema variations across different warehouse environments (e.g., detecting if the location column is named `terr` or `loctid`).

---

## 🧠 Core Logic & Features

### 1. Enhanced Sales Order Input

* **Hybrid Input Support:** Supports both manual typing and hardware scanner input.
* **Flexible Formatting:** Automatically handles Sales Order strings with leading spaces (e.g., `"   1234567"`) or standard strings (`"1234567"`).
* **Auto-Submission:** The system detects when a valid 7-digit Sales Order is entered (after trimming) and proceeds automatically.

### 2. Selective Control Locking (Safety Guard)

To prevent pick errors, the UI enforces a strict "Select-First" workflow:

* **Default State:** Upon entering the picking screen, all functional controls (Bin Scan, Item Scan, Qty, Bins button) are greyed out and disabled.
* **Activation:** Controls are only enabled once a user explicitly selects a specific line item from the Sales Order grid.

### 3. Picking Workflow & Guards

* **Bin Validation:** Users must scan a bin; the system verifies the item exists in that bin with available on-hand quantity.
* **Item Verification:** Scanned Item codes or UPCs must match the selected line item.
* **Quantity Guards:** * **Bin Limit:** Prevents picking more than is physically available in the scanned bin.
* **Order Limit:** Prevents over-picking beyond the remaining order quantity.



### 4. Batch Submission

* **Local Shopping Cart:** Picks are stored in `sessionPicks` locally, allowing users to pick from multiple bins for a single line before submitting.
* **Transactional Integrity:** On submission, the app uses SQL transactions to update `ScanOnhand2` (Inventory), `SOTRAN` (Orders), and `ScanBinTran2` (Audit Log) simultaneously.

---

## 📱 UI/UX Specifics

* **High Contrast:** Designed for warehouse lighting with large touch targets.
* **Visual Feedback:** * **Active Row:** Highlights the currently selected line item in yellow.
* **Flash Effects:** Inputs flash green upon a successful scan.


* **Full-Screen Mode:** Includes a dedicated toggle to maximize screen real estate on mobile browsers.

---

## 🔌 API Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/login` | POST | Authenticates user and detects DB columns. |
| `/picking` | GET | Fetches SO lines filtered by User Location. |
| `/get_item_bins` | POST | Returns available bins and stock for a specific item. |
| `/validate_bin` | POST | Verifies if an item is in a scanned bin. |
| `/process_batch_scan` | POST | Commits the entire pick list to the database. |

```

```