import sqlite3
import json
import logging

DB_NAME = 'orders.db'
logger = logging.getLogger(__name__)

def get_db_connection():
    """获取数据库连接（使用上下文管理器）。"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row  # 使查询结果可以通过字段名访问
        return conn
    except sqlite3.Error as e:
        logger.error(f"数据库连接错误: {e}")
        return None

def init_db():
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_json TEXT,
                    status TEXT DEFAULT '未打印',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT
                )
            ''')
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_printer', '')")
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_print_enabled', 'false')")
            conn.commit()

def get_setting(key):
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None
        return None

def set_setting(key, value):
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
            conn.commit()

def insert_or_update_order(order_data):
    """插入或更新订单。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            existing_order = cursor.execute("SELECT id FROM orders WHERE order_json LIKE ?", ('%'+order_data["order_id"]+'%',)).fetchone()
            order_json_str = json.dumps(order_data, ensure_ascii=False)
            if existing_order:
                cursor.execute("UPDATE orders SET order_json=? WHERE id=?", (order_json_str, existing_order[0]))
            else:
                cursor.execute("INSERT INTO orders (order_json, status) VALUES (?, ?)", (order_json_str, "未打印"))
            conn.commit()
            return cursor.lastrowid if not existing_order else existing_order[0]
        return None

def update_order(order_id, status, other_fields=None):
     with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            update_query = "UPDATE orders SET status=?"
            params = [status]
            if other_fields:
                for key, value in other_fields.items():
                    update_query += f", {key}=?"
                    params.append(value)
            update_query += " WHERE id=?"
            params.append(order_id)
            cursor.execute(update_query, params)
            conn.commit()

def get_all_orders():
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, order_json, status FROM orders ORDER BY id DESC")
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "order_json": json.loads(r["order_json"]),
                    "status": r["status"],
                } for r in rows
            ]
        return []

def get_order_by_id(order_id):
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, order_json, status FROM orders WHERE id=?", (order_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "order_json": json.loads(row["order_json"]),
                    "status": row["status"],
                }
        return None