# TWG Warehouse Scanner (Web App)

## Project Status

**Phase:** 3 — Batch Scanning with Hardened Commit Logic
**Current Mode:** LIVE COMMIT MODE — The application validates all logic (inventory availability, order limits, location checks) and performs live SQL `UPDATE` and `INSERT` operations against the database. All writes are wrapped in a single transaction with automatic rollback on any failure.

---

## Tech Stack

- **Backend:** Python 3 (Flask)
- **Database:** Microsoft SQL Server (via `pyodbc`)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (ES6)
- **Target Device:** Zebra TC52 (Mobile Viewport, Portrait Orientation)
- **PWA Support:** Web App Manifest with fullscreen display mode

---

## Project Structure

```
├── app.py                  # Flask application — all routes and business logic
├── config.py               # Environment variable loader and app configuration
├── requirements.txt        # Python dependencies (flask, pyodbc, python-dotenv)
├── static/
│   ├── css/
│   │   ├── style.css       # Global styles, layout system, table, modal, buttons
│   │   └── picking.css     # Picking-specific styles, keyboard-aware layout
│   ├── js/
│   │   ├── utils.js        # Shared utilities: UUID, audio, fullscreen, logging
│   │   ├── picking.js      # Core picking logic: state, scanning, validation, submission
│   │   └── picking-ui.js   # UI rendering: toasts, modals, bin list, review list
│   └── manifest.json       # PWA manifest for home screen install
├── templates/
│   ├── login.html          # User authentication screen
│   ├── dashboard.html      # Main menu with clock and app grid
│   └── picking.html        # Order picking interface (SO entry + pick screen)
└── readme.md               # This file
```

---

## Configuration

### Environment Variables (`.env`)

```ini
SECRET_KEY=your_flask_secret_key
DB_DRIVER={ODBC Driver 17 for SQL Server}
DB_SERVER=YOUR_SERVER_IP
DB_UID=YOUR_USER
DB_PWD=YOUR_PASSWORD
DB_AUTH=PRO12       # Database for Inventory, Users, Audit (ScanOnhand2, ScanUsers, ScanBinTran2, ScanItem)
DB_ORDERS=PRO05     # Database for Sales Orders (SOTRAN)
```

### Config Class (`config.py`)

The `Config` class loads all values from environment variables with fallback defaults. Two database references are maintained separately:

- `DB_AUTH` — Used for inventory tables (`ScanOnhand2`), user authentication (`ScanUsers`), UPC mapping (`ScanItem`), and audit logging (`ScanBinTran2`).
- `DB_ORDERS` — Used exclusively for the sales order table (`SOTRAN`).

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
| `scanresult` | Empty string | Reserved for future use |

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
2. The **5th character** (index 4) must be **numeric** (0–9).

This filters out non-standard bin codes (e.g., `000-PK-0-0` for packing stations) that should not appear in pick workflows. The validation is applied in three places:

- **Server-side** in `/get_item_bins` — filters query results before returning to client.
- **Client-side** in `picking-ui.js` (`isValidBin()`) — filters the bin list modal display.
- **Server-side** in `is_valid_bin()` — reusable Python helper function.

---

## API Endpoints

### `GET /health`

Returns server status and current timestamp. Used for uptime monitoring.

**Response:** `{ "status": "online", "time": "2026-02-19T08:00:00" }`

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

Renders the main menu with a live clock, user info, and app grid. Only the "Order Pick" module is currently active. Requires an active session.

### `GET /picking?so=<order_number>`

Fetches and displays order lines for picking. This endpoint handles two states:

**State 1 — No SO provided:** Renders the Sales Order input screen where the user scans or types a 7-digit SO number.

**State 2 — SO provided:** Queries the order and renders the picking grid.

