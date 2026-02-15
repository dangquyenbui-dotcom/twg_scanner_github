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
        print(f"DB Connection Error: {e}")
        return None

def row_to_dict(cursor, row):
    # Force lowercase keys for consistency
    columns = [column[0].lower() for column in cursor.description]
    return dict(zip(columns, row))

# --- ROUTES ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
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
                
                # Location Logic
                loc_id = user.get('location_id')
                loc_code = user.get('location')
                if loc_id: session['location'] = loc_id.strip()
                elif loc_code: session['location'] = str(loc_code).strip()
                else: session['location'] = 'Unknown'

                # Set Online Status (Try/Catch for Read-Only)
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user_id_input,))
                    conn.commit()
                except Exception:
                    pass

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
    
    current_so = request.args.get('so', '').strip()
    order_items = []
    
    if current_so:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Fetch Items: showing TranLineNo as 'No'
            sql = f"""
                SELECT 
                    tranlineno, 
                    item, 
                    qtyord, 
                    shipqty, 
                    (qtyord - shipqty) as remaining,
                    loctid 
                FROM {Config.DB_ORDERS}.dbo.SOTRAN 
                WHERE sono=? AND qtyord > shipqty
                ORDER BY tranlineno ASC
            """
            cursor.execute(sql, (current_so,))
            rows = cursor.fetchall()
            order_items = [row_to_dict(cursor, row) for row in rows]
            
            if not order_items:
                flash(f"Order {current_so} not found or fully picked!", "info")
                
        except Exception as e:
            flash(f"Database Error: {str(e)}", "error")
        finally:
            conn.close()

    return render_template('picking.html', so=current_so, items=order_items)

@app.route('/process_scan', methods=['POST'])
def process_scan():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Session expired'})
    
    data = request.json
    so_num = data.get('so')
    bin_loc = data.get('bin')
    scanned_input = data.get('item')
    qty = float(data.get('qty', 1))
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 1. READ: Validate Item against Order
        sql_check = f"SELECT * FROM {Config.DB_ORDERS}.dbo.SOTRAN WHERE sono=? AND item=?"
        cursor.execute(sql_check, (so_num, scanned_input))
        so_row = cursor.fetchone()
        
        if not so_row:
            return jsonify({'status': 'error', 'msg': f'Item {scanned_input} not in Order!'})
            
        line_data = row_to_dict(cursor, so_row)
        tran_line = line_data.get('tranlineno')
        
        # 2. WRITE: Attempt to Update DB
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
            # Read-Only Fallback (Simulation)
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