# TWG Warehouse Scanner (Web App)

## Project Status

**Version:** 1.11.0
**Phase:** 5 — Batch Scanning with Hardened Commit Logic + Short-Pick Exception Workflow + Zero Pick Workflow + IC Bin Reporting + Pending Picks Dashboard + Session Protection & Progress Tracking
**Current Mode:** LIVE COMMIT MODE — The application validates all logic (inventory availability, order limits, location checks) and performs live SQL `UPDATE` and `INSERT` operations against the database. All writes are wrapped in a single transaction with automatic rollback on any failure. Post-commit verification detects concurrent modifications and logs warnings without rollback.

---

## Tech Stack

- **Backend:** Python 3 (Flask)
- **Database:** Microsoft SQL Server (via `pyodbc`)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (ES6)
- **Email:** Office 365 SMTP (via Python `smtplib`, background thread delivery)
- **Target Device:** Zebra TC52 (Mobile Viewport, Portrait Orientation)
- **PWA Support:** Web App Manifest with fullscreen display mode
- **Proxy/CDN:** Cloudflare (via `dev.thewheelgroup.info`)
- **Client Persistence:** localStorage (user-scoped keys for multi-picker shared devices)

---

## Project Structure

```
twg_scanner_github/
├── app.py                  # Flask application — all routes, business logic, and email sender
├── config.py               # Environment variable loader, app version, and configuration
├── requirements.txt        # Python dependencies (flask, pyodbc, python-dotenv)
├── .env                    # Environment variables (DB credentials, SMTP credentials, IC email)
├── .gitignore              # Git exclusion rules (venv, .env, __pycache__, etc.)
├── static/
│   ├── css/
│   │   ├── style.css       # Global styles, layout system, table, modal, buttons, dashboard
│   │   └── picking.css     # Picking-specific styles, keyboard-aware layout, progress bar
│   ├── js/
│   │   ├── utils.js        # Shared utilities: UUID, audio, fullscreen, logging
│   │   ├── picking.js      # Core picking logic: state, scanning, validation, submission, navigation guards
│   │   └── picking-ui.js   # UI rendering: toasts, modals, bin list, review list, custom dialogs, bin report, progress bar
│   ├── logo/
│   │   ├── twg.png         # TWG brand logo used across all pages
│   │   ├── twg-192.png     # PWA icon (192x192)
│   │   └── twg-512.png     # PWA icon (512x512)
│   └── manifest.json       # PWA manifest for home screen install
├── templates/
│   ├── login.html          # User authentication screen
│   ├── dashboard.html      # Main menu with clock, app grid, pending picks detection, and localStorage cleanup
│   └── picking.html        # Order picking interface (SO entry + pick screen + all modals + progress bar + picker warning)
└── README.md               # This file
```

---

## Configuration

### Environment Variables (`.env`)

```ini
SECRET_KEY=your_flask_secret_key
DB_DRIVER={ODBC Driver 18 for SQL Server};TrustServerCertificate=yes
DB_SERVER=YOUR_SERVER_IP
DB_UID=YOUR_USER
DB_PWD=YOUR_PASSWORD
DB_AUTH=PRO12       # Database for Inventory, Users, Audit (ScanOnhand2, ScanUsers, ScanBinTran2, ScanItem)
DB_ORDERS=PRO05     # Database for Sales Orders (SOTRAN, SOMAST)

# Email Configuration (Office 365 SMTP for Bin Reports to IC Team)
SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
SMTP_USER=no_reply@thewheelgroup.com
SMTP_PASSWORD=YOUR_SMTP_PASSWORD
IC_EMAIL=recipient1@thewheelgroup.com,recipient2@thewheelgroup.com
```

The `IC_EMAIL` field supports **comma-separated multiple recipients**. All listed email addresses receive the bin report when a picker flags a bin for investigation.

### Config Class (`config.py`)

The `Config` class loads all values from environment variables with fallback defaults. Key configuration groups:

- **`APP_VERSION`** — Centralized version string used as a cache-buster query parameter on all static assets (`?v=1.11.0`). Bump this value on every deploy to force Cloudflare and browser caches to fetch fresh JS, CSS, images, and the PWA manifest. All three templates (`login.html`, `dashboard.html`, `picking.html`) read this value via `{{ config.APP_VERSION }}`.

- **`DB_AUTH`** — Used for inventory tables (`ScanOnhand2`), user authentication (`ScanUsers`), UPC mapping (`ScanItem`), and audit logging (`ScanBinTran2`).

- **`DB_ORDERS`** — Used for the sales order tables (`SOTRAN`, `SOMAST`).

- **`SMTP_*` / `IC_EMAIL`** — Office 365 SMTP connection settings and recipient list for the IC Bin Report email feature.

- **`SIMULATION_MODE`** — Reserved flag. Set to `False` for live database writes (current default). Set to `True` to validate logic without committing changes (not currently enforced in routes — reserved for future use).

---

## Setup & Installation

### Prerequisites

- Python 3.8+
- Microsoft SQL Server (with ODBC Driver 17 or 18 installed)
- Office 365 SMTP account (for bin report emails)

### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd twg_scanner_github

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file with your credentials
# (see Environment Variables section above)

# 5. Run the application
python app.py
```

The application starts on `http://0.0.0.0:5000` with debug mode enabled.

### Dependencies (`requirements.txt`)

| Package | Purpose |
|---------|---------|
| `flask` | Web framework, routing, session management, template rendering |
| `pyodbc` | ODBC database driver for SQL Server connections |
| `python-dotenv` | Loads `.env` file into `os.environ` at startup |

---

## Cache-Busting Strategy