**Process:**
1. Resolves the SO number using a `LIKE` match (handles leading spaces in the database).
2. Fetches open order lines from `SOTRAN` where `qtyord > shipqty` and `stkcode = 'Y'`.
3. Filters by user location unless the user is assigned to location `'000'` (all-access) or `'Unknown'`.
4. Fetches UPC mappings from `ScanItem` for all unique items in the order.
5. Strips whitespace from all item codes and UPC values during mapping.
6. If no open lines remain, flashes a "fully picked" success message.

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
  "batch_id": "uuid-string"
}
```

**The commit process follows 6 sequential phases:**

---

#### Phase 1: Pre-Aggregate Line Totals

Before any database reads, picks are aggregated by `tranlineno`. Multiple picks for the same order line (e.g., from different bins) are summed into a single quantity per line. This aggregated total is used for the SOTRAN over-ship validation.

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

One row is inserted per pick (not per aggregated line) to maintain full granularity of which bin each unit came from.

```sql
INSERT INTO ScanBinTran2
(actiontype, applid, udref, tranlineno, upc, item, binfr, quantity, userid, deviceid, adddate, scanstat, scanresult)
VALUES ('SP', 'SO', ?, ?, ?, ?, ?, ?, ?, '', GETDATE(), '', '')
```

---

#### Phase 6: Post-Commit Verification (Read-Only)

After `conn.commit()` succeeds, the application performs read-only verification to confirm the data landed correctly. **This phase never triggers a rollback** — the data is already committed. Failures are logged at `CRITICAL` level for manual review.

**SOTRAN shipqty verification:**
For each updated order line, the application re-reads `shipqty` and compares it to the expected value (pre-update value + aggregated pick quantity). A mismatch indicates a concurrent modification occurred between the pre-read and the commit.

If any post-commit warnings are generated, they are included in the response and logged, but the response status remains `'success'` since the transaction was committed.

---

#### Error Handling

- Any exception in Phases 1–5 triggers `conn.rollback()` and returns `{ "status": "error", "msg": "..." }`.
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
3. When open: adds `keyboard-open` class, sets explicit layout height, hides footer buttons, shows a context bar with the currently selected item info.
4. When closed: resets layout to full screen.
5. Recalculates baseline height on orientation changes and fullscreen state changes.

### Scanner Input Handling (`picking.js`)

The application supports both hardware barcode scanners (Zebra TC52) and manual keyboard input.

**Hardware scanner detection:** Hardware scanners inject text with `inputMode='none'` and fire rapidly. The `isVirtualKeyboardActive()` function checks `el.inputMode` to distinguish between scanner and keyboard input.

**Auto-trigger logic:**
- **Scanner input:** Auto-triggers action after 300ms debounce when input length > 5 characters.
- **Virtual keyboard input:** Waits for the user to press Enter (no auto-trigger to prevent premature submission while typing).
- **SO Input:** Auto-submits when exactly 7 digits are detected (after trimming).

**Input flow:**
1. **Select Row** → User taps an order line in the grid. Controls are enabled, bin input is focused.
2. **Scan Bin** → Validates bin against `ScanOnhand2` (uses cache if available, otherwise calls `/validate_bin`). On success, focuses item input.
3. **Scan Item** → Compares scanned value against the selected item code and its UPC (case-insensitive). On mismatch, shows error and clears input.
4. **Add to Session** → In Auto mode, automatically adds quantity of 1 after successful item scan. In Manual mode, user adjusts quantity and clicks ADD.

### Pick Modes

- **Auto Mode** (default): Quantity is fixed at 1. Each successful item scan immediately adds to the session. Designed for single-unit picks with a hardware scanner.
- **Manual Mode**: Quantity input is editable with +/- buttons. User must click ADD after scanning. Designed for bulk picks.

### Session Management (`picking.js`)

Picks are stored in a local `sessionPicks` array and persisted to `localStorage` under keys prefixed with the SO number (`twg_picks_<SO>`). This survives page refreshes and accidental navigation.

**Session pick structure:**
```javascript
{ id: timestamp, lineNo: 1, item: "ITEM1", bin: "BIN_CODE", qty: 5 }
```

**Deduplication:** If a pick already exists for the same `lineNo + bin + item`, the quantity is incremented rather than creating a duplicate entry.

**Guards (client-side):**
- **Bin limit:** Total picked from a bin cannot exceed the on-hand quantity reported during bin validation.
- **Order limit:** Total picked for a line cannot exceed the remaining order quantity (`qtyord - shipqty`).

### Bin Cache (`picking.js`)

When a row is selected, bins are pre-fetched via `/get_item_bins` and cached in `binCache[itemCode]`. Subsequent bin validations check the cache first before making a server call. The cache is per-item and lasts for the page session.

### UI Feedback

- **Active Row Highlight:** Selected order line turns yellow with a gold bottom border.
- **Flash Effects:** Quantity input flashes green on successful add.
- **Toast Notifications:** Success (green) and error (red) banners appear at the top of the screen with auto-dismiss after 2 seconds.
- **Audio Beeps:** Success beep (1500Hz sine, 150ms) and error beep (150Hz sawtooth, 400ms) via the Web Audio API. Audio context is unlocked on the first user interaction.
- **Pending Badge:** Status bar shows the count of unsubmitted picks.
- **Disabled Controls:** All scan inputs and buttons are greyed out and disabled until a row is selected (prevents accidental picks without a target).

### Modals

- **Bin Modal:** Shows all available bins for the selected item with on-hand, allocated, and available quantities. Bins are filtered client-side using `isValidBin()`.
- **Review Modal:** Shows all current session picks with item, bin, quantity, and a remove button per entry. Includes a "Clear All" option.

### Fullscreen Management (`utils.js`)

The application aggressively maintains fullscreen mode for the warehouse environment:

1. On DOM ready, attaches a one-time listener to the first touch/click to enter fullscreen.
2. Monitors fullscreen exit events (e.g., accidental swipe) and re-attaches the enter listener.
3. Dashboard includes a manual fullscreen toggle button.
4. PWA standalone mode is detected and skips fullscreen API calls.

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

---

## Error Handling Summary

| Layer | Mechanism | Behavior |
|-------|-----------|----------|
| DB Connection | `get_db_connection()` returns `None` | Routes flash "Database Offline" or return JSON error |
| Login | Try/catch around query | Flashes specific error to login form |
| Picking query | Try/catch with `finally: conn.close()` | Flashes database error to picking page |
| Batch pre-check | `raise Exception(...)` | Entire transaction is rolled back, error returned to client |
| Batch SQL guard | `rowcount == 0` check | Entire transaction is rolled back, error returned to client |
| Batch post-check | Try/catch, `logging.critical()` | Warnings logged and included in response, no rollback |
| Client network | `fetch().catch()` | Alert shown to user, submit button re-enabled |

---

## Security Notes

- All SQL queries use **parameterized placeholders** (`?`) to prevent SQL injection.
- Database connections use `autocommit=False` with explicit `commit()` or `rollback()`.
- Flask sessions are signed with `SECRET_KEY`.
- Connection timeout is set to 15 seconds.
- Passwords are stored and compared as plain text in `ScanUsers` (legacy system constraint).