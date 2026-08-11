import sqlite3
import re
from typing import List, Dict, Optional, Tuple

def get_db():
    conn = sqlite3.connect("bot_data.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            total_earned REAL DEFAULT 0.0,
            total_withdrawn REAL DEFAULT 0.0
        )
    ''')
    
    # Stock Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT NOT NULL,
            country TEXT NOT NULL,
            phone_number TEXT NOT NULL UNIQUE,
            normalized_number TEXT NOT NULL,
            reward_price REAL NOT NULL,
            status TEXT DEFAULT 'available',
            assigned_user_id INTEGER DEFAULT NULL
        )
    ''')
    
    # Withdrawals Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            details TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    # System Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def normalize_phone(phone: str) -> str:
    """Strips all non-digit characters (+234 -> 234, spaces, dashes)."""
    return re.sub(r'\D', '', phone)

# User Operations
def get_or_create_user(user_id: int, username: str) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, total_earned, total_withdrawn) VALUES (?, ?, 0.0, 0.0, 0.0)",
            (user_id, username)
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    conn.close()
    return dict(row)

def update_user_balance(user_id: int, amount: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET balance = balance + ?, total_earned = total_earned + ? 
        WHERE user_id = ?
    """, (amount, amount, user_id))
    conn.commit()
    conn.close()

# Stock & Assignment Operations
def assign_numbers(user_id: int, service: str, country: Optional[str] = None, count: int = 3) -> List[dict]:
    conn = get_db()
    cursor = conn.cursor()
    
    # Release previous assigned numbers for this user that are not rewarded yet
    cursor.execute("""
        UPDATE stock 
        SET status = 'available', assigned_user_id = NULL 
        WHERE assigned_user_id = ? AND status = 'assigned'
    """, (user_id,))
    
    # Select available stock
    if country:
        cursor.execute("""
            SELECT * FROM stock 
            WHERE service = ? AND country = ? AND status = 'available' 
            LIMIT ?
        """, (service, country, count))
    else:
        cursor.execute("""
            SELECT * FROM stock 
            WHERE service = ? AND status = 'available' 
            LIMIT ?
        """, (service, count))
        
    available = cursor.fetchall()
    assigned_numbers = []
    
    for row in available:
        cursor.execute("""
            UPDATE stock 
            SET status = 'assigned', assigned_user_id = ? 
            WHERE id = ?
        """, (user_id, row['id']))
        assigned_numbers.append(dict(row))
        
    conn.commit()
    conn.close()
    return assigned_numbers

def get_user_assigned_numbers(user_id: int) -> List[dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stock WHERE assigned_user_id = ? AND status = 'assigned'", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def match_and_reward_number(text: str) -> Optional[Tuple[dict, float, str]]:
    """
    Parses text, normalizes phone candidates, checks assigned stock,
    and credits balance if matched. Prevents duplicates.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Extract digit streams >= 7 digits
    candidates = re.findall(r'\+?\d[\d\s-]{6,14}\d', text)
    
    for cand in candidates:
        norm = normalize_phone(cand)
        cursor.execute("""
            SELECT * FROM stock 
            WHERE normalized_number = ? AND status = 'assigned'
        """, (norm,))
        matched = cursor.fetchone()
        
        if matched:
            stock_id = matched['id']
            user_id = matched['assigned_user_id']
            reward = matched['reward_price']
            phone = matched['phone_number']
            
            # Mark stock as rewarded
            cursor.execute("UPDATE stock SET status = 'rewarded' WHERE id = ?", (stock_id,))
            
            # Credit user balance safely
            cursor.execute("""
                UPDATE users 
                SET balance = balance + ?, total_earned = total_earned + ? 
                WHERE user_id = ?
            """, (reward, reward, user_id))
            
            conn.commit()
            conn.close()
            return (dict(matched), reward, phone)
            
    conn.close()
    return None
      