All static asset references in templates use a version query parameter sourced from `Config.APP_VERSION`:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v={{ config.APP_VERSION }}">
<script src="{{ url_for('static', filename='js/picking.js') }}?v={{ config.APP_VERSION }}"></script>
```

This covers CSS files, JavaScript files, logo images, PWA icon images, and the manifest.json file. When `APP_VERSION` is bumped (e.g., from `1.10.0` to `1.11.0`), every asset URL changes, forcing both Cloudflare edge caches and browser/PWA caches to fetch fresh copies.

**Deployment workflow:**

1. Make code changes.
2. Bump `APP_VERSION` in `config.py`.
3. Deploy to server.
4. (Optional) Purge Cloudflare cache once — after that, the version string handles cache invalidation automatically.

The login page footer and dashboard footer version labels also read from `APP_VERSION` dynamically, so the displayed version always matches the deployed code.

---

## Database Tables

### ScanUsers (DB_AUTH)

User authentication and session management.

| Column | Purpose |
|--------|---------|
| `userid` | Login identifier (uppercased on input) |
| `pw` | Password (plain-text match) |
| `location` or `location_id` | Warehouse location assignment (auto-detected) |
| `userstat` | Online status flag (set to `1` on login) |

### ScanOnhand2 (DB_AUTH)

Bin-level inventory with on-hand and allocation tracking.

| Column | Purpose |
|--------|---------|
| `item` | Item/SKU code |
| `bin` | Physical bin location (15-character format) |
| `onhand` | Total quantity physically in the bin |
| `aloc` or `alloc` | Allocated quantity (auto-detected column name) |
| `avail` | Computed available quantity (`onhand - aloc`) |
| `loctid` or `terr` | Warehouse location code (auto-detected) |
| `lupdate` | Last update timestamp |
| `luser` | Last user who modified the record |

### SOMAST (DB_ORDERS)

Sales order master header.

| Column | Purpose |
|--------|---------|
| `sono` | Sales order number |
| `picker` | Assigned picker (must be non-empty to allow picking) |

### SOTRAN (DB_ORDERS)

Sales order transaction lines.

| Column | Purpose |
|--------|---------|
| `sono` | Sales order number |
| `tranlineno` | Line number within the order |
| `item` | Item/SKU code |
| `qtyord` | Quantity ordered |
| `shipqty` | Quantity already shipped/picked |
| `stkcode` | Stock code flag (only `'Y'` lines are pickable) |
| `sostat` | Line status flag (`'X'` = cancelled, excluded from picks) |
| `loctid` | Location assignment for the order line |
| `shipdate` | Last ship/pick date |

### ScanBinTran2 (DB_AUTH)

Audit log for all pick transactions.

| Column | Value Written | Purpose |
|--------|---------------|---------|
| `actiontype` | `'SP'` | Scan Pick action type |
| `applid` | `'SO'` | Application identifier (Sales Order) |
| `udref` | Sales order number | Reference to the source order |
| `tranlineno` | Line number | Which order line was picked |
| `upc` | Item code | UPC/item identifier |
| `item` | Item code | Item/SKU code |
| `binfr` | Bin location | Which bin the pick came from |
| `quantity` | Pick quantity | How many units were picked |
| `userid` | Session user | Who performed the pick |
| `deviceid` | Empty string | Reserved for device tracking |
| `adddate` | `GETDATE()` | Server-side timestamp |
| `scanstat` | Empty string | Reserved for future use |
| `scanresult` | Exception code or empty | Short-pick reason code (e.g., `SHORT`, `DMG`, `NOFND`, `BADLC`) |

### ScanItem (DB_AUTH)

UPC-to-item mapping table.

| Column | Purpose |
|--------|---------|
| `item` | Item/SKU code |
| `upc` | UPC barcode value |

---

## Smart Column Detection (`detect_columns()`)

On the first login, the application runs `detect_columns()` to dynamically identify schema variations across different warehouse database environments. Results are cached in the global `DB_COLS` dictionary for the lifetime of the process.

**Detected variations:**

| Check | Option A | Option B | Fallback |
|-------|----------|----------|----------|
| Inventory location column | `loctid` | `terr` | `terr` |
| Inventory allocation column | `aloc` | `alloc` | `aloc` |
| Users location column | `location_id` | `location` | `location` |
| BinTran2 UPC column | exists (`True`) | missing (`False`) | `False` |

The detection runs `SELECT TOP 1 *` against each table and inspects `cursor.description` for column names. This avoids hard-coding column names that may differ between warehouse installations.

---

## Bin Validation (`is_valid_bin()`)

Bin values are validated both server-side and client-side using identical rules:

1. Must be exactly **15 characters** long.
2. The **5th character** (index 4) must be **numeric** (0-9).

This filters out non-standard bin codes (e.g., `000-PK-0-0` for packing stations) that should not appear in pick workflows. The validation is applied in three places:

- **Server-side** in `/get_item_bins` — filters query results before returning to client.
- **Client-side** in `picking-ui.js` (`isValidBin()`) — filters the bin list modal display.
- **Server-side** in `is_valid_bin()` — reusable Python helper function.

---

## API Endpoints

### `GET /health`

Returns server status and current timestamp. Used for uptime monitoring.

**Response:** `{ "status": "online", "time": "2026-03-13T08:00:00" }`

### `GET /`

Redirects to `/dashboard` if logged in, otherwise redirects to `/login`.

### `POST /login`

Authenticates a user against the `ScanUsers` table.

**Process:**
1. Triggers `detect_columns()` on first call.
2. Strips and uppercases the user ID input.
3. Queries `ScanUsers` with parameterized `userid` and `pw` match.
4. On success: stores `user_id` and `location` in Flask session, sets `userstat=1`.
5. On failure: flashes error message to the login form.

### `GET /dashboard`

Renders the main menu with a live clock, user info, and app grid. Only the "Order Pick" module is currently active. Other modules (Cycle Count, Receiving, Label Print) are shown as disabled placeholders. Requires an active session.

**Client-side features (v1.10.0+):**
- **Pending Picks Detection** — Scans localStorage for unsubmitted pick sessions belonging to the current user. Displays a prominent amber resume banner with SO numbers, pick counts, and timestamps.
- **Old-Key Migration** — Automatically migrates pre-v1.10.0 non-user-scoped localStorage keys to the new user-scoped format.
- **Stale Data Cleanup** — Removes pick data older than 7 days to prevent localStorage bloat on shared devices.

### `GET /picking?so=<order_number>`

Fetches and displays order lines for picking. This endpoint handles two states:

**State 1 — No SO provided:** Renders the Sales Order input screen where the user scans or types a 7-digit SO number.

**State 2 — SO provided:** Queries the order and renders the picking grid.

**Process:**
1. Resolves the SO number using a `LIKE` match (handles leading spaces in the database).
2. Validates picker assignment by checking `SOMAST.picker` is non-empty. If no picker is assigned, the order is rejected with an error message.
3. Reads the `picker` value and passes it to the template as `assigned_picker` for the picker warning banner.
4. Fetches open order lines from `SOTRAN` where `qtyord > shipqty`, `stkcode = 'Y'`, and `sostat <> 'X'` (excludes cancelled lines).
5. Filters by user location unless the user is assigned to location `'000'` (all-access) or `'Unknown'`.
6. Fetches UPC mappings from `ScanItem` for all unique items in the order.
7. Strips whitespace from all item codes and UPC values during mapping.
8. If no open lines remain, flashes a "fully picked" success message.

### `POST /get_item_bins`

Returns available bin locations and stock levels for a specific item.

**Request body:** `{ "item": "ITEM_CODE" }`

**Process:**
1. Queries `ScanOnhand2` for all bins where `onhand > 0` for the given item.
2. Filters by user location (using `LIKE` for prefix matching) unless location is `'000'` or `'Unknown'`.
3. Sorts by available quantity ascending (lowest availability first).
4. Filters out invalid bins using `is_valid_bin()` (must be 15 chars, numeric 5th character).
5. Returns `onhand`, `alloc`, and computed `avail` for each bin.

**Response:** `{ "status": "success", "bins": [{ "bin": "...", "qty": 10, "alloc": 2, "avail": 8, "loc": "..." }] }`

### `POST /validate_bin`

Verifies that a specific item exists in a scanned bin with available stock.

**Request body:** `{ "bin": "BIN_CODE", "item": "ITEM_CODE" }`

**Process:**
1. Queries `ScanOnhand2` for a matching `bin + item` combination with `onhand > 0`.
2. Applies location filtering consistent with other endpoints.
3. Returns the on-hand quantity if found, or an error message if the bin is empty or mismatched.

**Response (success):** `{ "status": "success", "onhand": 10 }`
**Response (failure):** `{ "status": "error", "msg": "Bin 'XXX' Empty/Mismatch" }`

### `POST /report_bin`

Receives a bin issue report from the picker and sends an email to the IC (Inventory Control) team in the background. Returns immediately so the picker can continue working without interruption.

**Request body:**
```json
{
  "bin": "000-10-01-02-03",
  "item": "ITEM-ABC",
  "reason": "Qty Mismatch",
  "notes": "System says 10 but only 6 on shelf",
  "onhand": 10,
  "alloc": 2,
  "avail": 8,
  "so": "1234567"
}
```

**Process:**
1. Validates session — returns error if expired.
2. Validates that `bin` and `reason` are present.
3. Truncates `notes` to 500 characters maximum (abuse prevention).
4. Assembles report data including picker ID, warehouse location, and server timestamp from the session.
5. Logs the report at `INFO` level.
6. Spawns a background thread (`threading.Thread`, daemon mode) to send the email via Office 365 SMTP. The picker's HTTP request returns immediately — it does not wait for SMTP delivery.
7. Returns success response.

**Email details:**
- **Subject:** `[IC Action Required] Bin Report — {bin} | {reason} | Item {item}`
- **Format:** HTML email with plain-text fallback. The HTML version uses TWG branding, a color-coded alert banner, and a structured detail grid showing all bin metrics, the sales order context, picker identity, and timestamp.
- **Recipients:** All comma-separated addresses in the `IC_EMAIL` environment variable.
- **Sender:** The `SMTP_USER` address (Office 365 authenticated).
- **SMTP connection:** TLS via `smtp.office365.com:587` with `STARTTLS`.
- **Error handling:** SMTP failures are caught and logged at `ERROR` level. They do not affect the picker's response — the picker always gets a success toast. Failed emails appear only in server logs.

**Available issue types (picker selects one):**
- `Qty Mismatch` — System quantity does not match physical count
- `Label Issue` — Wrong, missing, or damaged bin/item label
- `Damaged Product` — Product found but damaged
- `Wrong Item in Bin` — Bin contains a different item than expected
- `Bin Disorganized` — Mixed SKUs or messy bin
- `Safety Hazard` — Safety concern in or around the bin
- `Other` — Free-text description in notes field

**Response (success):** `{ "status": "success", "msg": "Report submitted for bin 000-10-01-02-03. IC team has been notified." }`
**Response (error):** `{ "status": "error", "msg": "Bin and reason are required." }`

### `POST /process_batch_scan`

**This is the core transactional endpoint.** It commits all picks from a session to the database, updating inventory, the sales order, and the audit log in a single atomic transaction.

**Request body:**
```json
{
  "so": "ORDER_NUMBER",
  "picks": [
    { "lineNo": 1, "item": "ITEM1", "bin": "BIN_CODE", "qty": 5 },
    { "lineNo": 1, "item": "ITEM1", "bin": "BIN_CODE2", "qty": 3 }
  ],
  "exceptions": {
    "1": "SHORT",
    "3": "NOFND"
  },
  "batch_id": "uuid-string"
}
```

The `exceptions` object is optional. It maps `tranlineno` (as string) to a short-pick reason code. These codes are written to the `scanresult` column in `ScanBinTran2` for lines that were partially picked. Valid codes are `SHORT`, `DMG`, `NOFND`, `BADLC` (max 10 characters, truncated for safety).

**The commit process follows 6 sequential phases:**

---

#### Phase 1: Pre-Aggregate Line Totals

Before any database reads, picks are aggregated by `tranlineno`. Multiple picks for the same order line (e.g., from different bins) are summed into a single quantity per line. This aggregated total is used for the SOTRAN over-ship validation.

**Zero-qty picks** (from the Zero Pick workflow) are excluded from this aggregation. They do not affect inventory or SOTRAN — their only purpose is to write an audit record in Phase 5.

---

#### Phase 2: Pre-Commit Validation (Read-Only)

All picks are validated against the current database state before any UPDATE is executed. If any check fails, the entire batch is rejected immediately with no data changes.

**Inventory check (per pick):**
```sql
SELECT onhand, ISNULL(aloc, 0) as current_alloc
FROM ScanOnhand2
WHERE item=? AND bin=? AND loctid=?
```
- Verifies the row exists (item is in that bin at that location).
- Computes `available = onhand - current_alloc`.
- Rejects if `available < requested_qty`.

**Order check (per aggregated line):**
```sql
SELECT qtyord, shipqty, (qtyord - shipqty) as remaining
FROM SOTRAN
WHERE sono=? AND tranlineno=? AND item=?
```
- Verifies the order line exists.
- Computes remaining pickable quantity.
- Rejects if `remaining < aggregated_qty` (would cause over-shipment).

---

#### Phase 3: Inventory Update (ScanOnhand2)

For each pick, the allocation is incremented and available quantity is recomputed.

```sql
UPDATE ScanOnhand2
SET aloc = ISNULL(aloc, 0) + ?,
    avail = onhand - (ISNULL(aloc, 0) + ?),
    lupdate = GETDATE(),
    luser = ?
