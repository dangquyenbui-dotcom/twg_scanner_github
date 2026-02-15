from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
import pyodbc
import logging
import datetime
import uuid

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config.from_object(Config)

# --- GLOBAL CACHE ---
DB_COLS = {
    'ScanOnhand2': None,
    'ScanUsers': None,
    'ScanBinTran2_UPC': False,
    'ScanItem_UPC': False
}

def get_db_connection():
    """Establishes a connection to the SQL Server with explicit timeout."""
    conn_str = (
        f"DRIVER={app.config['DB_DRIVER']};"
        f"SERVER={app.config['DB_SERVER']};"
        f"DATABASE={app.config['DB_AUTH']};"
        f"UID={app.config['DB_UID']};"
        f"PWD={app.config['DB_PWD']};"
    )
    try:
        # Increased timeout for unstable networks
        return pyodbc.connect(conn_str, timeout=15, autocommit=False) 
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}")
        return None

def row_to_dict(cursor, row):
    columns = [column[0].lower() for column in cursor.description]
    return dict(zip(columns, row))

def detect_columns():
    """Dynamically detects column names to handle schema variations."""
    if DB_COLS['ScanOnhand2']: return 
    
    conn = get_db_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor()
        
        # 1. Detect Location Column in Inventory
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanOnhand2")
            cols = [c[0].lower() for c in cursor.description]
            if 'loctid' in cols: DB_COLS['ScanOnhand2'] = 'loctid'
            elif 'terr' in cols: DB_COLS['ScanOnhand2'] = 'terr'
            elif 'location_id' in cols: DB_COLS['ScanOnhand2'] = 'location_id'
            else: DB_COLS['ScanOnhand2'] = 'terr'
        except: DB_COLS['ScanOnhand2'] = 'terr'

        # 2. Detect Location Column in Users
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanUsers")
            cols = [c[0].lower() for c in cursor.description]
            if 'location_id' in cols: DB_COLS['ScanUsers'] = 'location_id'
            else: DB_COLS['ScanUsers'] = 'location'
        except: DB_COLS['ScanUsers'] = 'location'

        # 3. Check for UPC Column Support
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanBinTran2")
            cols = [c[0].lower() for c in cursor.description]
            DB_COLS['ScanBinTran2_UPC'] = ('upc' in cols)
        except: DB_COLS['ScanBinTran2_UPC'] = False

        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanItem")
            cols = [c[0].lower() for c in cursor.description]
            DB_COLS['ScanItem_UPC'] = ('upc' in cols)
        except: DB_COLS['ScanItem_UPC'] = False

    except Exception as e:
        logging.error(f"Column Detection Error: {e}")
    finally:
        conn.close()

# --- ROUTES ---

@app.route('/health')
def health_check():
    """Lightweight endpoint for client to check connectivity."""
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
            sql = f"SELECT * FROM {Config.DB_AUTH}.dbo.ScanUsers WHERE userid=? AND pw=?"
            cursor.execute(sql, (user_id_input, password_input))
            row = cursor.fetchone()
            
            if row:
                user = row_to_dict(cursor, row)
                session['user_id'] = user.get('userid', '').strip()
                session['user_name'] = user.get('name', 'Unknown')
                
                # Determine Location
                loc_col = DB_COLS['ScanUsers'] or 'location'
                raw_loc = user.get(loc_col)
                session['location'] = str(raw_loc).strip() if raw_loc else 'Unknown'
                
                # Set User Online Status
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user_id_input,))
                    conn.commit()
                except Exception as ex:
                    logging.warning(f"Failed to update userstat: {ex}")
                    
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
    
    if raw_so:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 1. Validate Order Exists
            search_term = f"%{raw_so.strip()}"
            check_sql = f"SELECT TOP 1 sono FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono LIKE ?"
            cursor.execute(check_sql, (search_term,))
            check_row = cursor.fetchone()
            
            if not check_row:
                flash(f"❌ Order '{raw_so}' not found.", "error")
                return render_template('picking.html', so=None, items=[])
            
            resolved_so = check_row[0] 
            user_loc = session.get('location', 'Unknown').strip()
            
            # 2. Fetch Open Lines
            base_sql = f"""
                SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining, loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND qtyord > shipqty
            """
            params = [resolved_so]
            
            # Location Fencing
            if user_loc != '000' and user_loc != 'Unknown':
                base_sql += " AND loctid LIKE ?"
                params.append(f"{user_loc}%")
                
            base_sql += " ORDER BY item ASC, tranlineno ASC"
            
            cursor.execute(base_sql, tuple(params))
            rows = cursor.fetchall()
            order_items = [row_to_dict(cursor, row) for row in rows]
            
            if not order_items:
                flash(f"✅ Order #{resolved_so.strip()} is fully picked for your location!", "success")
                
        except Exception as e:
            flash(f"Database Error: {str(e)}", "error")
        finally:
            if conn: conn.close()
            
    return render_template('picking.html', so=resolved_so, items=order_items)

