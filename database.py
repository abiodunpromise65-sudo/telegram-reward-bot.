import sqlite3
import re
import json

DB_FILE = "bot_data.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                total_earned REAL DEFAULT 0.0,
                total_withdrawn REAL DEFAULT 0.0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Stock Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE,
                service TEXT DEFAULT 'whatsapp',
                country TEXT DEFAULT 'Default',
                status TEXT DEFAULT 'available',
                assigned_user_id INTEGER DEFAULT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Withdrawals Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Settings Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Default Settings
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('prices', ?)", (json.dumps({'whatsapp': 0.50, 'telegram': 0.30, 'other': 0.20}),))
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('required_group', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_group', '')")
        
        conn.commit()

# --- USER MANAGEMENT ---

def get_or_create_user(user_id: int, username: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
        return dict(user)

def get_all_user_ids():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        return [row['user_id'] for row in cursor.fetchall()]

def get_user_stats(user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM stock WHERE assigned_user_id = ?", (user_id,))
        received = cursor.fetchone()['cnt']
        cursor.execute("SELECT COUNT(*) as cnt FROM stock WHERE assigned_user_id = ? AND status = 'rewarded'", (user_id,))
        rewarded = cursor.fetchone()['cnt']
        return {'received': received, 'rewarded': rewarded}

# --- STOCK MANAGEMENT ---

def add_stock_bulk(numbers: list, service: str = "whatsapp", country: str = "Default") -> int:
    added = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for num in numbers:
            try:
                cursor.execute(
                    "INSERT INTO stock (phone_number, service, country) VALUES (?, ?, ?)",
                    (num, service.lower(), country)
                )
                added += 1
            except sqlite3.IntegrityError:
                continue
        conn.commit()
    return added

def remove_stock_bulk(numbers: list) -> int:
    removed = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for num in numbers:
            cursor.execute("DELETE FROM stock WHERE phone_number = ? AND status = 'available'", (num,))
            removed += cursor.rowcount
        conn.commit()
    return removed

def assign_numbers(user_id: int, service: str = "whatsapp", count: int = 3):
    with get_connection() as conn:
        cursor = conn.cursor()
        # Unassign previous active numbers for user to release pool
        cursor.execute("UPDATE stock SET assigned_user_id = NULL, status = 'available' WHERE assigned_user_id = ? AND status = 'assigned'", (user_id,))
        
        # Fetch available numbers
        cursor.execute(
            "SELECT * FROM stock WHERE status = 'available' AND service = ? LIMIT ?",
            (service.lower(), count)
        )
        available = cursor.fetchall()
        
        assigned = []
        for row in available:
            cursor.execute(
                "UPDATE stock SET assigned_user_id = ?, status = 'assigned' WHERE id = ?",
                (user_id, row['id'])
            )
            assigned.append(dict(row))
        conn.commit()
        return assigned

def get_user_assigned_numbers(user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock WHERE assigned_user_id = ? AND status = 'assigned'", (user_id,))
        return [dict(r) for r in cursor.fetchall()]

def get_stock_summary():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT service, status, COUNT(*) as count FROM stock GROUP BY service, status")
        rows = cursor.fetchall()
        summary = {}
        for r in rows:
            svc = r['service']
            if svc not in summary:
                summary[svc] = {'available': 0, 'assigned': 0, 'rewarded': 0}
            summary[svc][r['status']] = r['count']
        return summary

# --- MATCHING & REWARDS ---

def match_and_reward_number(text: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        extracted = re.findall(r'\+?\d{7,15}', text)
        if not extracted:
            return None
        
        for phone in extracted:
            cursor.execute("SELECT * FROM stock WHERE phone_number = ? AND status = 'assigned'", (phone,))
            stock_item = cursor.fetchone()
            if stock_item:
                stock_dict = dict(stock_item)
                service = stock_dict['service']
                
                prices = get_prices()
                reward_price = prices.get(service, 0.50)
                
                user_id = stock_dict['assigned_user_id']
                
                # Mark as rewarded
                cursor.execute("UPDATE stock SET status = 'rewarded' WHERE id = ?", (stock_dict['id'],))
                # Credit balance
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?",
                    (reward_price, reward_price, user_id)
                )
                conn.commit()
                return stock_dict, reward_price, phone
    return None

# --- WITHDRAWALS ---

def create_withdrawal(user_id: int, amount: float, details: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user or user['balance'] < amount:
            return False, "Insufficient balance."
        
        # Deduct balance temporarily
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        cursor.execute(
            "INSERT INTO withdrawals (user_id, amount, details) VALUES (?, ?, ?)",
            (user_id, amount, details)
        )
        conn.commit()
        return True, "Withdrawal request submitted successfully."

def get_pending_withdrawals():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM withdrawals WHERE status = 'pending'")
        return [dict(r) for r in cursor.fetchall()]

def process_withdrawal(withdrawal_id: int, status: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,))
        w = cursor.fetchone()
        if not w or w['status'] != 'pending':
            return False
        
        if status == 'approved':
            cursor.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (withdrawal_id,))
            cursor.execute("UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (w['amount'], w['user_id']))
        elif status == 'rejected':
            cursor.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (withdrawal_id,))
            # Refund balance
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (w['amount'], w['user_id']))
            
        conn.commit()
        return dict(w)

# --- SETTINGS & STATS ---

def get_prices():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'prices'")
        row = cursor.fetchone()
        return json.loads(row['value']) if row else {'whatsapp': 0.50, 'telegram': 0.30, 'other': 0.20}

def set_prices(prices: dict):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'prices'", (json.dumps(prices),))
        conn.commit()

def set_setting(key: str, value: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def get_setting(key: str, default: str = ""):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default

def get_admin_stats():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM users")
        total_users = cursor.fetchone()['cnt']
        
        cursor.execute("SELECT COUNT(*) as cnt FROM stock WHERE status = 'available'")
        total_available = cursor.fetchone()['cnt']
        
        cursor.execute("SELECT COUNT(*) as cnt FROM stock WHERE status = 'rewarded'")
        total_rewarded = cursor.fetchone()['cnt']
        
        cursor.execute("SELECT SUM(total_earned) as total FROM users")
        row = cursor.fetchone()
        total_payouts = row['total'] if row['total'] else 0.0
        
        return {
            'users': total_users,
            'available_stock': total_available,
            'rewarded_stock': total_rewarded,
            'total_payouts': total_payouts
        }
        
      
