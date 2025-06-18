# app.py (生产环境最终版)

import datetime
import hashlib
import json
import logging
import os
import subprocess
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort

# 导入我们的Linux专用打印助手
import print_helper
import print_helper_pdf
from database import (
    init_db, get_setting, set_setting,
    insert_or_update_order, get_all_orders, update_order, get_order_by_db_id
)
from token_manager import get_allvalue_access_token

DATA_DIR = 'data'
TIME_FILE = os.path.join(DATA_DIR, "uptime.json")
app = Flask(__name__)

# --- 日志和全局配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

shop = os.environ.get("SHOP_NAME", "一品滋味")
ALLVALUE_GRAPHQL_ENDPOINT = f"https://{shop}.myallvalue.com/admin/api/open/graphql/v202108"
ALLVALUE_WEBHOOK_SECRET = os.environ.get("ALLVALUE_WEBHOOK_SECRET")

scheduler = BackgroundScheduler(timezone="UTC")


# --- 辅助函数 ---

def get_printers():
    """在Linux上使用 lpstat 获取已配置的打印机列表。"""
    try:
        result = subprocess.run(['lpstat', '-p'], check=True, capture_output=True, text=True, encoding='utf-8')
        printers = [line.split(' ')[1] for line in result.stdout.strip().split('\n') if line.startswith('printer')]
        app.logger.info(f"发现Linux打印机: {printers}")
        return printers
    except Exception as e:
        app.logger.error(f"获取Linux打印机列表时出错: {e}")
        return []



def dispatch_print_job(order_data, printer_name, print_method):
    """根据打印方法设置，分发打印任务到相应的打印助手。"""
    if 'shop_name' not in order_data or not order_data['shop_name']:
        order_data['shop_name'] = shop

    actual_print_method = print_method or 'escpos'
    app.logger.info(
        f"分发打印任务：订单ID {order_data.get('order_id')}，方式: {actual_print_method}, 打印机: {printer_name}")

    success = False
    if actual_print_method == 'pdf':
        success = print_helper_pdf.print_order(order_data, printer_name=printer_name)
    else:  # 'escpos'
        success = print_helper.print_order(order_data, printer_name=printer_name)

    if success:
        app.logger.info(f"订单 {order_data.get('order_id')} 的打印任务已成功分发。")
    else:
        app.logger.error(f"订单 {order_data.get('order_id')} 分发打印任务失败。")
    return success


# --- 核心业务逻辑函数 ---
def record_uptime(end_time=None):
    data = {}
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f: data = json.load(f)
    except Exception as e:
        app.logger.warning(f"读取uptime.json时出错: {e}，将创建新文件。")
    if end_time: data["end_time"] = end_time.isoformat()
    try:
        with open(TIME_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        app.logger.error(f"写入 uptime.json 文件失败: {e}")


def get_last_uptime():
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                end_time_str = data.get("end_time")
                if end_time_str: return datetime.datetime.fromisoformat(end_time_str)
        return None
    except Exception as e:
        app.logger.error(f"读取{TIME_FILE}文件失败:{e}")
        return None


def to_millis(dt: datetime.datetime) -> int:
    utc_dt = dt.astimezone(datetime.timezone.utc) if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    return int((utc_dt - epoch).total_seconds() * 1000)


def fetch_missing_orders(start_time):
    access_token = get_allvalue_access_token()
    if not access_token: return []
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_ts, end_ts = to_millis(start_time), to_millis(end_time)
    if start_ts >= end_ts: return []
    gql_query = """query Orders($query: String!, $first: Int!, $after: String) { orders(query: $query, first: $first, after: $after) { edges { cursor, node { nodeId, name } }, pageInfo { hasNextPage } } }"""
    headers = {"Custom-AllValue-Access-Token": access_token}
    orders, has_next_page, after_cursor = [], True, None
    filter_str = f"created_at_range:[{start_ts} TO {end_ts}] AND financial_state:PAID"
    while has_next_page:
        variables = {"query": filter_str, "first": 50, "after": after_cursor}
        try:
            resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers,
                                 json={"query": gql_query, "variables": variables}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data and data["errors"]: app.logger.error(f"GraphQL Error: {data['errors']}"); break
            orders_conn = data.get("data", {}).get("orders", {})
            edges = orders_conn.get("edges", [])
            orders.extend([edge["node"] for edge in edges if edge.get("node")])
            page_info = orders_conn.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            if edges: after_cursor = edges[-1].get("cursor")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"请求遗漏订单失败: {e}"); break
    return orders


