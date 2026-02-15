from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
import pyodbc

app = Flask(__name__)
app.config.from_object(Config)

def get_db_connection():
    """Connects to SQL Server using details from .env"""
    conn_str = (
        f"DRIVER={app.config['DB_DRIVER']};"
        f"SERVER={app.config['DB_SERVER']};"
        f"DATABASE={app.config['DB_AUTH']};"
        f"UID={app.config['DB_UID']};"
        f"PWD={app.config['DB_PWD']};"
    )
    try:
        # Timeout set to 5 seconds to fail fast if DB is down
        return pyodbc.connect(conn_str, timeout=5)
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def row_to_dict(cursor, row):
    """Helper to convert SQL rows to dictionaries"""
    return dict(zip([column[0] for column in cursor.description], row))

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('picking_menu'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # .strip() removes accidental spaces from scanner input
        user_id_input = request.form['userid'].strip().upper()
        password_input = request.form['password']
        
        conn = get_db_connection()
        if not conn:
            flash("❌ Connection to Database Failed!", "error")
            return render_template('login.html')

        try:
            cursor = conn.cursor()
            # 1. Verify Credentials
            # We match strictly on ID and Password.
            sql = f"SELECT * FROM {Config.DB_AUTH}.dbo.ScanUsers WHERE userid=? AND pw=?"
            cursor.execute(sql, (user_id_input, password_input))
            row = cursor.fetchone()
            
            if row:
                user = row_to_dict(cursor, row)
                
                # 2. Success - Setup Session
                session['user_id'] = user['userid'].strip()
                session['user_name'] = user['name']
                # Capture the text location (e.g., 'ATL', 'LA')
                session['location'] = user['location_id'].strip() if user['location_id'] else 'Unknown'

                # 3. Update Status to 1 (Online)
                # We wrap this in a try/except so Read-Only accounts (svcpowerbi) can still login
                try:
                    update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=1 WHERE userid=?"
                    cursor.execute(update_sql, (user['userid'],))
                    conn.commit()
                except Exception as e:
                    print(f"Warning: Could not update status (likely Read-Only DB): {e}")

                return redirect(url_for('picking_menu'))
            else:
                flash("Invalid User ID or Password.", "error")
                
        except Exception as e:
            flash(f"Login Error: {str(e)}", "error")
        finally:
            conn.close()
            
    return render_template('login.html')

@app.route('/picking', methods=['GET'])
def picking_menu():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    current_so = request.args.get('so', '').strip()
    order_items = []
    
    if current_so:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Read Order from PRO05.SOTRAN
            # Showing items that still need picking (qtyord > shipqty)
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
            else:
                # Optional: Check if order location matches user location
                order_loc = order_items[0].get('loctid', '').strip()
                user_loc = session.get('location', '')
                if order_loc and user_loc and order_loc != user_loc:
                     flash(f"⚠️ Warning: This order is for {order_loc}, but you are in {user_loc}", "warning")
                
        except Exception as e:
            flash(f"Database Error: {str(e)}", "error")
        finally:
            conn.close()

    return render_template('picking.html', so=current_so, items=order_items)

@app.route('/process_scan', methods=['POST'])
def process_scan():
    """
    Handles the picking logic.
    """
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
        tran_line = line_data['tranlineno']
        
        # 2. WRITE: Attempt to Update DB
        try:
            # Insert Transaction
            insert_sql = f"""
                INSERT INTO {Config.DB_AUTH}.dbo.ScanBinTran2 
                (actiontype, applid, udref, tranlineno, userid, item, binfr, quantity, deviceid, adddate, scanstat)
                VALUES ('SP', 'SO', ?, ?, ?, ?, ?, ?, 'TC52_WEB', GETDATE(), 'C')
            """
            cursor.execute(insert_sql, (so_num, tran_line, session['user_id'], scanned_input, bin_loc, qty))
            
            # Update Order Qty
            update_sql = f"""
                UPDATE {Config.DB_ORDERS}.dbo.SOTRAN 
                SET shipqty = shipqty + ? 
                WHERE sono=? AND item=? AND tranlineno=?
            """
            cursor.execute(update_sql, (qty, so_num, scanned_input, tran_line))
            
            conn.commit()
            return jsonify({'status': 'success', 'msg': f'Picked {scanned_input}'})

        except Exception as e:
            # Fallback for Read-Only credentials (Simulation Mode)
            if "permission" in str(e).lower() or "read-only" in str(e).lower():
                return jsonify({
                    'status': 'success', 
                    'msg': f'Picked {scanned_input} (Simulated - Read Only)',
                    'remaining': line_data['qtyord'] - line_data['shipqty'] - qty
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
    # Attempt to set status to 0 (Offline) before clearing session
    if 'user_id' in session:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                update_sql = f"UPDATE {Config.DB_AUTH}.dbo.ScanUsers SET userstat=0 WHERE userid=?"
                cursor.execute(update_sql, (session['user_id'],))
                conn.commit()
            except Exception:
                pass # Ignore DB errors on logout
            finally:
                conn.close()
                
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)