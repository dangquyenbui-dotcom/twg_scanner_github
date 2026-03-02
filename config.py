import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev_key_very_secret_999'
    
    # --- DATABASE CONFIG ---
    DB_DRIVER = os.environ.get('DB_DRIVER', '{ODBC Driver 17 for SQL Server}')
    DB_SERVER = os.environ.get('DB_SERVER')
    DB_UID = os.environ.get('DB_UID')
    DB_PWD = os.environ.get('DB_PWD')
    
    DB_AUTH = os.environ.get('DB_AUTH', 'PRO12')     # Inventory & Users
    DB_ORDERS = os.environ.get('DB_ORDERS', 'PRO05') # Sales Orders

    # --- SYSTEM SETTINGS ---
    # Set to False to actually UPDATE inventory and orders (LIVE MODE).
    # Set to True to only validate logic without changing data (TEST MODE).
    SIMULATION_MODE = False