def poll_orders():
    """轮询获取遗漏订单的任务函数。"""
    with app.app_context():  # 确保在Flask应用上下文中运行
        app.logger.info("开始轮询获取遗漏订单...")
        start_time = get_last_uptime() or (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1))
        missing_orders = fetch_missing_orders(start_time)
        if missing_orders:
            app.logger.info(f"发现 {len(missing_orders)} 个遗漏订单")
            for order in missing_orders:
                process_order_webhook(order.get("nodeId"), should_print=get_setting('auto_print_enabled') == 'true')
        record_uptime(datetime.datetime.now(datetime.timezone.utc))


# --- Flask 路由 ---
@app.route("/")
def index():
    orders = get_all_orders()
    return render_template("index.html", orders=orders)


@app.route("/print/<int:db_id>")
def print_order_route(db_id):
    order_record = get_order_by_db_id(db_id)
    if not order_record: return "订单未找到", 404
    printer_name = get_setting('default_printer')

    # 仅测试用
    # if not printer_name:
    #     app.logger.warning("本地Docker测试：未在数据库中找到打印机设置，将使用'dummy_printer'作为占位符继续。")
    #     printer_name = "dummy_printer"

    if not printer_name: return "打印失败：未设置目标打印机。", 500
    print_method = get_setting('print_method') or 'escpos'
    success = dispatch_print_job(order_record["order_json"], printer_name, print_method)
    if success:
        update_order(db_id, "已打印")
        return redirect(url_for('index'))
    return f"打印失败 (方式: {print_method})。请检查应用日志。", 500


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        set_setting("default_printer", request.form.get("default_printer"))
        set_setting("auto_print_enabled", 'true' if request.form.get("auto_print_enabled") == 'on' else 'false')
        set_setting("print_method", request.form.get("print_method"))
        polling_enabled_new = request.form.get("polling_enabled") == 'on'
        set_setting("polling_enabled", 'true' if polling_enabled_new else 'false')

        job = scheduler.get_job('poll_orders_job')
        if polling_enabled_new and not job:
            scheduler.add_job(func=poll_orders, trigger="interval", hours=1, id='poll_orders_job')
            if not scheduler.running: scheduler.start()
            app.logger.info("已启动轮询任务。")
        elif not polling_enabled_new and job:
            job.remove()
            app.logger.info("已停止轮询任务。")

        return redirect(url_for("settings"))

    return render_template("settings.html",
                           default_printer=get_setting('default_printer'),
                           auto_print_enabled=get_setting('auto_print_enabled') == 'true',
                           polling_enabled=get_setting('polling_enabled') == 'true',
                           print_method=get_setting('print_method') or 'escpos',
                           printers=get_printers())


# --- Webhook 和订单处理逻辑 ---
class OrderProcessingError(Exception): pass


def verify_webhook_signature(request):
    md5_received = request.headers.get('X-AllValue-MD5')
    if not md5_received or not ALLVALUE_WEBHOOK_SECRET: return False
    message = request.get_data()
    md5_calculated = hashlib.md5(f"{message.decode('utf-8')}{ALLVALUE_WEBHOOK_SECRET}".encode('utf-8')).hexdigest()
    return md5_calculated == md5_received


def parse_order_data(raw_order_data):
    if not raw_order_data: raise ValueError("传入的原始订单数据为空。")
    shipping_addr, cust = raw_order_data.get("shippingAddress", {}), raw_order_data.get("customer", {})
    total_price_obj = raw_order_data.get("totalPrice", {}).get("shopMoney", {})
    return {
        "order_id": raw_order_data.get("name"), "created_at": raw_order_data.get("createdAt"),
        "contact_email": raw_order_data.get("contactEmail"), "customer_message": raw_order_data.get("customerMessage"),
        "shipping_address": {"firstName": shipping_addr.get("firstName"), "lastName": shipping_addr.get("lastName"),
                             "phone": shipping_addr.get("phone"), "address1": shipping_addr.get("address1"),
                             "address2": shipping_addr.get("address2"), "zip": shipping_addr.get("zip"),
                             "countryCode": shipping_addr.get("countryCode")},
        "line_items": [{"name": i.get("name"), "quantity": i.get("quantity"),
                        "option_values": [ov.get("name") for ov in i.get("optionValues", [])]} for i in
                       raw_order_data.get("lineItems", [])],
        "total_price": {"amount": total_price_obj.get("amount"), "currency_code": total_price_obj.get("currencyCode")},
        "customer_info": {"firstName": cust.get("firstName"), "lastName": cust.get("lastName")},
    }


