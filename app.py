from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
import pymysql
import datetime

app = Flask(__name__)
app.config.from_object(Config)

def get_db_connection():
    return pymysql.connect(
        host=app.config['DB_HOST'],
        user=app.config['DB_USER'],
        password=app.config['DB_PASSWORD'],
        database=app.config['DB_NAME'],
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('picking_menu'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Based on scanusers table in your doc
                sql = "SELECT * FROM scanusers WHERE userid=%s AND pw=%s"
                cursor.execute(sql, (username, password))
                user = cursor.fetchone()
                
                if user:
                    session['user_id'] = user['userid']
                    session['user_name'] = user['name']
                    return redirect(url_for('picking_menu'))
                else:
                    flash('Invalid ID or Password', 'error')
        finally:
            conn.close()
            
    return render_template('login.html')

@app.route('/picking', methods=['GET', 'POST'])
def picking_menu():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    order_items = []
    current_so = request.args.get('so', '')
    
    if current_so:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Fetch items for this Sales Order from sotran
                # Showing what is ordered vs what is shipped (picked)
                sql = """
                    SELECT tranlineno, item, qtyord, shipqty, (qtyord - shipqty) as remaining 
                    FROM sotran 
                    WHERE sono=%s AND qtyord > shipqty
                """
                cursor.execute(sql, (current_so,))
                order_items = cursor.fetchall()
        finally:
            conn.close()

    return render_template('picking.html', so=current_so, items=order_items)

@app.route('/process_scan', methods=['POST'])
def process_scan():
    if 'user_id' not in session: return jsonify({'status':'error', 'msg':'Login required'})
    
    data = request.json
    so_num = data.get('so')
    bin_loc = data.get('bin')
    item_code = data.get('item')
    qty = float(data.get('qty', 1))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Validate Item against SO
            cursor.execute("SELECT * FROM sotran WHERE sono=%s AND item=%s", (so_num, item_code))
            line_item = cursor.fetchone()
            
            if not line_item:
                return jsonify({'status': 'error', 'msg': 'Item not on this Order!'})
                
            # 2. Insert into Transaction Log (scanbintran2)
            # Mapping fields based on your doc: udref=SO, upc=Item, binfr=Bin
            insert_sql = """
                INSERT INTO scanbintran2 
                (udref, tranlineno, userid, item, binfr, quantity, adddate, actiontype, scanstat)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'PICK', 'READY')
            """
            cursor.execute(insert_sql, (
                so_num, 
                line_item['tranlineno'], 
                session['user_id'], 
                item_code, 
                bin_loc, 
                qty
            ))
            
            # 3. Update the Main Order Table (sotran)
            update_sql = "UPDATE sotran SET shipqty = shipqty + %s WHERE sono=%s AND item=%s"
            cursor.execute(update_sql, (qty, so_num, item_code))
            
            conn.commit()
            
            return jsonify({'status': 'success', 'msg': f'Picked {item_code}'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)