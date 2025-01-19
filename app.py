import datetime
import hashlib
import json
import logging
import os

import requests
import win32print
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort

import print_helper
import print_helper_old
from database import (
    init_db, get_setting, set_setting,
    insert_or_update_order, get_all_orders, update_order, get_order_by_id
)
from token_manager import get_allvalue_access_token

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

shop = ""
ALLVALUE_GRAPHQL_ENDPOINT = f"https://{shop}.myallvalue.com/admin/api/open/graphql/v202108"
ALLVALUE_WEBHOOK_SECRET = os.environ.get("ALLVALUE_WEBHOOK_SECRET")
TIME_FILE = "uptime.json"
first_request = True
scheduler_started = False

# 初始化 APScheduler
scheduler = BackgroundScheduler()

def record_uptime(end_time=None):
    """记录时间到 uptime.json。"""
    data = {}
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except json.JSONDecodeError:
        app.logger.warning("uptime.json 文件损坏，重新创建。")
    except FileNotFoundError:
        app.logger.warning("uptime.json 文件不存在，创建新文件")
    except IOError as e:
        app.logger.error(f"读取uptime.json文件失败:{e}")

    # 只记录 end_time
    if end_time:
        data["end_time"] = end_time.isoformat()

    try:
        with open(TIME_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        app.logger.error(f"写入 uptime.json 文件失败: {e}")

def get_last_uptime():
    """获取上次记录的 end_time（UTC）。"""
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                end_time_str = data.get("end_time")
                if end_time_str:
                    app.logger.info(f"从 {TIME_FILE} 中读取时间: end_time={end_time_str}")
                    return datetime.datetime.fromisoformat(end_time_str) # 只返回 end_time
        else:
            app.logger.warning(f"{TIME_FILE}文件不存在")
            return None
    except Exception as e:
        app.logger.error(f"读取{TIME_FILE}文件失败:{e}")
        return None

def to_millis(dt: datetime.datetime) -> int:
    """将Python datetime转成UTC毫秒时间戳"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    delta = dt - epoch
    return int(delta.total_seconds() * 1000)

def fetch_missing_orders(start_time):
    """请求指定时间段内的遗漏订单，支持分页，使用毫秒级 created_at_range。"""
    if not start_time:
        app.logger.warning("开始时间为空，无法请求遗漏订单。")
        return []

    access_token = get_allvalue_access_token()
    if not access_token:
        app.logger.error("无法获取 AllValue 访问令牌，无法请求遗漏订单。")
        return []

    end_time = datetime.datetime.utcnow() # 获取当前时间作为结束时间
    start_ts = to_millis(start_time)
    end_ts = to_millis(end_time)

    if start_ts > end_ts:
        app.logger.error("start_ts 大于 end_ts，无法请求遗漏订单。")
        return []

    # 使用正确的 GraphQL 查询语句
    gql_query = """
    query Orders($query: String!, $first: Int!, $after: String) {
      orders(query: $query, first: $first, after: $after) {
        edges {
          cursor
          node {
            nodeId
            name
          }
        }
        pageInfo {
          hasNextPage
        }
      }
    }
    """

    headers = {
        "Custom-AllValue-Access-Token": access_token
    }

    orders = []
    has_next_page = True
    after_cursor = None
    page_size = 50  # 每次请求50个订单

    # 构建查询字符串，使用 created_at_range 过滤
    filter_str = f"created_at_range:[{start_ts} TO {end_ts}]"
    app.logger.debug(f"Filter string: {filter_str}")

    while has_next_page:
        variables = {
            "query": filter_str,
            "first": page_size,
            "after": after_cursor
        }

        try:
            resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, json={"query": gql_query, "variables": variables}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if "errors" in data:
                app.logger.error(f"GraphQL Error: {data['errors']}")
                break

            orders_conn = data.get("data", {}).get("orders", {})
            edges = orders_conn.get("edges", [])
            for edge in edges:
                node = edge.get("node")
                if node:
                    orders.append(node)  # 只保存 nodeId 和 name

            page_info = orders_conn.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            if edges:  # 避免 edges 为空时报错
                after_cursor = edges[-1].get("cursor")

        except requests.exceptions.Timeout:
            app.logger.error("请求遗漏订单超时")
            break
        except requests.exceptions.RequestException as e:
            app.logger.error(f"请求遗漏订单失败: {e}")
            break
        except Exception as e:
            app.logger.exception(f"获取遗漏订单时发生未知错误: {e}")
            break

    return orders

def poll_orders():
    """轮询获取遗漏订单的任务函数。"""
    app.logger.info("开始轮询获取遗漏订单...")
    start_time = get_last_uptime()
    end_time = datetime.datetime.utcnow()
    if start_time is None:
        start_time = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    if start_time and start_time < end_time:
        app.logger.info(f"轮询时间范围：{start_time} 到 {end_time}")
        missing_orders = fetch_missing_orders(start_time, end_time)
        if missing_orders:
            app.logger.info(f"发现 {len(missing_orders)} 个遗漏订单")
            for order in missing_orders:
                order_id = order.get("nodeId")  # 从 fetch_missing_orders 的返回结果中提取 nodeId
                try:
                    # 传递 nodeId 给 process_order_webhook
                    process_order_webhook(order_id, should_print=get_setting('auto_print_enabled') == 'true')
                    app.logger.info(f"成功补齐订单：{order_id}")
                except OrderProcessingError as e:
                    app.logger.error(f"补齐订单 {order_id} 失败: {e}")
                except Exception as e:
                    app.logger.exception(f"补齐订单 {order_id} 时发生未知错误: {e}")
        else:
            app.logger.info("未发现遗漏订单。")
    else:
        app.logger.info("没有需要轮询的时间范围。")
    record_uptime(end_time=datetime.datetime.utcnow())

@app.before_request
def initialize():
    """在应用首次请求前初始化相关功能。"""
    global first_request
    global scheduler_started
    if first_request:
        init_db()

        polling_enabled = get_setting('polling_enabled') == 'true'

        if polling_enabled:
            if not scheduler_started:
                scheduler.add_job(func=poll_orders, trigger="interval", hours=1, id='poll_orders_job')
                scheduler.start()
                scheduler_started = True
                app.logger.info("已启动轮询任务。")
        else:
            app.logger.info("轮询任务未启用。")

        # 首次请求时也检查遗漏订单
        start_time = get_last_uptime()
        end_time = datetime.datetime.utcnow()
        if start_time and end_time and start_time < end_time:
            app.logger.info(f"开始检查遗漏订单，时间范围：{start_time} 到 {end_time}")
            missing_orders = fetch_missing_orders(start_time)
            if missing_orders:
                app.logger.info(f"发现 {len(missing_orders)} 个遗漏订单")
                for order in missing_orders:
                    order_id = order.get("nodeId")  # 从 fetch_missing_orders 的返回结果中提取 nodeId
                    try:
                        # 传递 nodeId 给 process_order_webhook
                        process_order_webhook(order_id, should_print=False)
                        app.logger.info(f"成功补齐订单：{order_id}")
                    except OrderProcessingError as e:
                        app.logger.error(f"补齐订单 {order_id} 失败: {e}")
                    except Exception as e:
                        app.logger.exception(f"补齐订单 {order_id} 时发生未知错误: {e}")
            else:
                app.logger.info("未发现遗漏订单。")

        record_uptime(end_time=datetime.datetime.utcnow())
        first_request = False

@app.route("/")
def index():
    orders = get_all_orders()
    return render_template("index.html", orders=orders)

@app.route("/print/<string:order_id>")
def print_order_route(order_id):
    order = get_order_by_id(order_id)
    if not order:
        return "Order not found", 404
    default_printer = get_setting('default_printer')
    if default_printer:
        win32print.SetDefaultPrinter(default_printer)
        success = print_helper.print_order(order["order_json"])  #  调用 printer_helper.py 中的 print_order 函数
        if success:
            update_order(order_id, "已打印")
            return redirect(url_for('index'))
        else:
            return "Print failed", 500  # 返回错误信息
    return "Printer not set", 500

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        default_printer = request.form.get("default_printer")
        auto_print_enabled = request.form.get("auto_print_enabled") == 'on'
        polling_enabled = request.form.get("polling_enabled") == 'on'
        # print_method = request.form.get("print_method")

        set_setting("default_printer", default_printer)
        set_setting("auto_print_enabled", str(auto_print_enabled).lower())
        set_setting("polling_enabled", str(polling_enabled).lower())
        # set_setting("print_method", print_method)

        global scheduler_started
        if polling_enabled and not scheduler_started:
            scheduler.add_job(func=poll_orders, trigger="interval", hours=1, id='poll_orders_job')
            if not scheduler.running:
                scheduler.start()
            scheduler_started = True
            app.logger.info("已启动轮询任务。")
        elif not polling_enabled and scheduler_started:
            try:
                scheduler.remove_job('poll_orders_job')
                scheduler_started = False
                app.logger.info("已停止轮询任务。")
            except Exception as e:
                app.logger.error(f"无法移除轮询任务: {e}")

        return redirect(url_for("settings"))
    return render_template("settings.html",
                           default_printer=get_setting('default_printer'),
                           auto_print_enabled=get_setting('auto_print_enabled') == 'true',
                           polling_enabled=get_setting('polling_enabled') == 'true',
                           # print_method=get_setting('print_method'),
                           printers=[printer[2] for printer in win32print.EnumPrinters(2)])

def verify_webhook_signature(request):
    """验证 Webhook 签名。"""
    md5_received = request.headers.get('X-AllValue-MD5')
    shop_domain = request.headers.get('X-AllValue-Shop-Domain')

    if not md5_received or not shop_domain:
        app.logger.warning("缺少必要的 header: X-AllValue-MD5 或 X-AllValue-Shop-Domain")
        return False

    message = request.get_data()
    data_to_hash = f"{message.decode('utf-8')}{ALLVALUE_WEBHOOK_SECRET}"
    md5_calculated = hashlib.md5(data_to_hash.encode('utf-8')).hexdigest()

    if md5_calculated != md5_received:
        app.logger.warning(f"Invalid webhook signature. Calculated: {md5_calculated}, Received: {md5_received}")
        return False

    # 验证 shop_domain
    if shop_domain != f"{shop}.myallvalue.com":
        app.logger.warning(f"Invalid shop domain. Received: {shop_domain}")
        return False

    return True

class OrderProcessingError(Exception):
    """订单处理过程中发生的异常。"""
    pass

def parse_order_data(raw_order_data):
    """解析订单数据"""
    if not raw_order_data:
        raise ValueError("raw_order_data is None or empty")

    # 1. 订单基础信息
    order_id = raw_order_data.get("name")
    created_at = raw_order_data.get("createdAt")
    contact_email = raw_order_data.get("contactEmail")
    customer_message = raw_order_data.get("customerMessage")

    # 2. 收货地址
    shipping_addr = raw_order_data.get("shippingAddress", {})
    shipping_address = {
        "address1": shipping_addr.get("address1"),
        "address2": shipping_addr.get("address2"),
        "city": shipping_addr.get("city"),
        "province": shipping_addr.get("province"),
        "country": shipping_addr.get("country"),
        "zip": shipping_addr.get("zip"),
        "provinceCode": shipping_addr.get("provinceCode"),
        "firstName": shipping_addr.get("firstName"),
        "lastName": shipping_addr.get("lastName"),
        "countryCode": shipping_addr.get("countryCode"),
        "company": shipping_addr.get("company"),
        "phone": shipping_addr.get("phone"),
    }

    # 3. 订单行项目 (lineItems)
    line_items = raw_order_data.get("lineItems", [])  # 直接获取 lineItems 列表
    parsed_items = []
    for item_obj in line_items:  # 直接遍历 lineItems 列表
        parsed_items.append({
            "name": item_obj.get("name"),
            "quantity": item_obj.get("quantity"),
            "option_values": [
                ov.get("name") for ov in item_obj.get("optionValues", [])
            ]
        })

    # 4. 订单总金额 (totalPrice)
    total_price_obj = raw_order_data.get("totalPrice", {})
    shop_money = total_price_obj.get("shopMoney", {})
    total_price = {
        "amount": shop_money.get("amount"),  # 字符串形式 "299.00"
        "currency_code": shop_money.get("currencyCode")
    }

    # 5. 买家信息
    cust = raw_order_data.get("customer", {})
    customer_info = {
        "email": cust.get("email"),
        "firstName": cust.get("firstName"),
        "lastName": cust.get("lastName"),
        "phone": cust.get("phone"),
    }

    # 6. 把所有字段组合到一个字典中
    order_data = {
        "order_id": order_id,
        "created_at": created_at,
        "contact_email": contact_email,
        "customer_message": customer_message,
        "shipping_address": shipping_address,
        "line_items": parsed_items,
        "total_price": total_price,
        "customer_info": customer_info,
    }

    return order_data


def get_default_printer():
    """获取默认打印机。"""
    return get_setting('default_printer') or ''


def fetch_order_details(access_token, nodeId):
    """从 AllValue API 获取订单详细信息。"""
    if not nodeId:
        app.logger.error("order_node_id is None or empty")
        raise OrderProcessingError("order_node_id is None or empty")

    headers = {
        "Custom-AllValue-Access-Token": access_token
    }

    # 修正后的 GraphQL 查询语句
    gql_query = """
    query OrderDetails($nodeId: NodeID!) {
        order(nodeId: $nodeId) {
            name
            createdAt
            shippingAddress {
                address1
                address2
                city
                province
                country
                zip
                provinceCode
                firstName
                lastName
                countryCode
                company
                phone
            }
            lineItems {
                name
                quantity
                optionValues {
                    name
                }
            }
            contactEmail
            customerMessage
            totalPrice {
                shopMoney {
                    amount
                    currencyCode
                }
            }
            customer {
                email
                firstName
                lastName
                phone
            }
        }
    }
    """

    variables = {
        "nodeId": nodeId
    }

    payload = {
        "query": gql_query,
        "variables": variables
    }

    app.logger.debug(f"Sending GraphQL query for order details with payload: {payload}")

    try:
        resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            app.logger.error(f"GraphQL Error: {data['errors']}")
            raise OrderProcessingError(f"GraphQL Error: {data['errors']}")

        return data["data"]["order"]

    except requests.exceptions.RequestException as e:
        app.logger.error(f"fetch_order_details error: {e}")
        raise OrderProcessingError(f"fetch_order_details error: {e}")


def persist_order_data(order_data):
    """将订单数据持久化到数据库"""
    if not order_data:
        raise OrderProcessingError("order_data is None")
    order_id = insert_or_update_order(order_data)
    if not order_id:
        raise OrderProcessingError("insert_or_update_order failed")
    return order_id


def print_order_if_enabled(order_data, should_print=True):
    """根据配置决定是否打印订单。"""
    if get_setting('auto_print_enabled') == 'true' and should_print:
        default_printer = get_default_printer()
        if default_printer:
            win32print.SetDefaultPrinter(default_printer)
            success = print_helper.print_order(order_data)
            if success:
                return True
            else:
                app.logger.warning("打印失败")
                return False
        else:
            app.logger.warning("未设置默认打印机。")
            return False
    return True


def process_order_webhook(order_node_id, should_print=True):
    """处理订单 Webhook 的主逻辑。"""
    try:
        access_token = get_allvalue_access_token()

        raw_order_data = fetch_order_details(access_token, order_node_id)
        order_data = parse_order_data(raw_order_data)
        order_id = persist_order_data(order_data)
        print_method = get_setting('print_method')
        print_success = print_order_if_enabled(order_data, should_print)
        if print_success:
            update_order(order_id, "已打印")
        else:
            update_order(order_id, "未打印")
        return True
    except (requests.exceptions.RequestException, OrderProcessingError) as e:
        app.logger.error(f"处理订单webhook时发生错误: {e}")
        return False
    except Exception as e:
        app.logger.exception("处理订单webhook时发生未知错误:")
        return False


@app.route('/webhook', methods=['POST'])
def handle_webhook():
    polling_enabled = get_setting('polling_enabled') == 'true'
    if polling_enabled:
        app.logger.info("轮询已启用，忽略 Webhook 请求。")
        return jsonify({"status": "ignored", "msg": "Polling is enabled, Webhook ignored."}), 200

    if not verify_webhook_signature(request):
        abort(401)

    data = request.get_json()
    if not data:
        abort(400)

    # 统一处理所有订单相关的 Webhook
    topic = request.headers.get('X-AllValue-Topic')
    if topic and topic.startswith('orders/'):
        order_node_id = data.get("nodeId")
        if not order_node_id:
            app.logger.error("Webhook data does not contain nodeId")
            return jsonify({"status": "fail", "msg": "Webhook data does not contain nodeId"}), 400

        if process_order_webhook(order_node_id):
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "fail", "msg": "Failed to process order webhook"}), 500
    else:
        app.logger.warning(f"Received webhook with unknown topic: {topic}")
        return jsonify({"status": "fail", "msg": f"Unknown webhook topic: {topic}"}), 400


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)