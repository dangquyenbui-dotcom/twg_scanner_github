from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
import pyodbc
import json

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
    conn_str = (
        f"DRIVER={app.config['DB_DRIVER']};"
        f"SERVER={app.config['DB_SERVER']};"
        f"DATABASE={app.config['DB_AUTH']};"
        f"UID={app.config['DB_UID']};"
        f"PWD={app.config['DB_PWD']};"
    )
    try:
        return pyodbc.connect(conn_str, timeout=5)
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def row_to_dict(cursor, row):
    columns = [column[0].lower() for column in cursor.description]
    return dict(zip(columns, row))

def detect_columns():
    if DB_COLS['ScanOnhand2']: return 
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        # 1. ScanOnhand2
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanOnhand2")
            cols = [c[0].lower() for c in cursor.description]
            if 'loctid' in cols: DB_COLS['ScanOnhand2'] = 'loctid'
            elif 'terr' in cols: DB_COLS['ScanOnhand2'] = 'terr'
            elif 'location_id' in cols: DB_COLS['ScanOnhand2'] = 'location_id'
            else: DB_COLS['ScanOnhand2'] = 'terr'
        except: DB_COLS['ScanOnhand2'] = 'terr'
        # 2. ScanUsers
        try:
            cursor.execute(f"SELECT TOP 1 * FROM {Config.DB_AUTH}.dbo.ScanUsers")
            cols = [c[0].lower() for c in cursor.description]
            if 'location_id' in cols: DB_COLS['ScanUsers'] = 'location_id'
            elif 'location' in cols: DB_COLS['ScanUsers'] = 'location'
            else: DB_COLS['ScanUsers'] = 'location'
        except: DB_COLS['ScanUsers'] = 'location'
        # 3. UPC Checks
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
        print(f"⚠️ Column Detection Error: {e}")
    finally:
        conn.close()

# --- ROUTES ---
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
            flash("❌ Connection to Database Failed!", "error")
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
                loc_col = DB_COLS['ScanUsers'] or 'location'
                raw_loc = user.get(loc_col)
                if raw_loc and str(raw_loc).strip():
                    session['location'] = str(raw_loc).strip()
                else: 
                    session['location'] = 'Unknown'
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user_id_input,))
                    conn.commit()
                except: pass
                return redirect(url_for('dashboard')) 
            else:
                flash("Invalid User ID or Password.", "error")
        except Exception as e:
            flash(f"Login Error: {str(e)}", "error")
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
            search_term = f"%{raw_so.strip()}"
            check_sql = f"SELECT TOP 1 sono FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono LIKE ?"
            cursor.execute(check_sql, (search_term,))
            check_row = cursor.fetchone()
            if not check_row:
                flash(f"❌ Order '{raw_so}' not found.", "error")
                return render_template('picking.html', so=None, items=[])
            resolved_so = check_row[0] 
            user_loc = session.get('location', 'Unknown').strip()
            base_sql = f"""
                SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining, loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND qtyord > shipqty
            """
            params = [resolved_so]
            if user_loc != '000' and user_loc != 'Unknown':
                base_sql += " AND loctid LIKE ?"
                params.append(f"{user_loc}%")
            base_sql += " ORDER BY tranlineno ASC"
            cursor.execute(base_sql, tuple(params))
            rows = cursor.fetchall()
            order_items = [row_to_dict(cursor, row) for row in rows]
            if not order_items:
                flash(f"✅ No open lines for {user_loc} on Order #{resolved_so.strip()}", "success")
        except Exception as e:
            flash(f"Database Error: {str(e)}", "error")
        finally:
            conn.close()
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
        conn.close()

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
            return jsonify({'status': 'error', 'msg': f"❌ Bin '{bin_loc}' does not contain '{item_code}'"})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        conn.close()

# --- NEW: BATCH PROCESS ROUTE ---
@app.route('/process_batch_scan', methods=['POST'])
def process_batch_scan():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    detect_columns()
    
    data = request.json
    picks = data.get('picks', [])
    so_num = data.get('so', '')
    user_loc = session.get('location', 'Unknown').strip()
    
    if not picks:
        return jsonify({'status': 'error', 'msg': 'No picks to submit!'})

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Validate and Process Each Pick
        processed_count = 0
        
        for pick in picks:
            scanned_input = pick.get('item', '').strip()
            bin_loc = pick.get('bin', '').strip()
            qty = float(pick.get('qty', 0))
            
            # 1. READ & VALIDATE (Order Data)
            sql_check = f"SELECT qtyord, shipqty, tranlineno FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND item=?"
            params = [so_num, scanned_input]
            if user_loc != '000' and user_loc != 'Unknown':
                sql_check += " AND loctid LIKE ?"
                params.append(f"{user_loc}%")
            cursor.execute(sql_check, tuple(params))
            so_row = cursor.fetchone()
            
            if not so_row:
                raise Exception(f"Item {scanned_input} invalid on Order")
            
            line_data = row_to_dict(cursor, so_row)
            tran_line = line_data.get('tranlineno')

            # 2. Check Bin Qty Limit
            bin_check_sql = f"SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 WHERE item LIKE ? AND bin=? AND onhand > 0"
            cursor.execute(bin_check_sql, (f"%{scanned_input}%", bin_loc))
            bin_row = cursor.fetchone()
            if not bin_row:
                 raise Exception(f"Bin '{bin_loc}' Invalid for item {scanned_input}")
            
            max_onhand = float(bin_row[0])
            if qty > max_onhand:
                 raise Exception(f"Overpick in Bin {bin_loc}! Has {int(max_onhand)}, tried {int(qty)}")

            # 3. Get UPC
            upc_code = None
            if DB_COLS['ScanItem_UPC']:
                cursor.execute(f"SELECT TOP 1 upc FROM {Config.DB_AUTH}.dbo.ScanItem WHERE item LIKE ?", (f"%{scanned_input}%",))
                upc_row = cursor.fetchone()
                if upc_row and upc_row[0]: upc_code = upc_row[0].strip()

            # 4. SIMULATED INSERT
            # In a real scenario, we would execute INSERTs here.
            processed_count += 1

        # Success for Batch
        return jsonify({
            'status': 'success', 
            'msg': f'SIMULATION: Successfully saved {processed_count} pick records!'
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'msg': f"Batch Failed: {str(e)}"})
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)