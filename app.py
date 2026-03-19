from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_wtf.csrf import CSRFProtect
from config import Config
import pyodbc
pyodbc.pooling = True  # Enable ODBC connection pooling
import logging
import datetime
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import html as html_mod

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)

# --- GLOBAL CACHE ---
DB_COLS = {
    'ScanOnhand2_Loc': None,    # loctid vs terr
    'ScanOnhand2_Alloc': None,  # aloc vs alloc
    'ScanUsers_Loc': None,
    'ScanBinTran2_UPC': False,
    'ScanItem_UPC': False
}

def _build_conn_str():
    return (
        f"DRIVER={app.config['DB_DRIVER']};"
        f"SERVER={app.config['DB_SERVER']};"
        f"DATABASE={app.config['DB_AUTH']};"
        f"UID={app.config['DB_UID']};"
        f"PWD={app.config['DB_PWD']};"
    )

def get_db_connection():
    """Writable connection (autocommit=False) for transaction-based routes."""
    try:
        conn = pyodbc.connect(_build_conn_str(), timeout=15, autocommit=False)
        conn.timeout = 30  # Command timeout: 30s max per query
        return conn
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}")
        return None

def get_readonly_connection():
    """Read-only connection (autocommit=True) — no open transaction, no held locks."""
    try:
        conn = pyodbc.connect(_build_conn_str(), timeout=15, autocommit=True)
        conn.timeout = 15  # Read queries should finish fast
        return conn
    except Exception as e:
        logging.error(f"DB ReadOnly Connection Failed: {e}")
        return None

def row_to_dict(cursor, row):
    columns = [column[0].lower() for column in cursor.description]
    return dict(zip(columns, row))

def detect_columns():
    """Dynamically detects column names to handle schema variations (aloc vs alloc)."""
    if DB_COLS['ScanOnhand2_Loc']: return

    conn = get_readonly_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor()
        
        # 1. Detect Columns in Inventory (ScanOnhand2)
        try:
            cursor.execute(f"SELECT TOP 0 * FROM {Config.DB_AUTH}.dbo.ScanOnhand2 WITH (NOLOCK)")
            cols = [c[0].lower() for c in cursor.description]
            
            # Location Column
            if 'loctid' in cols: DB_COLS['ScanOnhand2_Loc'] = 'loctid'
            elif 'terr' in cols: DB_COLS['ScanOnhand2_Loc'] = 'terr'
            else: DB_COLS['ScanOnhand2_Loc'] = 'terr'
            
            # Alloc Column (aloc vs alloc)
            if 'aloc' in cols: DB_COLS['ScanOnhand2_Alloc'] = 'aloc'
            elif 'alloc' in cols: DB_COLS['ScanOnhand2_Alloc'] = 'alloc'
            else: DB_COLS['ScanOnhand2_Alloc'] = 'aloc'
            
        except Exception as e:
            logging.error(f"Error detecting ScanOnhand2 cols: {e}")

        # 2. Detect Location Column in Users
        try:
            cursor.execute(f"SELECT TOP 0 * FROM {Config.DB_AUTH}.dbo.ScanUsers WITH (NOLOCK)")
            cols = [c[0].lower() for c in cursor.description]
            if 'location_id' in cols: DB_COLS['ScanUsers_Loc'] = 'location_id'
            else: DB_COLS['ScanUsers_Loc'] = 'location'
        except: DB_COLS['ScanUsers_Loc'] = 'location'

        # 3. Check for UPC Column Support
        try:
            cursor.execute(f"SELECT TOP 0 * FROM {Config.DB_AUTH}.dbo.ScanBinTran2 WITH (NOLOCK)")
            cols = [c[0].lower() for c in cursor.description]
            DB_COLS['ScanBinTran2_UPC'] = ('upc' in cols)
        except: DB_COLS['ScanBinTran2_UPC'] = False

    except Exception as e:
        logging.error(f"Column Detection Error: {e}")
    finally:
        conn.close()


