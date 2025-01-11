import win32print
import logging

logger = logging.getLogger(__name__)

def generate_print_text(order_data):

    lines = []

    # 1. 订单号、下单时间
    lines.append(f"订单号: {order_data.get('order_id', '')}")
    lines.append(f"下单时间: {order_data.get('created_at', '')}")

    # 2. 客户信息 (若需要)
    lines.append("----------")
    customer_info = order_data.get("customer_info", {})
    lines.append(f"顾客姓名: {customer_info.get('firstName','')} {customer_info.get('lastName','')}")
    lines.append(f"顾客电话: {customer_info.get('phone','')}")
    lines.append(f"顾客邮箱: {customer_info.get('email','')}")

    # 3. 收货地址 (若需要打印)
    shipping = order_data.get("shipping_address", {})
    lines.append("----------")
    lines.append("收货地址:")
    address_str = f"{shipping.get('province','')} {shipping.get('city','')} {shipping.get('address1','')} {shipping.get('address2','')}"
    lines.append(address_str.strip())

    # 4. 订单留言或备注
    lines.append("----------")
    lines.append(f"客户留言: {order_data.get('customer_message', '')}")

    # 5. 商品明细
    lines.append("----------")
    lines.append("商品 (数量) [可选规格]")
    line_items = order_data.get("line_items", [])
    for item in line_items:
        # 名称 + 数量
        line_str = f"{item.get('name','')} x {item.get('quantity','')}"
        # 如果有option_values，就拼成括号显示
        option_values = item.get("option_values", [])
        if option_values:
            line_str += " ("
            line_str += ", ".join(option_values)
            line_str += ")"
        lines.append(line_str)

    # 6. 订单总价
    lines.append("----------")
    total_price_info = order_data.get("total_price", {})
    amount = total_price_info.get("amount", "0")
    currency = total_price_info.get("currency_code", "")
    lines.append(f"总价: {amount} {currency}")

    return "\r\n".join(lines)


def print_order(order_data):
    """
    根据新版 order_data 打印订单。
    基本逻辑与旧版类似，只是调用了新的 generate_print_text。
    """
    try:
        print_text = generate_print_text(order_data)
        default_printer = win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(default_printer)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Print Job", None, "RAW"))  # 使用RAW格式
        win32print.StartPagePrinter(hPrinter)

        # 这里使用 gbk 编码，如需支持更多字符集可改成其他编码
        win32print.WritePrinter(hPrinter, print_text.encode("gbk"))

        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        win32print.ClosePrinter(hPrinter)

        logger.info(f"订单 {order_data.get('order_id')} 已打印到打印机 {default_printer}")
    except Exception as e:
        logger.error(f"打印订单 {order_data.get('order_id')} 时出现错误: {e}")