WHERE item=? AND bin=? AND loctid=?
  AND (onhand - ISNULL(aloc, 0)) >= ?    -- SQL-LEVEL GUARD
```

**SQL-level guard:** The `WHERE` clause includes `(onhand - ISNULL(aloc, 0)) >= ?` which prevents the update from executing if another user has allocated stock between the pre-check and this update (race condition protection). If `rowcount == 0`, the transaction is rolled back with a clear error message indicating a likely concurrent pick.

---

#### Phase 4: Sales Order Update (SOTRAN)

For each aggregated order line, the shipped quantity is incremented.

Before the update, the current `shipqty` is read and stored to compute the expected post-commit value for Phase 6 verification.

```sql
UPDATE SOTRAN
SET shipqty = shipqty + ?,
    shipdate = GETDATE()
WHERE sono=? AND tranlineno=? AND item=?
  AND (qtyord - shipqty) >= ?             -- SQL-LEVEL GUARD
```

**SQL-level guard:** The `WHERE` clause includes `(qtyord - shipqty) >= ?` which prevents over-shipment at the database level, even if two users submit simultaneously for the same order line. If `rowcount == 0`, the transaction is rolled back.

---

#### Phase 5: Audit Log Insert (ScanBinTran2)

One row is inserted per pick (not per aggregated line) to maintain full granularity of which bin each unit came from. **Zero-qty picks are included in this phase** — this is their only database write, ensuring a full audit trail for lines the picker could not fulfill.

```sql
INSERT INTO ScanBinTran2
(actiontype, applid, udref, tranlineno, upc, item, binfr, quantity, userid, deviceid, adddate, scanstat, scanresult)
VALUES ('SP', 'SO', ?, ?, ?, ?, ?, ?, ?, '', GETDATE(), '', ?)
```

**Exception code priority:** The `scanresult` column value is determined by checking two sources in order:

1. **Pick-level exception** — embedded directly in the pick object by the Zero Pick workflow (e.g., `NOFND`, `DMG`).
2. **Top-level exceptions dict** — collected from the Short-Pick exception modal at submit time (e.g., `SHORT`, `DMG`, `NOFND`, `BADLC`).
3. **Empty string** — for fully-picked lines with no exception.

For zero-qty picks, `quantity` is `0` and `binfr` (bin) is empty since the picker never scanned a bin. The exception code in `scanresult` records the reason.

---

#### Phase 6: Post-Commit Verification (Read-Only)

After `conn.commit()` succeeds, the application performs read-only verification to confirm the data landed correctly. **This phase never triggers a rollback** — the data is already committed. Failures are logged at `CRITICAL` level for manual review.

**SOTRAN shipqty verification:**
For each updated order line, the application re-reads `shipqty` and compares it to the expected value (pre-update value + aggregated pick quantity). A mismatch indicates a concurrent modification occurred between the pre-read and the commit.

If any post-commit warnings are generated, they are included in the response `warnings` array and logged, but the response status remains `'success'` since the transaction was committed.

**Response (success):**
```json
{
  "status": "success",
  "msg": "SUCCESS: Processed 3 lines.\nUpdated Inventory & Order.",
  "batch_id": "uuid-string",
  "warnings": null
}
```

**Response (success with warnings):**
```json
{
  "status": "success",
  "msg": "SUCCESS: Processed 3 lines.\nUpdated Inventory & Order.\n⚠️ 1 verification warning(s) logged.",
  "batch_id": "uuid-string",
  "warnings": ["POST-CHECK WARN: Line 1 (item 'ABC') — expected shipqty=10, actual=12."]
}
```

---

#### Error Handling

- Any exception in Phases 1-5 triggers `conn.rollback()` and returns `{ "status": "error", "msg": "..." }`.
- All quantities are cast to `int()` to avoid floating-point rounding issues.
- `ISNULL()` wrappers handle NULL allocation values in the database.

---

### `GET /logout`

Clears the Flask session and redirects to the login page.

---

## Frontend Architecture

### Layout System (`style.css`)

The application uses a fixed flexbox layout (`tc52-layout`) designed for the Zebra TC52 screen. The layout has three zones:

- **Header** (`tc52-header`) — Fixed at top. Shows app branding, user info, and current order number.
- **Grid** (`tc52-grid`) — Flexible middle section. Scrollable table of order lines.
- **Controls** (`tc52-controls`) — Fixed at bottom. Scan inputs, mode toggle, and action buttons.

### Keyboard-Aware Viewport (`picking.html` inline script)

When the virtual keyboard opens on mobile devices, the layout dynamically resizes to keep controls visible:

1. Listens to `window.visualViewport.resize` events.
2. Detects keyboard open/close by comparing viewport height to baseline (threshold: 80px reduction).
3. When open: adds `keyboard-open` class, sets explicit layout height, hides footer buttons, shows a context bar with the currently selected item info, hides the progress bar.
4. When closed: resets layout to full screen.
5. Recalculates baseline height on orientation changes and fullscreen state changes.

### Scanner Input Handling (`picking.js`)

The application supports both hardware barcode scanners (Zebra TC52) and manual keyboard input.

**Hardware scanner detection:** Hardware scanners inject text with `inputMode='none'` and fire rapidly. The `isVirtualKeyboardActive()` function checks `el.inputMode` to distinguish between scanner and keyboard input.

**Auto-trigger logic:**
- **Scanner input:** Auto-triggers action after 300ms debounce when input length > 5 characters.
- **Virtual keyboard input:** Waits for the user to press Enter (no auto-trigger to prevent premature submission while typing).
- **SO Input:** Auto-submits when exactly 7 digits are detected (after trimming).

**DataWedge symbology stripping (`stripWrappingAlpha()`):** Some Zebra DataWedge configurations add a symbology identifier character to both ends of a scanned UPC barcode (e.g., `A729419150129A`). The `stripWrappingAlpha()` function detects this pattern — alpha characters wrapping both ends of a purely numeric core — and strips them for comparison only. This does not affect bin scanning, SO input, or any data sent to the server. Examples:
- `'A729419150129A'` -> `'729419150129'` (stripped — alpha on both ends, numeric core)
- `'ABC12345'` -> `'ABC12345'` (unchanged — alpha only on left end)
- `'WIDGET-X'` -> `'WIDGET-X'` (unchanged — not a numeric core)

**Input flow:**
1. **Select Row** -> User taps an order line in the grid. Controls are enabled, bin input is focused.
2. **Scan Bin** -> Validates bin against `ScanOnhand2` (uses cache if available, otherwise calls `/validate_bin`). On success, focuses item input.
3. **Scan Item** -> Compares scanned value against the selected item code and its UPC (case-insensitive, with `stripWrappingAlpha()` applied). On mismatch, shows error and clears input.
4. **Add to Session** -> In Auto mode, automatically adds quantity of 1 after successful item scan. In Manual mode, user adjusts quantity and clicks ADD.

### Pick Modes

- **Auto Mode** (default): Quantity is fixed at 1. Each successful item scan immediately adds to the session. Designed for single-unit picks with a hardware scanner.
- **Manual Mode**: Quantity input is editable with +/- buttons. User must click ADD after scanning. Designed for bulk picks.

### UPC Translation Badge

When a scanned barcode matches a UPC (not the direct item code), a visual translation badge appears below the Scan Item input showing the UPC-to-item mapping. For example: `UPC 729419150129 -> ITEM-ABC`. The badge uses a slide-in animation and stays visible during repeated scans of the same UPC. It hides on row change, mismatch, or when the item code itself is scanned directly.

### Session Management (`picking.js`)

Picks are stored in a local `sessionPicks` array and persisted to `localStorage` under user-scoped keys prefixed with the user ID and SO number (`twg_picks_<USER>_<SO>`). This survives page refreshes, accidental navigation, and ensures picks are private per picker on shared devices.

**Normal session pick structure:**
```javascript
{ id: timestamp, lineNo: 1, item: "ITEM1", bin: "BIN_CODE", qty: 5, mode: "Auto" }
```

**Zero-pick session entry structure:**
```javascript
{ id: timestamp, lineNo: 3, item: "ITEM3", bin: "", qty: 0, mode: "Zero", exception: "NOFND" }
```

Zero-pick entries have `qty: 0`, `bin: ""` (no bin scanned), `mode: "Zero"`, and carry their exception code directly in the `exception` field. This distinguishes them from normal picks at every stage of the pipeline.

**Deduplication:** If a pick already exists for the same `lineNo + bin + item + mode`, the quantity is incremented rather than creating a duplicate entry. Auto and Manual picks for the same line/bin/item are stored as separate rows in the review list.

**Merge on commit:** Before submission, `mergePicksForCommit()` combines Auto and Manual rows for the same `lineNo + bin + item` into a single record by summing quantities. The `mode` field is dropped — the server never receives it. Zero-pick entries are passed through individually without merging (they carry their own exception code in the `exception` field and are appended to the merged result). This ensures identical commit behavior regardless of how the picks were accumulated.

**Guards (client-side):**
- **Bin limit:** Total picked from a bin cannot exceed the on-hand quantity reported during bin validation.
- **Order limit:** Total picked for a line cannot exceed the remaining order quantity (`qtyord - shipqty`).
- **Zero-pick duplicate guard:** A line can only have one Zero Pick entry. Attempting to zero-pick a line that already has one is blocked with a toast error.
- **Zero-pick conflict guard:** A line that already has normal picks (qty > 0) cannot be zero-picked. The picker should use the short-pick exception modal at submit time instead.

---

## localStorage Key Architecture

The application uses three types of localStorage keys per pick session, all scoped to the current user to prevent cross-user visibility on shared devices:

| Key Pattern | Purpose | Example |
|-------------|---------|---------|
| `twg_picks_<USER>_<SO>` | JSON array of session picks | `twg_picks_QUINN_1234567` |
| `twg_batch_id_<USER>_<SO>` | UUID for batch deduplication | `twg_batch_id_QUINN_1234567` |
| `twg_picks_ts_<USER>_<SO>` | ISO 8601 timestamp of last save | `twg_picks_ts_QUINN_1234567` |

**Key lifecycle:**
1. **Created:** When the first pick is added to a session (`saveToLocal()`). The timestamp key is also written at this time.
2. **Updated:** Every time a pick is added, removed, or modified. The timestamp updates on every save.
3. **Removed:** On successful batch submission (`clearLocal()`). All three keys are explicitly removed.
4. **Auto-cleaned:** The dashboard cleanup sweep removes all three keys if the timestamp is older than 7 days.

**Migration support:** Pre-v1.10.0 keys used the format `twg_picks_<SO>` (no user prefix). Both `picking.js` and `dashboard.html` contain migration logic that detects old-format keys, moves their data to the current user's namespace, and removes the old keys. This is a one-time operation per key.

---

## Pending Picks Dashboard Notification (v1.10.0+)

When a picker has unsubmitted picks in localStorage, the dashboard displays a prominent amber warning banner:

**Detection flow (runs on every dashboard page load):**
1. Reads the current user ID from the Flask session (injected via Jinja).
2. Runs the 7-day cleanup sweep to remove stale data (see below).
3. Migrates any old-format (non-user-scoped) keys to the current user's namespace.
4. Scans all localStorage keys matching `twg_picks_<USER>_*`.
5. Parses each key's JSON value and filters for non-empty arrays.
6. Reads the corresponding timestamp key (`twg_picks_ts_<USER>_<SO>`) for display.
7. Builds and injects a resume banner with clickable cards for each pending SO.

**Banner details per SO:**
- Sales order number
- Number of scan entries
- Total quantity across all picks
- Timestamp of last save (e.g., "Saved Mar 13, 2:30 PM") — shown only if the timestamp key exists

Tapping a card navigates to `/picking?so=<SO>` where the picks are automatically restored from localStorage.

---

## localStorage Cleanup Sweep (v1.11.0)

To prevent localStorage bloat on shared devices that accumulate abandoned pick sessions, the dashboard runs an automatic cleanup sweep on every page load:

**How it works:**
1. Reads the current user ID.
2. Takes a snapshot of all localStorage keys (to avoid index-shifting during iteration).
3. Scans for timestamp keys matching `twg_picks_ts_<USER>_*`.
4. For each timestamp key, parses the ISO 8601 value and computes the age.
5. If the age exceeds **7 days**, all three keys for that SO are removed (picks, batch ID, timestamp).
6. Invalid/unparseable timestamps are treated as stale and removed immediately.

**Design decisions:**
- Runs **before** the pending picks scan so stale entries never appear in the resume banner.
- Uses the snapshot-then-iterate pattern to avoid index-shifting when `localStorage.removeItem()` is called during the loop.
- Only cleans the **current user's** data — other users' keys are untouched.
- The 7-day threshold is configurable via the `STALE_DAYS` constant.

---

## Order Progress Bar (v1.11.0)

A thin progress bar sits between the order header and the picking grid, providing real-time visual feedback on picking completion:

**Appearance:**
- Grey background track with a colored fill bar and a text label (e.g., "12 of 25 qty - 48%").
- Fill color: grey (0%), blue (1-99%), green (100%).
- Smooth CSS transition on width changes (0.3s ease).

**How it works:**
1. `updateProgressBar()` is called at the end of every `updateSessionDisplay()` invocation.
2. Reads the total needed quantity by summing the "Need" column cells from the order grid DOM.
3. Computes total picked from the `sessionPicks` array.
4. Calculates percentage (capped at 100%) and updates the fill width and label text.

**Edge cases handled:**
- If the progress bar DOM elements don't exist (e.g., on the SO entry page), the function is a no-op.
- Division by zero is avoided — if `totalNeeded` is 0, percentage defaults to 0.
- The bar is hidden via CSS when the virtual keyboard is open (`.tc52-layout.keyboard-open #orderProgressBar { display: none; }`) to maximize screen space.

