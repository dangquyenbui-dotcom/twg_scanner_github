
### `README.md`

```markdown
# TWG Warehouse Scanner (Web App)

## 📌 Current Project Status
**Phase:** 3 - Batch Scanning & Logic Validation
**Write Mode:** 🔴 **READ-ONLY / SIMULATION**
*The application currently validates all logic (Inventory limits, Order limits, Location checks) but returns a "Simulation Success" message instead of executing `INSERT` or `UPDATE` SQL statements.*

---

## 🛠 Tech Stack
* **Backend:** Python (Flask)
* **Database:** SQL Server (via `pyodbc`)
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (ES6)
* **Target Device:** Zebra TC52 (Mobile Viewport)

---

## ⚙️ Configuration & Settings

### Environment Variables (`.env`)
The application relies on a `.env` file for database credentials.
```ini
DB_DRIVER={ODBC Driver 17 for SQL Server}
DB_SERVER=YOUR_SERVER_IP
DB_UID=YOUR_USER
DB_PWD=YOUR_PASSWORD
DB_AUTH=PRO12     # Authentication & Inventory DB
DB_ORDERS=PRO05   # Sales Order DB

```

### Smart Column Detection (Global Cache)

Because the database schema varies (e.g., `terr` vs `loctid`), the app runs `detect_columns()` on login to identify valid column names.

* **Inventory Location:** Checks `ScanOnhand2` for `loctid`, `terr`, or `location_id`.
* **User Location:** Checks `ScanUsers` for `location` or `location_id`.
* **UPC Support:** Checks if `ScanBinTran2` and `ScanItem` have a `upc` column.

---

## 🧠 Core Logic & Workflows

### 1. Authentication (`/login`)

* **Input:** User ID (Scanned) & Password.
* **Logic:**
* Validates against `ScanUsers`.
* **Location Locking:** Captures the user's warehouse (e.g., 'ATL').
* Updates `userstat=1` (Online).



### 2. Picking Workflow (`/picking`)

This is the primary feature. The workflow forces a specific sequence to ensure physical verification.

#### A. Order Selection

* User scans Sales Order (SO).
* **Validation:**
* Does SO exist?
* **Location Guard:** If User is 'ATL' but Order is 'LA', access is **BLOCKED** (unless User is Admin/000).



#### B. Item Selection (Grid)

* User sees a list of items for that SO (Filtered by their Location).
* **Interaction:** User **MUST** tap a row to select an item.
* **Data:** Row stores `data-remaining` (Qty Ordered - Qty Shipped) for validation limits.

#### C. Bin Validation (Step 1)

* User scans a Bin Label.
* **Endpoint:** `/validate_bin`
* **Logic:** Checks if the selected item exists in the scanned bin with `onhand > 0`.
* **Result:** Returns the specific `currentBinMaxQty` (e.g., "Bin has 5 items").

#### D. Item Scanning (Step 2)

* User scans the Item/UPC.
* **Logic:**
* **Match Check:** Scanned string must match Selected Item Code.
* **Auto Mode:** Increments Session Qty by 1 automatically.
* **Manual Mode:** Focuses Qty input for manual entry.



#### E. Quantity Guards (Double Control)

Before adding to the local "Shopping Cart" (Session), the system checks:

1. **Bin Limit:** `SessionQty + NewQty <= currentBinMaxQty` (Don't pick more than physically exists in that bin).
2. **Order Limit:** `TotalPickedForLine + NewQty <= RemainingOrderQty` (Don't over-pick the order).

### 3. Batching & Submission

* **Local Storage:** Picks are stored in a JavaScript array `sessionPicks`.
* **Multi-Bin Support:** Users can pick 5 from Bin A, then 5 from Bin B. Both entries are stored.
* **Review:** "View Scanned" modal allows deleting incorrect entries before submission.
* **Submit:**
* Endpoint: `/process_batch_scan`
* Iterates through the batch.
* Re-validates **Inventory** and **Order Limits** on the server side (Security).
* **Current Action:** Returns JSON `{status: 'success', msg: 'SIMULATION...'}`.



---

## 🔌 API Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/login` | POST | Authenticates user & detects DB columns. |
| `/picking` | GET | Fetches SO lines (Filtered by Location). |
| `/get_item_bins` | POST | Populates "View Bins" modal for specific item. |
| `/validate_bin` | POST | Checks if Item is in Bin. Returns `onhand` qty. |
| `/process_batch_scan` | POST | Validates and (Simulates) saving the pick list. |

---

## 📱 UI/UX Specifics (Zebra TC52)

* **Inputs:** Large, high-contrast inputs for barcode scanners.
* **Action Bar:** Buttons (View Scanned, Submit) are static inside the card (not fixed footer) to ensure visibility above on-screen keyboards.
* **Visibility:**
* "Picked Qty" input is 40px font size.
* Flashes **Green** on successful Auto-Scan.
* Review Modal uses high-contrast text.



---

## 📝 Next Steps (To Resume)

1. **Disable Simulation:** In `app.py` -> `process_batch_scan`, uncomment/enable the SQL `INSERT` into `ScanBinTran2` and `UPDATE` `SOTRAN`.
2. **Transaction ID:** Ensure unique Transaction IDs if required by the ERP.
3. **Inventory Decrement:** Currently, we update `SOTRAN` (Order). Decide if we also need to immediately `UPDATE ScanOnhand2` (Inventory) or if the ERP triggers handles that.

```

```