import atexit
import datetime
import requests
import os
import hashlib
import logging
import json
import webhook_handlers
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
import win32print

from token_manager import get_allvalue_access_token
import print_helper
from database import (
    init_db, get_setting, set_setting,
    insert_or_update_order, get_all_orders, update_order, get_order_by_id
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

shop = os.environ.get("SHOP")
ALLVALUE_GRAPHQL_ENDPOINT = f"https://{shop}.myallvalue.com/admin/api/open/graphql/v202108"
ALLVALUE_WEBHOOK_SECRET = os.environ.get("ALLVALUE_WEBHOOK_SECRET")

TIME_FILE = "uptime.json"
first_request = True

# --- 时间记录和补单相关函数 ---
def record_uptime(start_time=None, end_time=None):
    """记录应用上线或下线时间（UTC）。"""
    data = {}
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    except json.JSONDecodeError:
        app.logger.warning("uptime.json 文件损坏，重新创建。")
        data = {}
    except FileNotFoundError:
        app.logger.warning("uptime.json 文件不存在，创建新文件")
        data = {}
    except IOError as e:
        app.logger.error(f"读取uptime.json文件失败:{e}")
        data={}

    if start_time:
        data["start_time"] = start_time.isoformat()
    if end_time:
        data["end_time"] = end_time.isoformat()

    try:
        with open(TIME_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        app.logger.error(f"写入 uptime.json 文件失败: {e}")

def get_last_uptime():
    """获取上次应用上线和下线时间（UTC）。"""
    try:
        if os.path.exists(TIME_FILE):
            with open(TIME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                start_time_str = data.get("end_time")
                end_time_str = datetime.datetime.utcnow().isoformat()
                if start_time_str and end_time_str:
                    return datetime.datetime.fromisoformat(start_time_str), datetime.datetime.fromisoformat(
                        end_time_str)
        else:
            app.logger.warning(f"{TIME_FILE}文件不存在")  # 文件不存在也记录日志，方便排查
            return None, None
    except Exception as e:
        app.logger.error(f"读取{TIME_FILE}文件失败:{e}")  # 统一记录日志，并包含文件名
        return None, None

def to_millis(dt: datetime.datetime) -> int:
    """将Python datetime转成UTC毫秒时间戳"""
    if dt.tzinfo is None:
        # 假设你的 dt 已经是 UTC naive datetime
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    delta = dt - epoch
    return int(delta.total_seconds() * 1000)

def fetch_missing_orders(start_time, end_time):
    """请求指定时间段内的遗漏订单，支持分页，使用毫秒级 created_at_range。"""
    if not start_time or not end_time:
        app.logger.warning("开始或结束时间为空，无法请求遗漏订单。")
        return []

    access_token = get_allvalue_access_token()
    if not access_token:
        app.logger.error("无法获取 AllValue 访问令牌，无法请求遗漏订单。")
        return []

    start_ts = to_millis(start_time)
    end_ts = to_millis(end_time)

    # 构造 created_at_range 查询字符串
    filter_str = f"created_at_range:[{start_ts} TO {end_ts}]"

    orders = []
    has_next_page = True
    after_cursor = None
    page_size = 100  # 根据需要调整，每次请求的订单数

    gql_query = """
    query Orders($query: String!, $first: Int!, $after: String) {
      orders(query: $query, first: $first, after: $after) {
        edges {
          node {
            id
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """

    headers = {
        "Content-Type": "application/json",
        "custom-allvalue-access-token": access_token
    }

    while has_next_page:
        variables = {
            "query": filter_str,
            "first": page_size,
            "after": after_cursor
        }

        payload = {
            "query": gql_query,
            "variables": variables
        }

        try:
            resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if "errors" in data:
                app.logger.error(f"GraphQL Error: {data['errors']}")
                break

            orders_conn = data.get("data", {}).get("orders", {})
            edges = orders_conn.get("edges", [])
            for edge in edges:
                node = edge.get("node")
                if node and node.get("id"):
                    orders.append(node["id"])

            page_info = orders_conn.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            after_cursor = page_info.get("endCursor")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"请求遗漏订单失败: {e}")
            break
        except Exception as e:
            app.logger.exception(f"获取遗漏订单时发生未知错误: {e}")
            break

    return orders


@app.before_request
def check_for_missing_orders():
    """在应用启动后检查并处理遗漏订单。"""
    global first_request
    if first_request:
        start_time, end_time = get_last_uptime()
        if start_time and end_time and start_time < end_time:
            app.logger.info(f"开始检查遗漏订单，时间范围：{start_time} 到 {end_time}")
            missing_order_ids = fetch_missing_orders(start_time, end_time)
            if missing_order_ids:
                app.logger.info(f"发现 {len(missing_order_ids)} 个遗漏订单：{missing_order_ids}")
                for order_id in missing_order_ids:
                    try:
                        process_order_webhook(order_id, should_print=False)
                        app.logger.info(f"成功补齐订单：{order_id}")
                    except OrderProcessingError as e:
                        app.logger.error(f"补齐订单 {order_id} 失败: {e}")
                    except Exception as e:
                        app.logger.exception(f"补齐订单 {order_id} 时发生未知错误: {e}")
            else:
                app.logger.info("未发现遗漏订单。")
        record_uptime(start_time=datetime.datetime.utcnow())
        try:
            if os.path.exists(TIME_FILE):
                os.remove(TIME_FILE)
                app.logger.info(f"成功删除上一个记录时间的日志文件：{TIME_FILE}")
        except OSError as e:
            app.logger.error(f"删除上一个记录时间的日志文件 {TIME_FILE} 失败: {e}")
        except Exception as e:
            app.logger.exception(f"删除上一个记录时间的日志文件 {TIME_FILE} 时发生未知错误: {e}")
        first_request = False

@atexit.register
def on_exit():
    record_uptime(end_time=datetime.datetime.utcnow())

@app.route("/")
def index():
    orders = get_all_orders()
    return render_template("index.html", orders=orders)


@app.route("/print/<int:order_id>")
def print_order_route(order_id):
    order = get_order_by_id(order_id)
    if not order:
        return "Order not found", 404
    default_printer = get_setting('default_printer')
    if default_printer:
        win32print.SetDefaultPrinter(default_printer)
        print_helper.print_order(order["order_json"])
        update_order(order_id, "已打印")
        return redirect(url_for('index'))
    return "Printer not set", 500


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        default_printer = request.form.get("default_printer")
        auto_print_enabled = request.form.get("auto_print_enabled") == "on"
        set_setting("default_printer", default_printer)
        set_setting("auto_print_enabled", str(auto_print_enabled).lower())

        return redirect(url_for("settings"))
    return render_template("settings.html",
                           default_printer=get_setting('default_printer'),
                           auto_print_enabled=get_setting('auto_print_enabled') == 'true',
                           printers=[printer[2] for printer in win32print.EnumPrinters(2)])


def verify_webhook_signature(request):
    """验证 Webhook 签名。"""
    md5_received = request.headers.get('X-AllValue-MD5')
    shop_domain = request.headers.get('X-AllValue-Shop-Domain') # 加上shop_domain验证

    if not md5_received or not shop_domain:
        app.logger.warning("缺少必要的 header: X-AllValue-MD5 或 X-AllValue-Shop-Domain")
        return False

    message = request.get_data()
    data_to_hash = f"{message.decode('utf-8')}{ALLVALUE_WEBHOOK_SECRET}"
    md5_calculated = hashlib.md5(data_to_hash.encode('utf-8')).hexdigest()

    if md5_calculated != md5_received:
        app.logger.warning(f"Invalid webhook signature. Calculated: {md5_calculated}, Received: {md5_received}")
        return False
    return True

class OrderProcessingError(Exception):
    """订单处理过程中发生的异常。"""
    pass

def parse_order_data(raw_order_data):
    if not raw_order_data:
        raise ValueError("raw_order_data is None or empty")

    # 1. 订单基础信息
    order_id = raw_order_data.get("name")            # 订单号
    created_at = raw_order_data.get("createdAt")     # 下单时间
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
    #   你在查询里写的是 lineItems { name quantity optionValues { name } }
    #   一般返回一个数组而不是 edges/node。
    line_items = raw_order_data.get("lineItems", [])
    parsed_items = []
    for item_obj in line_items:
        parsed_items.append({
            "name": item_obj.get("name"),
            "quantity": item_obj.get("quantity"),
            # 如果有 optionValues，就解析为字符串列表或其他需要的格式
            "option_values": [
                ov.get("name") for ov in item_obj.get("optionValues", [])
            ]
        })

    # 4. 订单总金额 (totalPrice)
    #   根据你写的:
    #   totalPrice {
    #       shopMoney {
    #           amount
    #           currencyCode
    #       }
    #   }
    total_price_obj = raw_order_data.get("totalPrice", {})
    shop_money = total_price_obj.get("shopMoney", {})
    total_price = {
        "amount": shop_money.get("amount"),         # 字符串形式 "299.00"
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
        "Content-Type": "application/graphql",
        "custom-allvalue-access-token": access_token
    }

    query = f"""
    query MyQuery {{
          order(nodeId: "{nodeId}") {{
            name
            createdAt
            shippingAddress {{      
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
            }}
            lineItems {{
              
              name
              quantity
              optionValues {{
                    name
            }}
            }}
            contactEmail
            customerMessage
            totalPrice {{
              shopMoney {{
                amount
                currencyCode
              }}
            }}
            customer {{
              email
              firstName
              lastName
              phone
            }}
          }}
        }}
    """
    #如果请求失败抛出异常
    try:
        resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, data=query)
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


def print_order_if_enabled(order_data,should_print = True):
    """根据配置决定是否打印订单。"""
    if get_setting('auto_print_enabled') == 'true' and should_print:
        default_printer = get_default_printer()
        if default_printer:
            win32print.SetDefaultPrinter(default_printer)
            print_helper.print_order(order_data)
            return True
        else:
            app.logger.warning("未设置默认打印机。")
            return False
    return True

def process_order_webhook(order_node_id,should_print = True):
    """处理订单 Webhook 的主逻辑。"""
    try:
        access_token = get_allvalue_access_token()

        raw_order_data = fetch_order_details(access_token, order_node_id)
        order_data = parse_order_data(raw_order_data)
        order_id = persist_order_data(order_data)
        print_order_if_enabled(order_data,should_print)
        update_order(order_id, "已打印")
        return True
    except (requests.exceptions.RequestException, OrderProcessingError) as e: #捕捉所有自定义和requests的异常
        app.logger.error(f"处理订单webhook时发生错误: {e}")
        return False
    except Exception as e:
        app.logger.exception("处理订单webhook时发生未知错误:")
        return False


@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not verify_webhook_signature(request):
        abort(401)

    data = request.get_json()
    if not data:
        abort(400)

    topic = request.headers.get('X-AllValue-Topic')
    try:
        handler = webhook_handlers.get(topic)
        if handler:
            return handler.handle(request, data)
        else:
            app.logger.warning(f"未知 Webhook Topic: {topic}")
            return jsonify({"status": "fail", "msg": f"Unknown webhook topic: {topic}"}), 400
    except Exception as e:
        app.logger.exception("处理 webhook 时发生未知错误:")
        return jsonify({"status": "fail", "msg": "Internal server error"}), 500


if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)