---

## Leave-Page Confirmation Guard (v1.11.0)

Prevents accidental loss of unsubmitted picks when navigating away from the picking screen:

### `onclick` Guard (`guardNavigation()`)

Applied to the **Exit** button and the **Change** (SO) link. When clicked:

1. If `sessionPicks` is empty, allows normal navigation (returns `true`).
2. If picks exist, cancels the default click (returns `false`), shows a TWG-branded confirm dialog: "You have X unsubmitted pick(s). Leave without submitting?"
3. If the picker confirms, navigates programmatically via `window.location.href`.
4. If the picker cancels, stays on the current page.

### `beforeunload` Guard

A safety net for browser back button, page refresh, or URL changes:

1. Listens to the `window.beforeunload` event.
2. If `sessionPicks.length > 0`, triggers the browser's native "Leave page?" dialog.
3. Does **not** false-trigger after a successful submit because `clearLocal()` empties `sessionPicks` before `location.reload()`.

---

## Picker Assignment Soft-Check (v1.11.0)

When loading an order that is assigned to a different picker, a dismissible amber warning banner appears:

**Server-side (`app.py`):**
- The `picker` value is read from `SOMAST` during order validation and passed to the template as `assigned_picker`.
- The variable `picker_val` is initialized to `''` before the conditional block to ensure it's always defined, even on early-return code paths.