@app.route('/get_item_bins', methods=['POST'])
def get_item_bins():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Login required'})
    detect_columns()
    
    data = request.json
    item_code = data.get('item', '').strip()
    user_loc = session.get('location', 'Unknown').strip()
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        loc_col = DB_COLS['ScanOnhand2'] or 'terr'
        
        # Find bins with stock
        sql = f"""
            SELECT bin, onhand, {loc_col} FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE item LIKE ? AND onhand > 0
        """
        params = [f"%{item_code}%"]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
            
        sql += " ORDER BY onhand DESC"
        
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        
        bins = []
        for row in rows:
            r = row_to_dict(cursor, row)
            bins.append({
                'bin': r['bin'].strip(),
                'qty': int(r['onhand']),
                'loc': r.get(loc_col, '').strip()
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
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        loc_col = DB_COLS['ScanOnhand2'] or 'terr'
        
        sql = f"""
            SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE bin=? AND item LIKE ? AND onhand > 0
        """
        params = [bin_loc, f"%{item_code}%"]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
            
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        
        if row:
            return jsonify({'status': 'success', 'onhand': int(row[0])})
        else:
            return jsonify({'status': 'error', 'msg': f"❌ Bin '{bin_loc}' does not contain '{item_code}' or is empty."})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        if conn: conn.close()

@app.route('/process_batch_scan', methods=['POST'])
def process_batch_scan():
    """
    CRITICAL: This function processes the batch.
    It uses DB Transactions to ensure partial failures do not corrupt data.
    Now supports batch_id for tracking.
    """
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    detect_columns()
    
    data = request.json
    picks = data.get('picks', [])
    so_num = data.get('so', '')
    batch_id = data.get('batch_id', str(uuid.uuid4())) # Use provided or generate new
    user_id = session.get('user_id')
    
    if not picks:
        return jsonify({'status': 'error', 'msg': 'No picks to submit!'})

    logging.info(f"Processing Batch {batch_id} for SO {so_num} with {len(picks)} lines.")

    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'msg': 'Database Unavailable - Try Again'})

    try:
        cursor = conn.cursor()
        
        # --- START TRANSACTION ---
        
        processed_count = 0
        
        for pick in picks:
            scanned_item = pick.get('item', '').strip()
            bin_loc = pick.get('bin', '').strip()
            qty = float(pick.get('qty', 0))
            tran_line = pick.get('lineNo')

            if qty <= 0: continue

            # 1. SERVER-SIDE VALIDATION: Check Order Line Status AGAIN
            sql_check_so = f"""
                SELECT (qtyord - shipqty) as remaining 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND tranlineno=?
            """
            cursor.execute(sql_check_so, (so_num, tran_line))
            so_row = cursor.fetchone()
            
            if not so_row:
                 raise Exception(f"Line {tran_line} ({scanned_item}) closed or invalid.")
            
            remaining_so = float(so_row[0])
            if qty > remaining_so:
                raise Exception(f"Over-shipment: {scanned_item}. Need {remaining_so}, Tried {qty}.")

            # 2. SERVER-SIDE VALIDATION & UPDATE
            if not Config.SIMULATION_MODE:
                # A. Decrement Inventory (Optimistic Locking)
                update_inv_sql = f"""
                    UPDATE {Config.DB_AUTH}.dbo.ScanOnhand2 
                    SET onhand = onhand - ? 
                    WHERE bin=? AND item=? AND onhand >= ?
                """
                cursor.execute(update_inv_sql, (qty, bin_loc, scanned_item, qty))
                
                if cursor.rowcount == 0:
                     raise Exception(f"Stock Conflict! {bin_loc} doesn't have {qty} of {scanned_item}.")

                # B. Update Sales Order (Ship Qty)
                update_so_sql = f"""
                    UPDATE {Config.DB_ORDERS}.dbo.SOTRAN
                    SET shipqty = shipqty + ?
                    WHERE sono=? AND tranlineno=?
                """
                cursor.execute(update_so_sql, (qty, so_num, tran_line))

                # C. Audit Log
                upc_code = '' 
                if DB_COLS['ScanItem_UPC']:
                    cursor.execute(f"SELECT TOP 1 upc FROM {Config.DB_AUTH}.dbo.ScanItem WHERE item=?", (scanned_item,))
                    u_row = cursor.fetchone()
                    if u_row: upc_code = u_row[0]

                insert_hist_sql = f"""
                    INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2 
                    (item, bin, qty, userid, datetime, sono, type, upc)
                    VALUES (?, ?, ?, ?, GETDATE(), ?, 'PICK', ?)
                """
                # Note: We could store batch_id here if schema supported it.
                cursor.execute(insert_hist_sql, (scanned_item, bin_loc, qty, user_id, so_num, upc_code))

            processed_count += 1

        # --- COMMIT TRANSACTION ---
        conn.commit()
        
        status_msg = f"Saved {processed_count} lines."
        if Config.SIMULATION_MODE:
             status_msg = f"SIMULATION SUCCESS: {processed_count} lines (No DB write)."

        return jsonify({'status': 'success', 'msg': status_msg, 'batch_id': batch_id})

    except Exception as e:
        conn.rollback() # CRITICAL: Undo everything
        logging.error(f"Batch {batch_id} Failed: {e}")
        return jsonify({'status': 'error', 'msg': f"Batch Failed: {str(e)}"})
    finally:
        if conn: conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)