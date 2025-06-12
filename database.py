import datetime
import os
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
    """初始化数据库，创建表和默认设置。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            # 创建 orders 表，添加 order_id 列并设置唯一约束, 这里的order_id对应的是订单的name字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    order_json TEXT,
                    status TEXT DEFAULT '未打印',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # 创建 settings 表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT
                )
            ''')
            # 插入默认设置项
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_printer', '')")
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_print_enabled', 'false')")
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('polling_enabled', 'false')")
            #cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('print_method', 'text')")
            conn.commit()

def get_setting(key):
    """获取指定设置项的值。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None
    return None

def set_setting(key, value):
    """设置或更新应用配置。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

def insert_or_update_order(order_data):
    """插入或更新订单。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            order_id = order_data.get("order_id")  # 使用 order_id (即订单的 name)
            if not order_id:
                logger.error("订单数据中缺少 'order_id' 字段。")
                return None

            # 检查订单是否已存在
            existing_order = cursor.execute("SELECT id FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            order_json_str = json.dumps(order_data, ensure_ascii=False)

            if existing_order:
                # 更新现有订单
                cursor.execute("UPDATE orders SET order_json=?, status=? WHERE order_id=?",
                               (order_json_str, "未打印", order_id)) # 使用 order_id 更新
                logger.info(f"更新订单 {order_id}。")
                return existing_order["id"]
            else:
                # 插入新订单
                cursor.execute("INSERT INTO orders (order_id, order_json, status) VALUES (?, ?, ?)",
                               (order_id, order_json_str, "未打印"))
                conn.commit()
                logger.info(f"插入新订单 {order_id}。")
                return cursor.lastrowid
    return None

# 在 database.py 中

def update_order(db_id, status, other_fields=None): # 1. 参数名从 order_id 改为 db_id，更清晰
    """更新订单状态和其他字段，基于数据库主键 ID。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            update_query = "UPDATE orders SET status=?"
            params = [status]

            if other_fields:
                for key, value in other_fields.items():
                    update_query += f", {key}=?"
                    params.append(value)

            update_query += " WHERE id=?"  # 2. SQL查询条件改为 WHERE id=?
            params.append(db_id)          # 3. 将传入的 db_id 作为参数

            cursor.execute(update_query, params)
            conn.commit()
            logger.info(f"更新数据库订单记录 ID {db_id} 的状态为 {status}。")

def get_all_orders():
    """获取所有订单，按 ID 降序排列。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, order_id, order_json, status, created_at FROM orders ORDER BY id DESC")
            rows = cursor.fetchall()
            orders = []
            for row in rows:
                try:
                    order_json = json.loads(row["order_json"])
                    # 确保 order_json 中包含 order_id 字段
                    if "order_id" not in order_json:
                        order_json["order_id"] = row["order_id"]
                except json.JSONDecodeError:
                    logger.error(f"解析订单 JSON 失败，订单 ID: {row['id']}")
                    order_json = {"order_id": row["order_id"]}  # 至少包含 order_id
                orders.append({
                    "id": row["id"],
                    "order_id": row["order_id"],
                    "order_json": order_json,
                    "status": row["status"],
                    "created_at": row["created_at"],
                })
            return orders
    return []

def get_order_by_db_id(db_id): # 1. 函数名和参数名修改，表明是通过数据库ID查询
    """通过数据库主键 ID 获取订单。"""
    with get_db_connection() as conn:
        if conn:
            cursor = conn.cursor()
            # 2. SQL查询条件改为 WHERE id=?
            cursor.execute("SELECT id, order_id, order_json, status, created_at FROM orders WHERE id=?", (db_id,))
            row = cursor.fetchone()
            if row:
                try:
                    order_json = json.loads(row["order_json"])
                    if "order_id" not in order_json:
                        order_json["order_id"] = row["order_id"]
                except json.JSONDecodeError:
                    logger.error(f"解析订单 JSON 失败，数据库 ID: {row['id']}")
                    order_json = {"order_id": row["order_id"]}
                return {
                    "id": row["id"],
                    "order_id": row["order_id"],
                    "order_json": order_json,
                    "status": row["status"],
                    "created_at": row["created_at"], # 从数据库记录中获取创建时间
                }
    return None