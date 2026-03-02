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


def is_valid_bin(bin_value):
    """
    Validates a bin value:
    - Must be exactly 15 characters long
    - The 5th character (index 4) must be numeric (0-9)
    """
    if not bin_value or len(bin_value) != 15:
        return False
    if not bin_value[4].isdigit():
        return False
    return True


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
            
            # CHECK: Picker must be assigned
            try:
                picker_sql = f"SELECT picker FROM {Config.DB_ORDERS}.dbo.SOMAST WHERE sono=?"
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
            
            # 1. FETCH ORDER LINES (exclude cancelled lines)
            base_sql = f"""
                SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining, loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
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
            
            # 2. FETCH UPC MAPPING
            if order_items:
                try:
                    unique_items = list(set((i['item'] or '').strip() for i in order_items))
                    
                    if unique_items:
                        placeholders = ','.join(['?'] * len(unique_items))
                        upc_sql = f"""
                            SELECT item, upc 
                            FROM {Config.DB_AUTH}.dbo.scanitem 
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

        sql = f"""
            SELECT bin, onhand, {alloc_col}, {loc_col} 
            FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
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
    SIMULATION MODE: Runs all logic, but executes a ROLLBACK at the end.
    """
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    detect_columns()
    
    data = request.json
    picks = data.get('picks', [])
    exceptions = data.get('exceptions', {})
    so_num = data.get('so', '')
    batch_id = data.get('batch_id') or str(uuid.uuid4())
    device_id = '' 
    user_id = session.get('user_id')
    user_loc = session.get('location', 'Unknown')
    
    if not picks: return jsonify({'status': 'error', 'msg': 'No picks to submit!'})

    is_simulation = app.config.get('SIMULATION_MODE', False)
    mode_str = "SIMULATION (ROLLBACK)" if is_simulation else "FULL COMMIT"
    logging.info(f"--- PROCESSING BATCH {batch_id} ({mode_str}) ---")

    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'msg': 'Database Unavailable'})

    try:
        cursor = conn.cursor()
        
        col_loc = DB_COLS['ScanOnhand2_Loc'] or 'loctid'
        col_alloc = DB_COLS['ScanOnhand2_Alloc'] or 'aloc'

        # ===================================================================
        # PRE-AGGREGATE: Build line-level totals for SOTRAN validation
        # ===================================================================
        line_updates = {}
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = int(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            
            if line_no not in line_updates:
                line_updates[line_no] = {'qty': 0, 'item': item}
            line_updates[line_no]['qty'] += qty

        # ===================================================================
        # PRE-COMMIT VALIDATION PHASE
        # ===================================================================

        for pick in picks:
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            qty = int(pick.get('qty', 0))

            if qty <= 0: continue

            check_inv_sql = f"""
                SELECT onhand, ISNULL({col_alloc}, 0) as current_alloc
                FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
                WHERE item=? AND bin=? AND {col_loc}=?
            """
            cursor.execute(check_inv_sql, (item, bin_val, user_loc))
            inv_row = cursor.fetchone()

            if not inv_row:
                raise Exception(
                    f"PRE-CHECK FAILED: Item '{item}' not found in bin '{bin_val}' at location '{user_loc}'."
                )
            
            current_onhand = int(inv_row[0] or 0)
            current_alloc = int(inv_row[1] or 0)
            available = current_onhand - current_alloc

            if available < qty:
                raise Exception(
                    f"PRE-CHECK FAILED: Item '{item}' in bin '{bin_val}' — "
                    f"available={available} (onhand={current_onhand}, alloc={current_alloc}), requested={qty}."
                )

        for line_no, line_data in line_updates.items():
            agg_qty = line_data['qty']
            item_code = line_data['item']

            check_so_sql = f"""
                SELECT qtyord, shipqty, (qtyord - shipqty) as remaining
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND tranlineno=? AND item=?
            """
            cursor.execute(check_so_sql, (so_num, line_no, item_code))
            so_row = cursor.fetchone()

            if not so_row:
                raise Exception(f"PRE-CHECK FAILED: Order line {line_no} for item '{item_code}' on SO '{so_num}' not found.")

            remaining = int(so_row[2] or 0)
            if remaining < agg_qty:
                raise Exception(f"PRE-CHECK FAILED: Order line {line_no} (item '{item_code}') — remaining={remaining}, requested={agg_qty}. Would over-ship.")

        logging.info(f"Batch {batch_id}: All pre-commit validations passed.")

        # ===================================================================
        # PART 1: Inventory Update (ScanOnhand2)
        # ===================================================================
        for pick in picks:
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            qty = int(pick.get('qty', 0))

            if qty <= 0: continue

            update_inv_sql = f"""
                UPDATE {Config.DB_AUTH}.dbo.ScanOnhand2
                SET {col_alloc} = ISNULL({col_alloc}, 0) + ?, 
                    avail = onhand - (ISNULL({col_alloc}, 0) + ?),
                    lupdate = GETDATE(),
                    luser = ?
                WHERE item=? AND bin=? AND {col_loc}=?
                  AND (onhand - ISNULL({col_alloc}, 0)) >= ?
            """
            cursor.execute(update_inv_sql, (qty, qty, user_id, item, bin_val, user_loc, qty))
            
            if cursor.rowcount == 0:
                raise Exception(f"INVENTORY GUARD: Update rejected for item '{item}' at bin '{bin_val}'. Insufficient available stock or row not found (concurrent pick likely).")

        # ===================================================================
        # PART 2: Sales Order Update (SOTRAN)
        # ===================================================================
        expected_shipqty = {}

        for line_no, line_data in line_updates.items():
            agg_qty = line_data['qty']
            item_code = line_data['item']

            cursor.execute(f"SELECT shipqty FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND tranlineno=? AND item=?", (so_num, line_no, item_code))
            pre_row = cursor.fetchone()
            pre_shipqty = int(pre_row[0] or 0) if pre_row else 0
            expected_shipqty[line_no] = pre_shipqty + agg_qty

            update_so_sql = f"""
                UPDATE {Config.DB_ORDERS}.dbo.SOTRAN
                SET shipqty = shipqty + ?,
                    shipdate = GETDATE()
                WHERE sono=? AND tranlineno=? AND item=?
                  AND (qtyord - shipqty) >= ?
            """
            cursor.execute(update_so_sql, (agg_qty, so_num, line_no, item_code, agg_qty))
            
            if cursor.rowcount == 0:
                raise Exception(f"ORDER GUARD: Update rejected for line {line_no} (item '{item_code}'). Remaining qty insufficient or row not found.")

        # ===================================================================
        # PART 3: Audit Log (ScanBinTran2)
        # ===================================================================
        for pick in picks:
            line_no = pick.get('lineNo')
            qty = int(pick.get('qty', 0))
            item = pick.get('item', '').strip()
            bin_val = pick.get('bin', '').strip()
            upc_val = item 
            
            # Fetch exception code for this line (defaults to blank per instructions)
            exception_code = exceptions.get(str(line_no), '')

            insert_sql = f"""
                INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2 
                (actiontype, applid, udref, tranlineno, upc, item, binfr, quantity, userid, deviceid, adddate, scanstat, scanresult)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?)
            """
            cursor.execute(insert_sql, (
                'SP', 'SO', so_num, line_no, upc_val, item, bin_val, qty,
                user_id, device_id, '', exception_code
            ))

        # ===================================================================
        # FINAL COMMIT / ROLLBACK (Simulation Mode)
        # ===================================================================
        if is_simulation:
            conn.rollback()
            logging.info(f"--- SIMULATION MODE: ROLLED BACK BATCH {batch_id} ---")
        else:
            conn.commit()
            logging.info(f"--- COMMITTED BATCH {batch_id}: {len(picks)} picks ---")

        # ===================================================================
        # POST-COMMIT VERIFICATION
        # ===================================================================
        post_warnings = []

        if not is_simulation:
            try:
                for line_no, expected_val in expected_shipqty.items():
                    item_code = line_updates[line_no]['item']
                    cursor.execute(f"SELECT shipqty FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND tranlineno=? AND item=?", (so_num, line_no, item_code))
                    post_row = cursor.fetchone()
                    actual_shipqty = int(post_row[0] or 0) if post_row else -1

                    if actual_shipqty != expected_val:
                        warn = f"POST-CHECK WARN: Line {line_no} (item '{item_code}') — expected shipqty={expected_val}, actual={actual_shipqty}."
                        logging.critical(warn)
                        post_warnings.append(warn)

            except Exception as pve:
                logging.critical(f"POST-CHECK ERROR (non-fatal): {pve}")
                post_warnings.append(f"Post-commit verification error: {str(pve)}")

        # ===================================================================
        # RESPONSE
        # ===================================================================
        if is_simulation:
            msg = f"🧪 SIMULATION SUCCESS: Processed {len(picks)} lines.\n(Data rolled back safely, no database changes made.)"
        else:
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