**Template (`picking.html`):**
- Jinja condition: `{% if assigned_picker|default('') and assigned_picker.strip().upper() != session['user_id'].strip().upper() %}`
- Uses `|default('')` as a defensive filter in case `assigned_picker` is not passed by early-return paths in the Flask route.
- Displays: "Assigned to **JOHN**, not you (**QUINN**)"
- A **Continue** button dismisses the banner by setting `display: none` — it does not block picking.

**Element order in the `{% else %}` block:**
Header -> Picker Warning Banner (conditional) -> Progress Bar -> Grid -> Context Bar -> Controls

---

## Short-Pick Exception Workflow

When the user taps **Submit**, the system checks whether any order lines were only partially picked (picked > 0 but less than the "Need" quantity). If partial picks are detected:

1. The **Exception Modal** opens, listing each short-picked line with its item code, needed quantity, and picked quantity.
2. The picker **must** select a reason code from a dropdown for every short-picked line before they can submit. Available codes:
   - `SHORT` — Short Pick (Not enough in bin)
   - `DMG` — Damaged (Found, unpickable)
   - `NOFND` — No Find (Bin empty/Missing)
   - `BADLC` — Wrong Location (Inventory mismatch)
3. Once all reasons are selected, the picker taps **Confirm & Submit Batch**.
4. Exception codes are sent to the server in the `exceptions` object and written to the `scanresult` column in `ScanBinTran2` for each corresponding line.

If all lines are fully picked (or no picks exist for some lines), the exception modal is skipped and a standard confirmation dialog appears.

### Zero Pick Workflow

The Zero Pick workflow allows pickers to formally report that they could not find **any** stock for an order line. This creates a full audit trail for unfulfillable lines without requiring a bin scan or item scan.

**Picker flow:**

1. Select the row they cannot find stock for.
2. Tap the red **"X Zero Pick"** button (located next to the Bins button in the controls area).
3. The Zero Pick modal opens, showing the line number, item code, and needed quantity.
4. The picker **must** select one of two reason codes:
   - `NOFND` — No Find (Bin empty / Missing)
   - `DMG` — Damaged (Found, all unpickable)
5. Tap **"Confirm Zero Pick"**.
6. The line is added to the session as a zero-qty entry and the order grid row is **greyed out and locked** (40% opacity, `pointerEvents: none`).

**Why only two reason codes:** Zero Pick means the picker found nothing at all for the line. "Short Pick" and "Wrong Location" are excluded because they imply the picker found *some* stock — those scenarios are handled by the short-pick exception modal at submit time.

**Row lockout behavior:**

Once a line has a Zero Pick, it is visually greyed out in the order grid and cannot be tapped or interacted with. This prevents accidental double-handling. The lockout is enforced at three levels:

