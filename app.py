import requests
import os
import hashlib
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, abort
import win32print

from token_manager import get_allvalue_access_token, TokenRetrievalError
import print_helper
from database import (
    init_db, get_setting, set_setting,
    insert_or_update_order, get_all_orders, update_order, get_order_by_id
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO)

ALLVALUE_CLIENT_ID = os.environ.get("ALLVALUE_CLIENT_ID")
ALLVALUE_CLIENT_SECRET = os.environ.get("ALLVALUE_CLIENT_SECRET")
ALLVALUE_REDIRECT_URI = os.environ.get("ALLVALUE_REDIRECT_URI")
ALLVALUE_AUTHORIZE_URL = os.environ.get("ALLVALUE_AUTHORIZE_URL")
ALLVALUE_TOKEN_URL = os.environ.get("ALLVALUE_TOKEN_URL")
ALLVALUE_GRAPHQL_ENDPOINT = os.environ.get("ALLVALUE_GRAPHQL_ENDPOINT")
ALLVALUE_WEBHOOK_SECRET = os.environ.get("ALLVALUE_WEBHOOK_SECRET")


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
    message = request.get_data()
    md5_calculated = hashlib.md5(message + ALLVALUE_WEBHOOK_SECRET.encode('utf-8')).hexdigest()
    if md5_calculated != md5_received:
        app.logger.warning(f"Invalid webhook signature. Calculated: {md5_calculated}, Received: {md5_received}")
        return False
    return True


def get_default_printer():
    """获取默认打印机。"""
    return get_setting('default_printer') or ''


def process_order_webhook(order_node_id):
    """处理订单 Webhook。"""
    try:
        access_token = get_allvalue_access_token()
        if not access_token:
            raise TokenRetrievalError("Failed to get AllValue access token.")
        headers = {
            "Content-Type": "application/graphql",
            "Custom-AllValue-Access-Token": access_token
        }
        query = f"""
        {{
          node(id: "{order_node_id}") {{
            ... on Order {{
              name
              createdAt
              totalPrice
              displayFulfillmentStatus
              lineItems(first:10) {{
                edges {{
                  node {{
                    title
                    quantity
                    price
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        resp = requests.post(ALLVALUE_GRAPHQL_ENDPOINT, headers=headers, data=query)
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            app.logger.error(f"GraphQL Error: {data['errors']}")
            return False

        node = data["data"]["node"]
        order_data = {
            "order_id": node["name"],
            "timestamp": node["createdAt"],
            "total_price": node["totalPrice"],
            "items": [],
            "status": "未打印"
        }
        line_items = node["lineItems"]["edges"]
        for li_edge in line_items:
            li_node = li_edge["node"]
            item = {
                "name": li_node["title"],
                "qty": li_node["quantity"],
                "price": li_node["price"]
            }
            order_data["items"].append(item)

        order_id = insert_or_update_order(order_data)
        if order_id and get_setting('auto_print_enabled') == 'true':
            default_printer = get_default_printer()
            if default_printer:
                win32print.SetDefaultPrinter(default_printer)
                print_helper.print_order(order_data)
                update_order(order_id, "已打印")
        return True

    except requests.exceptions.RequestException as e:
        app.logger.error(f"fetch_single_allvalue_order error: {e}")
        return False
    except TokenRetrievalError as e:
        app.logger.error(str(e))
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
    app.logger.info(f"Received webhook: Topic: {topic}, Data: {data}")

    if topic in ('orders/create', 'orders/paid', 'orders/payment_confirmed', 'orders/fulfilled'):
        order_node_id = data.get('orderNodeId')
        if not process_order_webhook(order_node_id):
            return jsonify({"status": "fail", "msg": "Failed to process order"}), 500
    # ... (其他 topic 处理)

    return jsonify({"status": "success"}), 200


@app.route("/auth")
def auth():
    auth_url = f"{ALLVALUE_AUTHORIZE_URL}?client_id={ALLVALUE_CLIENT_ID}&redirect_uri={ALLVALUE_REDIRECT_URI}&response_type=code"
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    try:
        get_allvalue_access_token(code)
    except TokenRetrievalError as e:
        return f"Token retrieval error: {e}", 500
    return redirect(url_for('index'))


if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)