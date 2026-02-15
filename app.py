from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
import pyodbc

app = Flask(__name__)
app.config.from_object(Config)

# --- DB Connection Helper ---
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

# --- ROUTES ---

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
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
                
                loc_id = user.get('location_id')
                loc_code = user.get('location')
                
                if loc_id and str(loc_id).strip():
                    session['location'] = str(loc_id).strip()
                elif loc_code: 
                    session['location'] = str(loc_code).strip()
                else: 
                    session['location'] = 'Unknown'
                
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user_id_input,))
                    conn.commit()
                except Exception: pass

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
            
            # Step 1: Resolve SO
            search_term = f"%{raw_so.strip()}"
            check_sql = f"SELECT TOP 1 sono FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono LIKE ?"
            cursor.execute(check_sql, (search_term,))
            check_row = cursor.fetchone()
            
            if not check_row:
                flash(f"❌ Order '{raw_so}' not found.", "error")
                return render_template('picking.html', so=None, items=[])
            
            resolved_so = check_row[0] 
            user_loc = session.get('location', 'Unknown').strip()
            
            # Step 2: Fetch Items
            base_sql = f"""
                SELECT 
                    tranlineno, 
                    item, 
                    qtyord, 
                    shipqty, 
                    (qtyord - shipqty) as remaining,
                    loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND qtyord > shipqty
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
    
    data = request.json
    item_code = data.get('item', '').strip()
    user_loc = session.get('location', 'Unknown').strip()
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        sql = f"""
            SELECT bin, onhand, loctid 
            FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE item LIKE ? AND onhand > 0
        """
        params = [f"%{item_code}%"]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql += " AND loctid LIKE ?"
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
                'loc': r.get('loctid', '').strip()
            })
        
        return jsonify({'status': 'success', 'bins': bins})

    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        conn.close()

# --- NEW: REAL-TIME BIN VALIDATION ROUTE ---
@app.route('/validate_bin', methods=['POST'])
def validate_bin():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Login required'})

    data = request.json
    bin_loc = data.get('bin', '').strip()
    item_code = data.get('item', '').strip()
    user_loc = session.get('location', 'Unknown').strip()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Check if the scanned BIN contains the SELECTED ITEM (with positive qty)
        sql = f"""
            SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE bin=? AND item LIKE ? AND onhand > 0
        """
        params = [bin_loc, f"%{item_code}%"]
        
        # Optional: Enforce User Location (don't let ATL user pick from LA bin)
        if user_loc != '000' and user_loc != 'Unknown':
            sql += " AND loctid LIKE ?"
            params.append(f"{user_loc}%")
            
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        
        if row:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'msg': f"❌ Item '{item_code}' is NOT in Bin '{bin_loc}'"})

    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        conn.close()

@app.route('/process_scan', methods=['POST'])
def process_scan():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    
    data = request.json
    so_num = data.get('so')
    bin_loc = data.get('bin', '').strip()
    scanned_input = data.get('item', '').strip()
    qty = float(data.get('qty', 1))
    user_loc = session.get('location', 'Unknown').strip()
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. Check Order
        sql_check = f"SELECT * FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND item=?"
        params = [so_num, scanned_input]
        
        if user_loc != '000' and user_loc != 'Unknown':
            sql_check += " AND loctid LIKE ?"
            params.append(f"{user_loc}%")
            
        cursor.execute(sql_check, tuple(params))
        so_row = cursor.fetchone()
        
        if not so_row:
            return jsonify({'status': 'error', 'msg': f'Item {scanned_input} not found on Order!'})
            
        line_data = row_to_dict(cursor, so_row)
        tran_line = line_data.get('tranlineno')
        
        # 2. Re-Check Bin (Security)
        bin_check_sql = f"""
            SELECT TOP 1 onhand FROM {Config.DB_AUTH}.dbo.ScanOnhand2 
            WHERE item LIKE ? AND bin=? AND onhand > 0
        """
        cursor.execute(bin_check_sql, (f"%{scanned_input}%", bin_loc))
        bin_row = cursor.fetchone()
        
        if not bin_row:
             return jsonify({'status': 'error', 'msg': f"❌ Bin '{bin_loc}' does not contain '{scanned_input}'!"})

        # 3. Write
        try:
            insert_sql = f"""
                INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2 
                (actiontype, applid, udref, tranlineno, userid, item, binfr, quantity, deviceid, adddate, scanstat)
                VALUES ('SP', 'SO', ?, ?, ?, ?, ?, ?, 'TC52_WEB', GETDATE(), 'C')
            """
            cursor.execute(insert_sql, (so_num, tran_line, session['user_id'], scanned_input, bin_loc, qty))
            
            update_sql = f"""
                UPDATE {Config.DB_ORDERS}.dbo.SOTRAN 
                SET shipqty = shipqty + ? 
                WHERE sono=? AND item=? AND tranlineno=?
            """
            cursor.execute(update_sql, (qty, so_num, scanned_input, tran_line))
            
            conn.commit()
            return jsonify({'status': 'success', 'msg': f'Picked {scanned_input}'})

        except Exception as e:
            if "permission" in str(e).lower() or "read-only" in str(e).lower():
                rem = line_data.get('qtyord', 0) - line_data.get('shipqty', 0) - qty
                return jsonify({
                    'status': 'success', 
                    'msg': f'Picked {scanned_input} (Simulated)',
                    'remaining': rem
                })
            else:
                raise e

    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)