- **Visual:** Row opacity drops to 40% with a `zero-picked-row` CSS class.
- **Pointer events:** `pointerEvents: none` on the row element blocks all tap/click events.
- **JavaScript guard:** `selectRow()` checks `isZeroPickedLine()` and rejects the interaction with a toast message if somehow triggered.

**Restoring a locked row:**

The only way to undo a Zero Pick is through the **Review modal** (View button):

- Tap the **X** button next to the zero-pick entry to remove it, or
- Tap **Clear All** to remove all session picks.

Both actions call `refreshZeroPickRows()` which scans the current `sessionPicks` and restores any rows that no longer have a zero-pick entry to their normal interactive state.

**Page reload persistence:**

On page load, after restoring `sessionPicks` from `localStorage`, `refreshZeroPickRows()` runs to re-apply the greyed-out state to any zero-picked rows. This ensures the lockout survives browser refreshes and accidental navigation.

**Integration with the submit workflow:**

When the picker taps Submit, zero-pick entries are handled seamlessly:

- `mergePicksForCommit()` passes zero-pick entries through individually (they are not merged with normal picks).
- `checkExceptionsAndSubmit()` collects exception codes already embedded in zero-pick entries and excludes those lines from the short-pick detection. This means zero-picked lines will never trigger the short-pick exception modal.
- If the batch has both zero picks and short picks from other lines, both sets of exceptions are merged into a single `exceptions` dict before submission.
- On the server, zero-qty picks skip inventory updates (`ScanOnhand2`) and sales order updates (`SOTRAN`) but still write an audit row to `ScanBinTran2` with `quantity=0` and the exception code in `scanresult`.

### IC Bin Report Workflow

The IC (Inventory Control) Bin Report workflow allows pickers to flag any bin for investigation by the IC team without interrupting their picking flow. Reports are sent via email in the background.

**Picker flow:**

