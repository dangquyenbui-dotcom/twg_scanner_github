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
    'ScanOnhand2_Loc': None,    # loctid vs terr
    'ScanOnhand2_Alloc': None,  # aloc vs alloc
    'ScanUsers_Loc': None,
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
        return pyodbc.connect(conn_str, timeout=15, autocommit=False) 
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}")
        return None

def row_to_dict(cursor, row):
    columns = [column[0].lower() for column in cursor.description]
    return dict(zip(columns, row))

def detect_columns():
    """Dynamically detects column names to handle schema variations (aloc vs alloc)."""
    if DB_COLS['ScanOnhand2_Loc']: return 
    
    conn = get_db_connection()
    if not conn: return
    
    try:
        cursor = conn.cursor()
        
        # 1. Detect Columns in Inventory (ScanOnhand2)
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanOnhand2")
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
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanUsers")
            cols = [c[0].lower() for c in cursor.description]
            if 'location_id' in cols: DB_COLS['ScanUsers_Loc'] = 'location_id'
            else: DB_COLS['ScanUsers_Loc'] = 'location'
        except: DB_COLS['ScanUsers_Loc'] = 'location'

        # 3. Check for UPC Column Support
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanBinTran2")
            cols = [c[0].lower() for c in cursor.description]
            DB_COLS['ScanBinTran2_UPC'] = ('upc' in cols)
        except: DB_COLS['ScanBinTran2_UPC'] = False

    except Exception as e:
        logging.error(f"Column Detection Error: {e}")
    finally:
        conn.close()

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
            sql = f"SELECT * FROM {Config.DB_AUTH}.dbo.ScanUsers WHERE userid=? AND pw=?"
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
    
    if raw_so:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Validate Order
            check_sql = f"SELECT TOP 1 sono FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono LIKE ?"
            cursor.execute(check_sql, (f"%{raw_so.strip()}",))
            check_row = cursor.fetchone()
            
            if not check_row:
                flash(f"❌ Order '{raw_so}' not found.", "error")
                return render_template('picking.html', so=None, items=[])
            
            resolved_so = check_row[0] 
            user_loc = session.get('location', 'Unknown').strip()
            
            # 1. FETCH ORDER LINES
            # Standard query with location filtering if applicable
            base_sql = f"""
                SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining, loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND qtyord > shipqty
            """
            params = [resolved_so]
            
            if user_loc != '000' and user_loc != 'Unknown':
                base_sql += " AND loctid LIKE ?"
                params.append(f"{user_loc}%")
                
            base_sql += " ORDER BY item ASC, tranlineno ASC"
            
            cursor.execute(base_sql, tuple(params))
            rows = cursor.fetchall()
            order_items = [row_to_dict(cursor, row) for row in rows]
            
            # 2. FETCH UPC MAPPING (Separate Step)
            if order_items:
                try:
                    # Collect unique items from the order
                    unique_items = list(set(i['item'] for i in order_items))
                    
                    if unique_items:
                        # Build dynamic IN clause
                        placeholders = ','.join(['?'] * len(unique_items))
                        upc_sql = f"""
                            SELECT item, upc 
                            FROM {Config.DB_AUTH}.dbo.scanitem 
                            WHERE item IN ({placeholders})
                        """
                        cursor.execute(upc_sql, tuple(unique_items))
                        upc_rows = cursor.fetchall()
                        
                        # Create Map: Item -> UPC
                        # Using row_to_dict to ensure column name safety
                        upc_map = {}
                        for r in upc_rows:
                            d = row_to_dict(cursor, r)
                            upc_map[d['item']] = d.get('upc', '')

                        # Apply UPCs to order items
                        for item in order_items:
                            item['upc'] = upc_map.get(item['item'], '')
                    
                    # Ensure 'upc' key exists for all items even if lookup failed
                    for item in order_items:
                        if 'upc' not in item: item['upc'] = ''
                        
                except Exception as e:
                    logging.error(f"UPC Fetch Error: {e}")
                    # Fallback: Just set empty UPCs so the app doesn't crash
                    for item in order_items: item['upc'] = ''

            if not order_items:
                flash(f"✅ Order #{resolved_so.strip()} is fully picked!", "success")
                
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
        loc_col = DB_COLS['ScanOnhand2_Loc'] or 'terr'
        alloc_col = DB_COLS['ScanOnhand2_Alloc'] or 'aloc'

        # Fetch Data - Exact Match
        sql = f"""
            SELECT bin, onhand, {alloc_col}, {loc_col} 
            FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE item = ? AND onhand > 0
        """
        params = [item_code]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
        
        sql += " ORDER BY bin ASC"
        
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        
        bins = []
        for row in rows:
            r = row_to_dict(cursor, row)
            
            # --- FIX: SAFE CONVERSIONS (Handle None/NULL) ---
            # Use (val or 0) pattern to handle DB NULLs gracefully
            qty_onhand = int(r.get('onhand') or 0)
            qty_alloc = int(r.get(alloc_col) or 0) 
            qty_avail = qty_onhand - qty_alloc
            
            # --- FIX: SAFE STRING HANDLING ---
            # Ensure we don't call .strip() on None
            bin_val = (r.get('bin') or '').strip()
            loc_val = (r.get(loc_col) or '').strip()

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
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        loc_col = DB_COLS['ScanOnhand2_Loc'] or 'terr'
        
        sql = f"""
            SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE bin=? AND item = ? AND onhand > 0
        """
        params = [bin_loc, item_code]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += f" AND {loc_col} LIKE ?"
            params.append(f"{user_loc}%")
            
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        
        if row: 
            # --- FIX: Handle potential NULL onhand ---
            safe_onhand = int(row[0] or 0)
            return jsonify({'status': 'success', 'onhand': safe_onhand})
        else: 
            return jsonify({'status': 'error', 'msg': f"❌ Bin '{bin_loc}' Empty/Mismatch"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        if conn: conn.close()

@app.route('/process_batch_scan', methods=['POST'])
def process_batch_scan():
    """
    PRODUCTION MODE: Commits updates to ScanOnhand2, SOTRAN, and ScanBinTran2.
    """
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    detect_columns()
    
    data = request.json
    picks = data.get('picks', [])
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
        
        col_loc = DB_COLS['ScanOnhand2_Loc'] or 'loctid'
        col_alloc = DB_COLS['ScanOnhand2_Alloc'] or 'aloc'

        # -------------------------------------------------------------------
        # PART 1: Inventory Update (ScanOnhand2)
        # -------------------------------------------------------------------
        for pick in picks:
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            qty = float(pick.get('qty', 0))

            if qty <= 0: continue

            # --- FIX: ISNULL ADDED ---
            # If 'aloc' is NULL in DB, (NULL + qty) = NULL, destroying data.
            # ISNULL(col, 0) treats NULL as 0 for the math, preserving data.
            update_inv_sql = f"""
                UPDATE {Config.DB_AUTH}.dbo.ScanOnhand2
                SET {col_alloc} = ISNULL({col_alloc}, 0) + ?, 
                    avail = onhand - (ISNULL({col_alloc}, 0) + ?),
                    lupdate = GETDATE(),
                    luser = ?
                WHERE item=? AND bin=? AND {col_loc}=?
            """
            cursor.execute(update_inv_sql, (qty, qty, user_id, item, bin_val, user_loc))
            
            if cursor.rowcount == 0:
                raise Exception(f"Inventory Update Failed: {item} at {bin_val} not found in {user_loc}")

        # -------------------------------------------------------------------
        # PART 2: Sales Order Update (SOTRAN)
        # -------------------------------------------------------------------
        line_updates = {}
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = float(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            
            if line_no not in line_updates:
                line_updates[line_no] = {'qty': 0.0, 'item': item}
            line_updates[line_no]['qty'] += qty

        for line_no, data in line_updates.items():
            agg_qty = data['qty']
            item_code = data['item']

            update_so_sql = f"""
                UPDATE {Config.DB_ORDERS}.dbo.SOTRAN
                SET shipqty = shipqty + ?,
                    shipdate = GETDATE()
                WHERE sono=? AND tranlineno=? AND item=?
            """
            cursor.execute(update_so_sql, (agg_qty, so_num, line_no, item_code))
            
            if cursor.rowcount == 0:
                raise Exception(f"Order Update Failed: Line {line_no} for {item_code} not found.")

        # -------------------------------------------------------------------
        # PART 3: Audit Log (ScanBinTran2)
        # -------------------------------------------------------------------
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = float(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            upc_val = item 

            insert_sql = f"""
                INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2 
                (actiontype, applid, udref, tranlineno, upc, item, binfr, quantity, userid, deviceid, adddate, scanstat, scanresult)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?)
            """
            cursor.execute(insert_sql, ('SP', 'SO', so_num, line_no, upc_val, item, bin_val, qty, user_id, device_id, '', ''))

        # --- FINAL COMMIT ---
        conn.commit()
        logging.info(f"--- SUCCESS: COMMITTED BATCH {batch_id} ---")
        
        return jsonify({
            'status': 'success', 
            'msg': f"SUCCESS: Processed {len(picks)} lines.\nUpdated Inventory & Order.",
            'batch_id': batch_id
        })

    except Exception as e:
        conn.rollback()
        logging.error(f"Batch Failed: {e}")
        return jsonify({'status': 'error', 'msg': f"Database Error: {str(e)}"})
    finally:
        if conn: conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)