def fetch_order_details(access_token, node_id):
    """通过GraphQL API获取单个订单的详细信息。"""
    gql_query = """query OrderDetails($nodeId: NodeID!) { order(nodeId: $nodeId) { name, createdAt, contactEmail, customerMessage, shippingAddress { firstName, lastName, phone, address1, address2, zip, countryCode }, lineItems { name, quantity, optionValues { name } }, totalPrice { shopMoney { amount, currencyCode } }, customer { firstName, lastName } } }"""
    variables = {"nodeId": node_id}
    payload = {"query": gql_query, "variables": variables}
    headers = {"Custom-AllValue-Access-Token": access_token}

    resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data and data["errors"]:
        raise OrderProcessingError(f"GraphQL Error: {data['errors']}")

    return data["data"]["order"]


def persist_order_data(order_data):
    if not order_data: raise OrderProcessingError("尝试持久化的订单数据为空。")
    return insert_or_update_order(order_data)


def print_order_if_enabled(order_data, db_order_id, should_print=True):
    if get_setting('auto_print_enabled') != 'true' or not should_print:
        update_order(db_order_id, "未打印 (自动打印禁用或无需)")
        return None
    printer_name = get_setting('default_printer')
    if not printer_name:
        update_order(db_order_id, "打印失败 (未配置打印机)")
        return False
    print_method = get_setting('print_method') or 'escpos'
    success = dispatch_print_job(order_data, printer_name, print_method)
    update_order(db_order_id, "已打印" if success else "打印失败")
    return success


def process_order_webhook(order_node_id, should_print=True):
    db_order_id = None
    try:
        access_token = get_allvalue_access_token()
        raw_order_data = fetch_order_details(access_token, order_node_id)
        order_data = parse_order_data(raw_order_data)
        db_order_id = persist_order_data(order_data)
        if not db_order_id: raise OrderProcessingError("持久化订单失败")
        print_order_if_enabled(order_data, db_order_id, should_print)
        return True
    except Exception as e:
        app.logger.error(f"处理订单 {order_node_id} 失败: {e}", exc_info=True)
        if db_order_id:
            error_msg = str(e).replace("'", "").replace('"', '')[:50]
            update_order(db_order_id, f"处理错误: {error_msg}")
        return False


@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if get_setting('polling_enabled') == 'true': return jsonify({"status": "ignored"}), 200
    if not verify_webhook_signature(request): abort(401)
    data = request.get_json()
    if not data: abort(400)
    topic = request.headers.get('X-AllValue-Topic')
    if topic and topic.startswith('orders/'):
        order_node_id = data.get("nodeId")
        if not order_node_id: return jsonify({"status": "fail", "msg": "no nodeId"}), 400
        if process_order_webhook(order_node_id): return jsonify({"status": "success"}), 200
        return jsonify({"status": "fail", "msg": "Failed to process"}), 500
    return jsonify({"status": "fail", "msg": f"Unknown topic: {topic}"}), 400


# --- 应用启动时的主动初始化逻辑 ---
def startup_tasks():
    """在应用启动时执行的任务，独立于任何Web请求。"""
    with app.app_context():  # 确保在Flask应用上下文中执行
        app.logger.info("应用启动，开始执行启动任务...")
        init_db()  # 1. 初始化数据库

        # 2. 检查轮询设置并启动调度器
        polling_enabled = get_setting('polling_enabled') == 'true'
        if polling_enabled:
            job = scheduler.get_job('poll_orders_job')
            if not job:
                scheduler.add_job(func=poll_orders, trigger="interval", hours=1, id='poll_orders_job')
            if not scheduler.running:
                scheduler.start()
                app.logger.info("后台轮询任务已在应用启动时启动。")
        else:
            app.logger.info("后台轮询任务在设置中被禁用。")

        # 3. 首次启动时检查一次遗漏订单
        app.logger.info("应用启动时，执行一次遗漏订单检查...")
        poll_orders()
        app.logger.info("启动任务执行完毕。")


# --- 启动 ---
if __name__ == "__main__":
    startup_tasks()  # 确保在开发模式下也执行启动任务
    app.run(host='0.0.0.0', port=5000, debug=True)
else:
    startup_tasks()