def is_valid_bin(bin_value):
    """
    Validates a bin value:
    - Must be exactly 15 characters long
    - The 5th character (index 4) must be numeric (0-9)
    Example valid:   '000-10-00-00-00' (15 chars, 5th char '1' is numeric)
    Example invalid: '000-PK-0-0'     (10 chars, 5th char 'P' is not numeric)
    """
    if not bin_value or len(bin_value) != 15:
        return False
    if not bin_value[4].isdigit():
        return False
    return True


# ===================================================================
# EMAIL HELPER — Sends bin report emails in a background thread
# so the picker's workflow is never blocked by SMTP latency.
# ===================================================================

def send_bin_report_email(report_data):
    """
    Sends a professional bin report email to the IC team via Office 365 SMTP.
    Runs in a background thread — caller does not wait for completion.
    """
    def _send():
        try:
            smtp_server = app.config['SMTP_SERVER']
            smtp_port = app.config['SMTP_PORT']
            smtp_user = app.config['SMTP_USER']
            smtp_password = app.config['SMTP_PASSWORD']
            ic_email_raw = app.config['IC_EMAIL']

            if not smtp_user or not ic_email_raw:
                logging.error("BIN REPORT EMAIL: SMTP_USER or IC_EMAIL not configured.")
                return

            # Support comma-separated recipients (e.g. "a@co.com,b@co.com")
            ic_recipients = [e.strip() for e in ic_email_raw.split(',') if e.strip()]

            # Build subject line (plain text — no HTML escaping needed,
            # but strip any newlines to prevent email header injection)
            def _clean_header(v):
                return str(v).replace('\r', '').replace('\n', ' ').strip()

            subject = (
                f"[IC Action Required] Bin Report — "
                f"{_clean_header(report_data.get('bin', 'N/A'))} | "
                f"{_clean_header(report_data.get('reason', 'Issue Reported'))} | "
                f"Item {_clean_header(report_data.get('item', 'N/A'))}"
            )

            # Escape all user-supplied values to prevent XSS in email clients
            esc = html_mod.escape
            safe = {k: esc(str(v)) for k, v in report_data.items()}

            # Build HTML email body
            timestamp = safe.get('timestamp', esc(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; color: #2d3748; margin: 0; padding: 0; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1a202c; padding: 18px 24px; border-radius: 8px 8px 0 0; }}
        .header h1 {{ color: #ffffff; font-size: 18px; margin: 0; font-weight: 700; letter-spacing: 0.3px; }}
        .header .subtitle {{ color: #a0aec0; font-size: 12px; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}
        .alert-banner {{ background: #fff5f5; border-left: 4px solid #e53e3e; padding: 14px 18px; margin: 0; }}
        .alert-banner .reason {{ color: #c53030; font-weight: 700; font-size: 16px; }}
        .body {{ background: #ffffff; border: 1px solid #e2e8f0; border-top: none; padding: 24px; }}
        .detail-grid {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
        .detail-grid td {{ padding: 10px 14px; border-bottom: 1px solid #edf2f7; font-size: 14px; }}
        .detail-grid .label {{ color: #718096; font-weight: 600; width: 140px; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; vertical-align: top; }}
        .detail-grid .value {{ color: #2d3748; font-weight: 500; }}
        .detail-grid .value.highlight {{ color: #2b6cb0; font-weight: 700; font-size: 16px; }}
        .notes-section {{ background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 16px; margin-top: 8px; }}
        .notes-section .notes-label {{ color: #718096; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
        .notes-section .notes-text {{ color: #4a5568; font-size: 14px; line-height: 1.5; }}
        .footer {{ background: #f7fafc; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; padding: 14px 24px; text-align: center; }}
        .footer p {{ color: #a0aec0; font-size: 11px; margin: 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Bin Inspection Report</h1>
            <div class="subtitle">TWG Warehouse Management System</div>
        </div>

        <div class="alert-banner">
            <span class="reason">⚠️ {safe.get('reason', 'Issue Reported')}</span>
        </div>

        <div class="body">
            <table class="detail-grid">
                <tr>
                    <td class="label">Bin Location</td>
                    <td class="value highlight">{safe.get('bin', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Item Code</td>
                    <td class="value highlight">{safe.get('item', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">On-Hand Qty</td>
                    <td class="value">{safe.get('onhand', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Allocated Qty</td>
                    <td class="value">{safe.get('alloc', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Available Qty</td>
                    <td class="value">{safe.get('avail', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Warehouse</td>
                    <td class="value">{safe.get('location', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Sales Order</td>
                    <td class="value">{safe.get('so', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Reported By</td>
                    <td class="value">{safe.get('picker', 'N/A')}</td>
                </tr>
                <tr>
                    <td class="label">Report Time</td>
                    <td class="value">{timestamp}</td>
                </tr>
            </table>

            {"<div class='notes-section'><div class='notes-label'>Picker Notes</div><div class='notes-text'>" + safe.get('notes', '') + "</div></div>" if safe.get('notes') else ""}
        </div>

        <div class="footer">
            <p>This report was generated automatically by the TWG Warehouse Scanner App.<br>
            Please investigate the reported bin at your earliest convenience.</p>
        </div>
    </div>
</body>
</html>
"""

            # Build the email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = smtp_user
            msg['To'] = ', '.join(ic_recipients)
            msg['Reply-To'] = smtp_user

            # Plain text fallback
            plain_text = (
                f"BIN INSPECTION REPORT\n"
                f"{'=' * 40}\n\n"
                f"Reason:       {report_data.get('reason', 'Issue Reported')}\n"
                f"Bin:          {report_data.get('bin', 'N/A')}\n"
                f"Item:         {report_data.get('item', 'N/A')}\n"
                f"On-Hand:      {report_data.get('onhand', 'N/A')}\n"
                f"Allocated:    {report_data.get('alloc', 'N/A')}\n"
                f"Available:    {report_data.get('avail', 'N/A')}\n"
                f"Warehouse:    {report_data.get('location', 'N/A')}\n"
                f"Sales Order:  {report_data.get('so', 'N/A')}\n"
                f"Reported By:  {report_data.get('picker', 'N/A')}\n"
                f"Report Time:  {timestamp}\n"
            )
            if report_data.get('notes'):
                plain_text += f"\nPicker Notes:\n{report_data.get('notes')}\n"

            plain_text += (
                f"\n{'=' * 40}\n"
                f"Auto-generated by TWG Warehouse Scanner App.\n"
                f"Please investigate the reported bin at your earliest convenience.\n"
            )

            msg.attach(MIMEText(plain_text, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))

            # Send via Office 365 SMTP
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, ic_recipients, msg.as_string())

            logging.info(f"BIN REPORT EMAIL SENT: Bin={report_data.get('bin')}, Item={report_data.get('item')}, Reason={report_data.get('reason')}, Picker={report_data.get('picker')}")

        except Exception as e:
            logging.error(f"BIN REPORT EMAIL FAILED: {e}")

    # Fire and forget — run in background thread
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


# ===================================================================
# DEVICE GATE — Block desktop/laptop browsers from accessing the app.
# This app is designed exclusively for Zebra TC52 handheld scanners
# and mobile devices. Desktop browsers are not supported.
# ===================================================================

MOBILE_KEYWORDS = (
    'mobile', 'android', 'iphone', 'ipad', 'ipod',
    'webos', 'blackberry', 'opera mini', 'iemobile',
    'zebra', 'tc52', 'tc51', 'tc72', 'tc77'
)

def is_mobile_device():
    """
    Returns True if the request comes from a mobile/tablet device.
    Checks the User-Agent header for known mobile keywords.
    Returns False (desktop) if no User-Agent is present or none match.
    """
    ua = request.headers.get('User-Agent', '').lower()
    if not ua:
        return False
    return any(keyword in ua for keyword in MOBILE_KEYWORDS)

@app.before_request
def enforce_mobile_only():
    """
    Blocks all non-mobile devices before any route executes.
    Exceptions:
      - /health — monitoring endpoint, must always be reachable
      - /static/ — Flask's built-in static file serving (needed for unsupported page assets)
    """
    if request.path == '/health':
        return None
    if request.path.startswith('/static/'):
        return None
    if not is_mobile_device():
        return render_template('unsupported.html'), 403


# --- ROUTES ---

@app.route('/health')
def health_check():
    return jsonify({'status': 'online', 'time': datetime.datetime.now().isoformat()})

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    detect_columns()
    if request.method == 'POST':
        user_id_input = request.form['userid'].strip().upper()
        password_input = request.form['password']
        
        conn = get_db_connection()
        if not conn:
            flash("❌ Database Offline. Check Server Connection.", "error")
            return render_template('login.html')
            
        try:
            cursor = conn.cursor()
            sql = f"SELECT * FROM {Config.DB_AUTH}.dbo.ScanUsers WITH (NOLOCK) WHERE userid=? AND pw=?"
            cursor.execute(sql, (user_id_input, password_input))
            row = cursor.fetchone()
            
            if row:
                user = row_to_dict(cursor, row)
                session['user_id'] = user.get('userid', '').strip()
                
                # Determine Location
                loc_col = DB_COLS['ScanUsers_Loc'] or 'location'
                raw_loc = user.get(loc_col)
                session['location'] = str(raw_loc).strip() if raw_loc else 'Unknown'
                
                # Update Online Status
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user_id_input,))
                    conn.commit()
                except: pass
                    
                return redirect(url_for('dashboard')) 
            else:
                flash("Invalid User ID or Password.", "error")
        except Exception as e:
            flash(f"Login System Error: {str(e)}", "error")
        finally:
            conn.close()
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/picking', methods=['GET'])
def picking_menu():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    raw_so = request.args.get('so', '')
    order_items = []
    resolved_so = raw_so
    picker_val = ''
    
    if raw_so:
        conn = get_readonly_connection()
        try:
            cursor = conn.cursor()

            # Validate Order
            check_sql = f"SELECT TOP 1 sono FROM {Config.DB_ORDERS}.dbo.SOTRAN WITH (NOLOCK) WHERE sono LIKE ?"
            cursor.execute(check_sql, (f"%{raw_so.strip()}",))
            check_row = cursor.fetchone()
            
            if not check_row:
                flash(f"❌ Order '{raw_so}' not found.", "error")
                return render_template('picking.html', so=None, items=[])
            
            resolved_so = check_row[0] 
            
            # CHECK: Picker must be assigned (somast.picker cannot be NULL or blank)
            try:
                picker_sql = f"SELECT picker FROM {Config.DB_ORDERS}.dbo.SOMAST WITH (NOLOCK) WHERE sono=?"
                cursor.execute(picker_sql, (resolved_so,))
                picker_row = cursor.fetchone()
                picker_val = (str(picker_row[0]).strip() if picker_row and picker_row[0] is not None else '') if picker_row else ''
                
                if not picker_val:
                    flash("❌ Assigned picker required. This order has not been assigned to a picker.", "error")
                    return render_template('picking.html', so=None, items=[])
            except Exception as e:
                logging.error(f"Picker check error: {e}")
                flash("❌ Unable to verify picker assignment.", "error")
                return render_template('picking.html', so=None, items=[])
            
            user_loc = session.get('location', 'Unknown').strip()
            
            # 1. FETCH ORDER LINES (exclude cancelled lines where sostat = 'X')
            base_sql = f"""
                SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining, loctid
                FROM {Config.DB_ORDERS}.dbo.SOTRAN WITH (NOLOCK)
                WHERE sono=? AND qtyord > shipqty AND stkcode = 'Y' AND sostat <> 'X'
            """
            params = [resolved_so]
            
            if user_loc != '000' and user_loc != 'Unknown':
                base_sql += " AND loctid LIKE ?"
                params.append(f"{user_loc}%")
                
            base_sql += " ORDER BY tranlineno ASC"
            
            cursor.execute(base_sql, tuple(params))
            rows = cursor.fetchall()
            order_items = [row_to_dict(cursor, row) for row in rows]
            
            # 2. FETCH UPC MAPPING (Separate Step)
            if order_items:
                try:
                    unique_items = list(set((i['item'] or '').strip() for i in order_items))
                    
                    if unique_items:
                        placeholders = ','.join(['?'] * len(unique_items))
                        upc_sql = f"""
                            SELECT item, upc
                            FROM {Config.DB_AUTH}.dbo.scanitem WITH (NOLOCK)
                            WHERE item IN ({placeholders})
                        """
                        cursor.execute(upc_sql, tuple(unique_items))
                        upc_rows = cursor.fetchall()
                        
                        upc_map = {}
                        for r in upc_rows:
                            d = row_to_dict(cursor, r)
                            db_item = (d.get('item') or '').strip()
                            raw_upc = d.get('upc')
                            clean_upc = str(raw_upc).strip() if raw_upc is not None else ''
                            upc_map[db_item] = clean_upc

                        for item in order_items:
                            clean_item_code = (item.get('item') or '').strip()
                            item['item'] = clean_item_code
                            item['upc'] = upc_map.get(clean_item_code, '')
                    
                    for item in order_items:
                        if 'upc' not in item: item['upc'] = ''
                        
                except Exception as e:
                    logging.error(f"UPC Fetch Error: {e}")
                    for item in order_items: item['upc'] = ''

            if not order_items:
                flash(f"✅ Order #{resolved_so.strip()} is fully picked!", "success")
                
        except Exception as e:
            flash(f"Database Error: {str(e)}", "error")
        finally:
            if conn: conn.close()
            
    return render_template('picking.html', so=resolved_so, items=order_items, assigned_picker=picker_val)

@app.route('/get_item_bins', methods=['POST'])
def get_item_bins():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Login required'})
    detect_columns()
    
    data = request.json
    item_code = data.get('item', '').strip()
    user_loc = session.get('location', 'Unknown').strip()

    conn = get_readonly_connection()
    try:
        cursor = conn.cursor()
        loc_col = DB_COLS['ScanOnhand2_Loc'] or 'terr'
        alloc_col = DB_COLS['ScanOnhand2_Alloc'] or 'aloc'

        sql = f"""
            SELECT bin, onhand, {alloc_col}, {loc_col}
            FROM {Config.DB_AUTH}.dbo.ScanOnhand2 WITH (NOLOCK)
            WHERE item = ? AND onhand > 0
        """
        params = [item_code]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
        
        sql += f" ORDER BY (onhand - ISNULL({alloc_col}, 0)) ASC"
        
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        
        bins = []
        for row in rows:
            r = row_to_dict(cursor, row)
            qty_onhand = int(r.get('onhand') or 0)
            qty_alloc = int(r.get(alloc_col) or 0) 
            qty_avail = qty_onhand - qty_alloc
            bin_val = (r.get('bin') or '').strip()
            loc_val = (r.get(loc_col) or '').strip()

            if not is_valid_bin(bin_val):
                continue

            bins.append({
                'bin': bin_val,
                'qty': qty_onhand,
                'alloc': qty_alloc,
                'avail': qty_avail,
                'loc': loc_val
            })
            
        return jsonify({'status': 'success', 'bins': bins})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        if conn: conn.close()

@app.route('/validate_bin', methods=['POST'])
def validate_bin():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Login required'})
    detect_columns()
    
    data = request.json
    bin_loc = data.get('bin', '').strip()
    item_code = data.get('item', '').strip()
    user_loc = session.get('location', 'Unknown').strip()

    conn = get_readonly_connection()
    try:
        cursor = conn.cursor()
        loc_col = DB_COLS['ScanOnhand2_Loc'] or 'terr'
        
        sql = f"""
            SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 WITH (NOLOCK)
            WHERE bin=? AND item = ? AND onhand > 0
        """
        params = [bin_loc, item_code]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
            
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        
        if row: 
            safe_onhand = int(row[0] or 0)
            return jsonify({'status': 'success', 'onhand': safe_onhand})
        else: 
            return jsonify({'status': 'error', 'msg': f"❌ Bin '{bin_loc}' Empty/Mismatch"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        if conn: conn.close()

@app.route('/report_bin', methods=['POST'])
def report_bin():
    """
    Receives a bin issue report from the picker and sends an email
    to the IC team in the background. Returns immediately so the
    picker can continue working without interruption.
    """
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'msg': 'Session expired. Please log in again.'})

    data = request.json
    bin_val = data.get('bin', '').strip()
    item_code = data.get('item', '').strip()
    reason = data.get('reason', '').strip()
    notes = data.get('notes', '').strip()
    onhand = data.get('onhand', 'N/A')
    alloc = data.get('alloc', 'N/A')
    avail = data.get('avail', 'N/A')
    so_num = data.get('so', '').strip()

    if not bin_val or not reason:
        return jsonify({'status': 'error', 'msg': 'Bin and reason are required.'})

    # Sanitize notes — max 500 chars to prevent abuse
    if len(notes) > 500:
        notes = notes[:500]

    report_data = {
        'bin': bin_val,
        'item': item_code,
        'reason': reason,
        'notes': notes,
        'onhand': onhand,
        'alloc': alloc,
        'avail': avail,
        'so': so_num,
        'picker': session.get('user_id', 'Unknown'),
        'location': session.get('location', 'Unknown'),
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    logging.info(
        f"BIN REPORT RECEIVED: Bin={bin_val}, Item={item_code}, "
        f"Reason={reason}, Picker={session.get('user_id')}, SO={so_num}"
    )

    # Fire email in background — picker gets instant response
    send_bin_report_email(report_data)

    return jsonify({
        'status': 'success',
        'msg': f"Report submitted for bin {bin_val}. IC team has been notified."
    })

@app.route('/process_batch_scan', methods=['POST'])
def process_batch_scan():
    """
    Commits updates to ScanOnhand2, SOTRAN, and ScanBinTran2.
    Includes: Exception Codes mapping, pre-commit validation, 
    SQL-level guards, post-commit verification with warnings.
    """
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    detect_columns()
    
    data = request.json
    picks = data.get('picks', [])
    exceptions = data.get('exceptions', {})  # Short-pick exception reason codes
    so_num = data.get('so', '')
    batch_id = data.get('batch_id') or str(uuid.uuid4())
    device_id = '' 
    user_id = session.get('user_id')
    user_loc = session.get('location', 'Unknown')
    
    if not picks: return jsonify({'status': 'error', 'msg': 'No picks to submit!'})

    logging.info(f"--- PROCESSING BATCH {batch_id} (FULL COMMIT) ---")

    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'msg': 'Database Unavailable'})

    try:
        cursor = conn.cursor()

        # Set lock timeout to prevent indefinite waits on locked rows (10 seconds)
        cursor.execute("SET LOCK_TIMEOUT 10000")

        col_loc = DB_COLS['ScanOnhand2_Loc'] or 'loctid'
        col_alloc = DB_COLS['ScanOnhand2_Alloc'] or 'aloc'

        # ===================================================================
        # PRE-AGGREGATE: Build line-level totals for SOTRAN validation
        # AND inventory-level totals by (item, bin) for ScanOnhand2
        # Zero-qty picks (from Zero Pick workflow) are excluded —
        # they don't update inventory or SOTRAN, only the audit log.
        # ===================================================================
        line_updates = {}
        inv_updates = {}  # key: (item, bin) -> aggregated qty
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = int(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()

            if qty <= 0: continue  # Skip zero picks — audit-only

            if line_no not in line_updates:
                line_updates[line_no] = {'qty': 0, 'item': item}
            line_updates[line_no]['qty'] += qty

            inv_key = (item, bin_val)
            inv_updates[inv_key] = inv_updates.get(inv_key, 0) + qty

        # ===================================================================
        # PART 1: Inventory Update (ScanOnhand2) — aggregated by (item, bin)
        # SQL-level WHERE guard is the real safety net against concurrency.
        # ===================================================================
        update_inv_sql = f"""
            UPDATE {Config.DB_AUTH}.dbo.ScanOnhand2
            SET {col_alloc} = ISNULL({col_alloc}, 0) + ?,
                avail = onhand - (ISNULL({col_alloc}, 0) + ?),
                lupdate = GETDATE(),
                luser = ?
            WHERE item=? AND bin=? AND {col_loc}=?
              AND (onhand - ISNULL({col_alloc}, 0)) >= ?
        """
        for (item, bin_val), agg_qty in inv_updates.items():
            cursor.execute(update_inv_sql, (agg_qty, agg_qty, user_id, item, bin_val, user_loc, agg_qty))

            if cursor.rowcount == 0:
                raise Exception(
                    f"INVENTORY GUARD: Update rejected for item '{item}' at bin '{bin_val}'. "
                    f"Insufficient available stock or row not found (concurrent pick likely)."
                )

        # ===================================================================
        # PART 2: Sales Order Update (SOTRAN) — with SQL-level guard
        # ===================================================================
        expected_shipqty = {}

        update_so_sql = f"""
            UPDATE {Config.DB_ORDERS}.dbo.SOTRAN
            SET shipqty = shipqty + ?,
                shipdate = GETDATE()
            WHERE sono=? AND tranlineno=? AND item=?
              AND (qtyord - shipqty) >= ?
        """
        for line_no, line_data in line_updates.items():
            agg_qty = line_data['qty']
            item_code = line_data['item']

            # Read current shipqty to compute expected value after update
            cursor.execute(
                f"SELECT shipqty FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND tranlineno=? AND item=?",
                (so_num, line_no, item_code)
            )
            pre_row = cursor.fetchone()
            pre_shipqty = int(pre_row[0] or 0) if pre_row else 0
            expected_shipqty[line_no] = pre_shipqty + agg_qty

            cursor.execute(update_so_sql, (agg_qty, so_num, line_no, item_code, agg_qty))

            if cursor.rowcount == 0:
                raise Exception(
                    f"ORDER GUARD: Update rejected for line {line_no} (item '{item_code}'). "
                    f"Remaining qty insufficient or row not found (concurrent pick likely)."
                )

        # ===================================================================
        # PART 3: Audit Log Insert (ScanBinTran2) — batched with executemany
        # Zero-qty picks ARE included here — this is their only DB write.
        # ===================================================================
        insert_sql = f"""
            INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2
            (actiontype, applid, udref, tranlineno, upc, item, binfr, quantity, userid, deviceid, adddate, scanstat, scanresult)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?)
        """
        audit_rows = []
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = int(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            upc_val = item

            raw_exception = pick.get('exception', '') or exceptions.get(str(line_no), '')
            safe_exception_code = str(raw_exception)[:10] if raw_exception else ''

            audit_rows.append((
                'SP', 'SO', so_num, line_no, upc_val, item, bin_val, qty,
                user_id, device_id, '', safe_exception_code
            ))

        cursor.fast_executemany = True
        cursor.executemany(insert_sql, audit_rows)

        # ===================================================================
        # FINAL COMMIT
        # ===================================================================
        conn.commit()
        logging.info(f"--- COMMITTED BATCH {batch_id}: {len(picks)} picks ---")

        # ===================================================================
        # POST-COMMIT VERIFICATION (read-only — log alerts, never rollback)
        # ===================================================================
        post_warnings = []

        try:
            # Verify: SOTRAN shipqty matches expected
            for line_no, expected_val in expected_shipqty.items():
                item_code = line_updates[line_no]['item']
                cursor.execute(
                    f"SELECT shipqty FROM {Config.DB_ORDERS}.dbo.SOTRAN WITH (NOLOCK) WHERE sono=? AND tranlineno=? AND item=?",
                    (so_num, line_no, item_code)
                )
                post_row = cursor.fetchone()
                actual_shipqty = int(post_row[0] or 0) if post_row else -1

                if actual_shipqty != expected_val:
                    warn = (
                        f"POST-CHECK WARN: Line {line_no} (item '{item_code}') — "
                        f"expected shipqty={expected_val}, actual={actual_shipqty}."
                    )
                    logging.critical(warn)
                    post_warnings.append(warn)

        except Exception as pve:
            logging.critical(f"POST-CHECK ERROR (non-fatal): {pve}")
            post_warnings.append(f"Post-commit verification error: {str(pve)}")

        # ===================================================================
        # RESPONSE
        # ===================================================================
        msg = f"SUCCESS: Processed {len(picks)} lines.\nUpdated Inventory & Order."
        if post_warnings:
            msg += f"\n⚠️ {len(post_warnings)} verification warning(s) logged."

        logging.info(f"--- SUCCESS: BATCH {batch_id} COMPLETE ---")
        
        return jsonify({
            'status': 'success', 
            'msg': msg,
            'batch_id': batch_id,
            'warnings': post_warnings if post_warnings else None
        })

    except Exception as e:
        conn.rollback()
        logging.error(f"Batch {batch_id} ROLLED BACK: {e}")
        return jsonify({'status': 'error', 'msg': f"Transaction Failed: {str(e)}"})
    finally:
        if conn: conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)