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

    # --- EMAIL CONFIG (Office 365 SMTP for Bin Reports) ---
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.office365.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER = os.environ.get('SMTP_USER', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    IC_EMAIL = os.environ.get('IC_EMAIL', '')

    # --- SYSTEM SETTINGS ---
    # Set to False to actually UPDATE inventory and orders (LIVE MODE).
    # Set to True to only validate logic without changing data (TEST MODE).
    SIMULATION_MODE = False