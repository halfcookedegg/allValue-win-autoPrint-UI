import win32print
import logging

logger = logging.getLogger(__name__)

def generate_print_text(order_data):
    lines = []
    lines.append(f"订单号: {order_data.get('order_id', '')}")
    lines.append("----------")
    lines.append("品名\t数量\t单价")
    for item in order_data.get('items', []):
        lines.append(f"{item['name']}\t{item['qty']}\t{item['price']}")
    lines.append("----------")
    lines.append(f"总价: {order_data.get('total_price', 0)}")
    lines.append(f"下单时间: {order_data.get('timestamp', '')}")
    return "\r\n".join(lines)

def print_order(order):
    try:
        print_text = generate_print_text(order)
        default_printer = win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(default_printer)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Print Job", None, "RAW"))  # 使用RAW格式
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, print_text.encode("gbk")) # 使用gbk编码
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        win32print.ClosePrinter(hPrinter)
        logger.info(f"订单 {order.get('order_id')} 已打印到打印机 {default_printer}")
    except Exception as e:
        logger.error(f"打印订单 {order.get('order_id')} 时出现错误: {e}")