1. Select an order line (to establish which item they're looking at).
2. Tap the **"Bins"** button to open the Available Bins modal.
3. Each bin row in the modal has a flag button in the rightmost "IC" column.
4. Tap the flag on the bin they want to report.
5. The **Bin Report Modal** opens, pre-filled with bin location, item code, on-hand, allocated, and available quantities.
6. The picker **must** select an issue type from the dropdown (see list above).
7. Optionally add notes (up to 500 characters) describing the issue.
8. Tap **"Submit Report to IC"**.
9. The modal closes, a green success toast confirms the report, and the picker can immediately continue picking.

**Behind the scenes:**

- The client sends a `POST` to `/report_bin` with the bin details, selected reason, notes, and the current SO number.
- The server responds instantly with a success message.
- A background daemon thread connects to Office 365 SMTP and sends a professional HTML email to all recipients listed in `IC_EMAIL`.
- A plain-text fallback is included for email clients that don't render HTML.
- SMTP failures are logged at `ERROR` level but never surface to the picker.

**Non-disruptive design:** The bin report feature is entirely independent of the picking workflow. It does not modify any database tables, does not affect session picks, does not block the UI, and does not require the picker to leave their current screen. The background thread ensures SMTP latency (typically 1-3 seconds) never delays the picker's response.

### Bin Cache (`picking.js`)

When a row is selected, bins are pre-fetched via `/get_item_bins` and cached in `binCache[itemCode]`. Subsequent bin validations check the cache first before making a server call. The cache is per-item and lasts for the page session.

### UI Feedback

- **Active Row Highlight:** Selected order line turns yellow with a gold bottom border.
- **Flash Effects:** Quantity input flashes green on successful add.
- **Toast Notifications:** Success (green, 2-second display) and error (red, 4-second display) banners appear at the top of the screen with auto-dismiss and fade-out. Audio beeps accompany toasts unless explicitly suppressed.
- **Audio Beeps:** Success beep (1500Hz sine, 150ms) and error beep (150Hz sawtooth, 400ms) via the Web Audio API. Audio context is unlocked on the first user interaction.
- **Pending Badge:** Status bar shows the count of unsubmitted picks.
- **Progress Bar:** Real-time visual indicator of overall order completion (see Order Progress Bar section).
- **Disabled Controls:** All scan inputs and buttons are greyed out and disabled until a row is selected (prevents accidental picks without a target).

### Custom Branded Dialogs (`picking-ui.js`)

All confirmation and alert dialogs use custom-branded modals instead of the browser's native `alert()` and `confirm()`. This displays **"TWG WMS App"** as the dialog header instead of the server's IP address.

- **`twgAlert(message)`** — Shows a branded dialog with an OK button. Returns a Promise that resolves when OK is tapped.
- **`twgConfirm(message)`** — Shows a branded dialog with Cancel and OK buttons. Returns a Promise that resolves `true` (OK) or `false` (Cancel).

Both functions are async/Promise-based. All calling functions (`checkExceptionsAndSubmit`, `removePick`, `clearSession`, `executeSubmit`, `confirmExceptionsAndSubmit`, `guardNavigation`) use `await` or `.then()` accordingly.

### Modals

- **Bin Modal:** Shows all available bins for the selected item with on-hand, allocated, available quantities, and an IC report flag per bin row. Bins are filtered client-side using `isValidBin()`. Closeable via the X button **or by tapping the dark overlay area** outside the modal. On close, focus automatically returns to the Scan Bin input via `safeFocus('binInput')`.
- **Bin Report Modal:** Shows pre-filled bin details with a required issue type dropdown and optional notes textarea. Opened by tapping the flag in the Bin Modal. On submit, sends report in background and shows success toast. Closeable via X button or overlay tap.
- **Review Modal:** Shows all current session picks with item, bin, quantity, mode badge (Auto/Manual), and a remove button per entry. Zero-pick entries are rendered with a red background, "---" for bin, "0" for quantity, and a red exception badge (e.g., `NOFND`) instead of the mode badge. Includes a "Clear All" option. Closeable via X button or overlay tap.
- **Exception Modal:** Shows short-picked lines with required reason code dropdowns. Closeable via X button or overlay tap. Submission is blocked until all reason codes are selected.
- **Zero Pick Modal:** Shows the selected line's item code and needed quantity with a reason code dropdown (NOFND or DMG only). Closeable via X button or overlay tap. Confirmation is blocked until a reason is selected. On confirm, adds a zero-qty entry to the session and locks the corresponding order grid row.
- **Custom Dialog (twgAlert/twgConfirm):** Dynamically created branded overlay for all confirmation and alert messages. Displays "TWG WMS App" header with dark theme.

### Fullscreen Management (`utils.js`)

The application aggressively maintains fullscreen mode for the warehouse environment:

1. On DOM ready, attaches a one-time listener to the first touch/click to enter fullscreen.
2. Monitors fullscreen exit events (e.g., accidental swipe) and re-attaches the enter listener.
3. Dashboard includes a manual fullscreen toggle button.
4. PWA standalone mode is detected and skips fullscreen API calls.
5. Login page overrides the global `enterFullscreen()` to suppress fullscreen when input fields are focused (prevents keyboard conflicts).

---

## Location Filtering Logic

Location-based filtering is applied consistently across all data queries:

- **Location `'000'`:** Treated as all-access. No location filter is applied.
- **Location `'Unknown'`:** No location filter is applied (fallback).
- **Any other location:** A `LIKE` prefix match is applied (e.g., location `'100'` matches `'100'`, `'100A'`, `'100-B'`, etc.).

This applies to: order line fetching (`/picking`), bin stock queries (`/get_item_bins`), bin validation (`/validate_bin`), and inventory updates (`/process_batch_scan` uses exact `=` match for the UPDATE).

---

## Data Cleaning

The application applies aggressive whitespace handling throughout:

- **Item codes:** Stripped on read from both `SOTRAN` and `ScanItem` tables. The UPC mapping uses stripped item codes as dictionary keys to ensure consistent matching.
- **UPC values:** `None` values are converted to empty strings. All UPC strings are stripped before comparison.
- **Bin values:** Stripped on read from `ScanOnhand2`.
- **Location values:** Stripped on read from both `ScanUsers` and `ScanOnhand2`.
- **User ID:** Stripped and uppercased on login input.
- **SO Number:** Resolved using `LIKE` match to handle leading-space padding in the database.
- **Exception codes:** Truncated to max 10 characters before database insert to prevent column overflow.
- **Bin report notes:** Truncated to max 500 characters before processing to prevent abuse.

---

## Email System Architecture

The bin report email system is designed for zero-disruption to the picker workflow:

```
Picker taps flag -> Client POST /report_bin -> Flask validates & responds 200 -> Toast shown
                                             |  (background)
                                             v
                                      threading.Thread(daemon=True)
                                             |
                                             v
                                      smtplib.SMTP -> Office 365 STARTTLS
                                             |
                                             v
                                      Email delivered to IC_EMAIL recipients
```

**Key design decisions:**

- **Background thread:** SMTP connections take 1-3 seconds. Running in a daemon thread means the picker's HTTP response returns in ~50ms regardless of email delivery time.
- **Daemon mode:** The thread is marked `daemon=True` so it will not prevent the Flask process from shutting down during restarts.
- **No retry logic:** If the SMTP connection fails (e.g., Office 365 is temporarily unreachable), the email is lost and an `ERROR` log is written. This is intentional — bin reports are informational, not transactional, and a retry queue would add complexity without proportional value.
- **No database write:** Bin reports are not stored in the database. The email is the sole record. If persistent storage is needed in the future, a `BinReports` table could be added.
- **HTML + plain text:** The email includes both `text/html` and `text/plain` MIME parts. Email clients that render HTML see the branded layout; plain-text clients see a structured text fallback.
- **Multiple recipients:** The `IC_EMAIL` config value is split on commas at send time. Adding or removing recipients requires only an `.env` change — no code deployment needed.

---

## Error Handling Summary

| Layer | Mechanism | Behavior |
|-------|-----------|----------|
| DB Connection | `get_db_connection()` returns `None` | Routes flash "Database Offline" or return JSON error |
| Login | Try/catch around query | Flashes specific error to login form |
| Picker Validation | `SOMAST.picker` check | Rejects order if no picker assigned |
| Picking query | Try/catch with `finally: conn.close()` | Flashes database error to picking page |
| Batch pre-check | `raise Exception(...)` | Entire transaction is rolled back, error returned to client |
| Batch SQL guard | `rowcount == 0` check | Entire transaction is rolled back, error returned to client |
| Batch post-check | Try/catch, `logging.critical()` | Warnings logged and included in response, no rollback |
| Client network | `fetch().catch()` | TWG-branded alert shown to user, submit button re-enabled |
| Client guards | Bin limit / Order limit checks | Toast error shown, pick rejected before reaching server |
| Navigation guard | `guardNavigation()` + `beforeunload` | Branded confirm dialog prevents accidental data loss |
| Zero-pick duplicate guard | `isZeroPickedLine()` check | Toast error if line already has a Zero Pick entry |
| Zero-pick conflict guard | Normal picks exist check | Toast error if line already has qty > 0 picks (use short-pick modal instead) |
| Zero-pick row lockout | `selectRow()` early exit | Toast error and interaction blocked on greyed-out rows |
| Exception validation | Dropdown required for short picks | TWG-branded alert blocks submission until all reasons selected |
| Bin report validation | Reason required, notes truncated | TWG-branded alert if no reason selected; notes capped at 500 chars |
| Bin report email | Background thread try/catch | `logging.error()` on SMTP failure; picker always gets success response |
| Stale data cleanup | 7-day threshold on timestamp keys | Automatic removal of abandoned pick sessions on dashboard load |

---

## Security Notes

- All SQL queries use **parameterized placeholders** (`?`) to prevent SQL injection.
- Database connections use `autocommit=False` with explicit `commit()` or `rollback()`.
- Flask sessions are signed with `SECRET_KEY`.
- Connection timeout is set to 15 seconds.
- Passwords are stored and compared as plain text in `ScanUsers` (legacy system constraint).
- Exception codes are truncated server-side to max 10 characters to prevent injection via oversized values.
- Bin report notes are truncated server-side to max 500 characters to prevent abuse.
- SMTP credentials are stored in `.env` (excluded from version control via `.gitignore`).
- The `APP_VERSION` cache-buster is not a security feature — it exists purely for cache invalidation.
- localStorage keys are user-scoped to prevent cross-user data visibility on shared devices.
- Navigation guards prevent accidental loss of unsubmitted work.

---

## JavaScript Function Reference

### `utils.js`

| Function | Purpose |
|----------|---------|
| `generateUUID()` | Creates a UUID using `crypto.randomUUID()` with fallback |
| `getDeviceId()` | Returns or generates a persistent device ID in localStorage |
| `log(msg)` | Writes timestamped message to debug console and `console.log` |
| `toggleDebug()` | Shows/hides the on-screen debug console |
| `isPWAStandalone()` | Detects if running as an installed PWA |
| `isFullscreen()` | Checks current fullscreen state across browser prefixes |
| `enterFullscreen()` | Requests fullscreen on `document.documentElement` |
| `exitFullscreen()` | Exits fullscreen mode |
| `autoEnterFullscreen()` | Attaches one-time listener to enter fullscreen on first user gesture |
| `watchFullscreenExit()` | Re-enters fullscreen if accidentally exited |
| `forceFullscreen()` | Legacy compat — enters fullscreen if not already active |
| `unlockAudio()` | Resumes suspended AudioContext (required for mobile browsers) |
| `playBeep(type)` | Plays success (1500Hz sine) or error (150Hz sawtooth) beep |

### `picking-ui.js`

| Function | Purpose |
|----------|---------|
| `updateStatusUI(online)` | Updates the status bar to show online/offline state |
| `updateSessionDisplay(sessionPicks)` | Refreshes pick counts in the grid, pending badge, and progress bar |
| `updateProgressBar(sessionPicks)` | Calculates and renders the order progress bar fill and label |
| `showToast(msg, type, playSound)` | Displays a timed notification banner (error: 4s, success: 2s) |
| `isValidBin(binStr)` | Client-side bin validation (15 chars, numeric 5th character) |
| `renderBinList(bins)` | Renders the bin modal table with stock levels and IC report flags |
| `renderReviewList(sessionPicks)` | Renders the review modal table with mode badges; zero-pick entries render with red background and exception badge |
| `renderExceptionList(shortLines)` | Renders the exception modal with reason code dropdowns |
| `openModal(id)` | Shows a modal overlay by ID |
| `closeModal(id)` | Hides a modal overlay by ID; returns focus to binInput if closing bin modal |
| `openBinReportModal(bin, onhand, alloc, avail)` | Opens the bin report modal pre-filled with bin details for IC reporting |
| `submitBinReport()` | Validates reason selection, POSTs to `/report_bin`, shows success/error toast |
| `twgAlert(message)` | Branded alert dialog (async, returns Promise) |
| `twgConfirm(message)` | Branded confirm dialog (async, returns Promise resolving true/false) |

**Modal close behavior:** All modals (bin, review, exception, zero pick, bin report) can be closed by tapping the dark overlay area outside the modal content, in addition to the X button. The bin modal specifically returns focus to the Scan Bin input on close.

### `picking.js`

| Function | Purpose |
|----------|---------|
| `picksKey(so)` | Returns the user-scoped localStorage key for picks: `twg_picks_<USER>_<SO>` |
| `batchKey(so)` | Returns the user-scoped localStorage key for batch ID: `twg_batch_id_<USER>_<SO>` |
| `tsKey(so)` | Returns the user-scoped localStorage key for timestamp: `twg_picks_ts_<USER>_<SO>` |
| `migrateOldLocalKeys()` | One-time migration from old non-user-scoped keys to new format |
| `isVirtualKeyboardActive(el)` | Detects virtual keyboard by checking `inputMode` |
| `stripWrappingAlpha(str)` | Strips DataWedge symbology wrapping from UPC scans |
| `attachScannerListeners()` | Binds keydown/input listeners to all scan inputs |
| `handleAction(el)` | Routes input action to the correct handler based on element ID |
| `selectRow(row, itemCode, remainingQty, lineNo, upc)` | Selects an order line, enables controls, prefetches bins |
| `validateBin()` | Validates scanned bin against cache or server |
| `verifySuccess(qty, bin)` | Stores bin context and advances focus to item input |
| `addToSession()` | Adds a pick to the session with deduplication and guard checks |
| `resetInputAfterAdd(success)` | Clears item input (Auto) or resets qty (Manual) after add |
| `handleItemScan()` | Matches scanned value against item code or UPC |
| `showUpcBadge(upcValue, itemCode)` | Shows the UPC translation badge with animation |
| `hideUpcBadge()` | Hides the UPC translation badge |
| `escapeHtml(str)` | Safely escapes HTML entities in a string |
| `mergePicksForCommit(picks)` | Aggregates Auto+Manual picks into single records per line/bin/item |
| `checkExceptionsAndSubmit()` | Entry point for submit — detects short picks, opens exception modal or confirms |
| `confirmExceptionsAndSubmit()` | Collects exception codes from modal and proceeds to submit |
| `executeSubmit(commitPicks, exceptions)` | Sends the final batch to `/process_batch_scan` |
| `resetSubmitBtn(btn, txt)` | Re-enables submit button after error |
| `saveToLocal()` | Persists session picks and timestamp to localStorage |
| `loadFromLocal()` | Restores session picks from localStorage |
| `clearLocal()` | Removes all localStorage data (picks, batch ID, timestamp) for the current SO |
| `guardNavigation(linkEl)` | Intercepts link clicks, shows confirm dialog if unsaved picks exist |
| `updateMode()` | Toggles between Auto and Manual mode UI states |
| `openBinModal()` | Opens the bin modal and triggers bin prefetch |
| `prefetchBins(item)` | Fetches and caches bin data from `/get_item_bins` |
| `openReviewModal()` | Opens the review modal with current session picks |
| `removePick(i)` | Removes a single pick entry after TWG-branded confirmation; refreshes zero-pick row locks |
| `clearSession()` | Clears all picks after TWG-branded confirmation; refreshes zero-pick row locks |
| `openZeroPickModal()` | Opens the Zero Pick modal for the currently selected line; blocks if line already has a zero pick or normal picks |
| `confirmZeroPick()` | Validates reason code selected, pushes zero-qty entry to sessionPicks, locks the order grid row |
| `isZeroPickedLine(lineNo)` | Returns true if the given line number has a Zero Pick entry in sessionPicks |
| `lockZeroPickRow(lineNo)` | Greys out an order grid row (40% opacity, pointerEvents disabled) after a Zero Pick |
| `unlockZeroPickRow(lineNo)` | Restores an order grid row to normal interactive state |
| `refreshZeroPickRows()` | Scans sessionPicks and applies/removes row locks; called on page load, removePick, and clearSession |
| `toggleKeyboard(id)` | Toggles virtual keyboard visibility on an input |
| `safeFocus(id)` | Focuses an input with `inputMode='none'` to prevent keyboard popup |
| `adjustQty(n)` | Increments/decrements the quantity input in Manual mode |

---

## Complete Picker Workflow (End-to-End)

1. **Login** — Picker scans or types their user ID and password on the TC52. The app authenticates against `ScanUsers`, stores the session, and redirects to the dashboard.

2. **Dashboard** — Shows the main menu with a live clock. If unsubmitted picks exist in localStorage, an amber banner appears with resume links. The cleanup sweep silently removes any pick data older than 7 days.

3. **Enter SO** — Picker taps "Order Pick" and scans/types a 7-digit sales order number. The app validates the order exists and has an assigned picker.

4. **Picker Warning** — If the order is assigned to a different picker, an amber warning banner appears. The picker can tap "Continue" to dismiss it and proceed.

5. **Select Item** — Picker taps a row in the order grid. The row highlights yellow, controls become active, and bins are pre-fetched.

6. **Scan Bin** — Picker scans a bin barcode. The app validates the bin contains the selected item with available stock.

7. **Scan Item** — Picker scans the item barcode. The app matches it against the item code or UPC. A translation badge appears for UPC matches.

8. **Add Pick** — In Auto mode, the pick is added automatically (qty 1). In Manual mode, the picker adjusts quantity and taps ADD. The progress bar updates in real-time.

9. **Repeat** — Steps 5-8 repeat for each item/bin combination. The session is saved to localStorage on every change.

10. **Zero Pick** (optional) — For items that cannot be found, the picker taps "Zero Pick", selects a reason, and the line is locked out.

11. **Report Bin** (optional) — For bins with issues, the picker opens the bins modal, taps the flag icon, fills out the report form, and an email is sent to IC.

12. **Submit** — Picker taps Submit. If any lines are short-picked, the exception modal collects reason codes. A branded confirm dialog shows the pick count. On confirmation, the batch is sent to the server.

13. **Server Commit** — The 6-phase transactional pipeline validates, updates inventory, updates the sales order, writes the audit log, and verifies post-commit. On success, localStorage is cleared and the page reloads.

14. **Navigation Protection** — At any point, if the picker tries to exit or change orders with unsaved picks, a branded dialog warns them. The browser's native "Leave page?" dialog is also active as a safety net.

---

## Version History

| Version | Changes |
|---------|---------|
| **1.11.0** | Order progress bar, leave-page confirmation guard, picker assignment soft-check, localStorage timestamp tracking, 7-day stale data cleanup sweep, `clearLocal()` orphaned keys bugfix |
| **1.10.0** | Pending picks dashboard notification, user-scoped localStorage keys (cross-user fix), old-key migration logic, APP_VERSION cache-busting for PWA |
| **1.8.0** | IC Bin Reporting via email, bin report modal, background SMTP threading, multi-recipient support |
| **1.7.0** | Zero Pick workflow, row lockout system, exception code integration |
| **1.6.0** | Short-Pick exception modal, reason code dropdowns, `scanresult` audit column |
| **1.5.0** | Batch scanning with 6-phase transactional commit, SQL-level guards, post-commit verification |
| **1.4.0** | UPC translation badge, DataWedge symbology stripping |
| **1.3.0** | Custom branded dialogs (twgAlert/twgConfirm), keyboard-aware viewport |
| **1.2.0** | Manual pick mode, quantity adjustment controls |
| **1.1.0** | Bin validation, bin cache, bin modal with stock levels |
| **1.0.0** | Initial release — login, dashboard, basic picking with auto mode |
