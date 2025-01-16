import win32print
import logging
import datetime
# from database import get_item_price  # 假设你有这个函数从数据库获取单价

logger = logging.getLogger(__name__)

def generate_print_text(order_data, print_method):
    """生成用于打印小票的文本。

    Args:
        order_data: 订单数据字典。
        print_method: 打印方式，"text" 表示普通文本，"escpos" 表示 ESC/POS 指令。

    Returns:
        根据打印方式生成的文本内容。
    """

    MAX_WIDTH = 32  # 假设每行最大宽度为 32 个字符

    def center_text(text):
        """将文本居中对齐"""
        text = text.encode('gbk').decode('gbk','ignore')
        padding = (MAX_WIDTH - len(text)) // 2
        return " " * padding + text

    def right_text(text):
        """将文本右对齐"""
        text = text.encode('gbk').decode('gbk','ignore')
        padding = MAX_WIDTH - len(text)
        return " " * padding + text

    def left_text(text):
        """将文本左对齐"""
        text = text.encode('gbk').decode('gbk','ignore')
        if len(text) > MAX_WIDTH:
            return text[:MAX_WIDTH]
        else:
            return text

    lines = []

    # 店铺名称 (居中)
    lines.append(center_text("一品"))  # todo: 修改成你的店铺名称
    lines.append("")

    # 订单信息
    lines.append(f"订单号: {order_data.get('order_id', '')}")
    lines.append(f"下单时间: {order_data.get('created_at', '')[:19]}")  # 截取日期时间部分
    lines.append("")

    # 客户信息 (根据需要调整)
    customer_info = order_data.get("customer_info", {})
    lines.append(f"顾客姓名: {customer_info.get('firstName','')} {customer_info.get('lastName','')}")
    lines.append(f"顾客电话: {customer_info.get('phone','')}")
    # lines.append(f"顾客邮箱: {customer_info.get('email','')}") # 邮箱信息通常不需要在小票中打印

    # 收货地址 (根据需要调整)
    shipping = order_data.get("shipping_address", {})
    address_str = f"{shipping.get('province','')} {shipping.get('city','')} {shipping.get('address1','')} {shipping.get('address2','')}"
    lines.append(left_text(address_str)) # 收货地址信息可能很长, 只保留一行, 且左对齐

    # 分隔线
    lines.append("-" * MAX_WIDTH)

    # 商品明细
    lines.append("商品        数量")  # 标题行, 去掉了单价和小计
    line_items = order_data.get("line_items", [])
    for item in line_items:
        item_name = item.get('name', '')
        quantity = item.get('quantity', 0)

        # 商品名称可能过长，需要截断并换行
        if len(item_name) > 10:
            lines.append(f"{item_name[:10]}")
            lines.append(f"{item_name[10:]}")
        else:
            lines.append(f"{item_name}")

        # 可选规格
        option_values = item.get("option_values", [])
        if option_values:
            lines.append(f"  规格: {', '.join(option_values)}")

        lines.append(right_text(f"{quantity:2}")) # 只打印数量

    # 分隔线
    lines.append("-" * MAX_WIDTH)

    # 总计
    total_price_info = order_data.get("total_price", {})
    amount = total_price_info.get("amount", "0")
    currency = total_price_info.get("currency_code", "")
    lines.append(right_text(f"总计: {amount} {currency}"))
    lines.append("")

    # 客户留言
    lines.append(f"客户留言: {order_data.get('customer_message', '')}")
    lines.append("")

    # 打印时间
    lines.append(center_text(f"打印时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))

    if print_method == "escpos":
        # 如果是 ESC/POS 模式，插入控制字符
        INIT = '\x1B\x40'  # 初始化打印机
        TXT_NORMAL = '\x1B\x21\x00'  # 正常字体
        TXT_DOUBLE_HEIGHT = '\x1B\x21\x10'  # 倍高字体
        TXT_DOUBLE_WIDTH = '\x1B\x21\x20'  # 倍宽字体
        TXT_UNDERL_ON = '\x1B\x2D\x02'  # 下划线
        TXT_UNDERL_OFF = '\x1B\x2D\x00'  # 取消下划线
        TXT_ALIGN_LT = '\x1B\x61\x00'  # 左对齐
        TXT_ALIGN_CT = '\x1B\x61\x01'  # 居中对齐
        TXT_ALIGN_RT = '\x1B\x61\x02'  # 右对齐
        CUT = '\x1D\x56\x41\x10'  # 切纸 (半切) 兼容指令
        LF = '\x0A' # 换行

        # 构造 ESC/POS 指令序列
        formatted_text = ""
        formatted_text += INIT
        formatted_text += TXT_ALIGN_CT # 居中对齐
        formatted_text += TXT_DOUBLE_HEIGHT # 使用倍高字体
        formatted_text += "一品\n" # 店铺名称
        formatted_text += TXT_NORMAL # 恢复正常字体
        formatted_text += TXT_ALIGN_LT # 左对齐
        formatted_text += "\r\n".join(lines) # 订单内容
        formatted_text += LF
        formatted_text += CUT
        return formatted_text
    else:
        lines.append("")
        lines.append("")
        lines.append("")
        return "\r\n".join(lines)


def print_order(order_data, print_method="text"):
    """
    根据新版 order_data 打印订单。
    """
    try:
        print_text = generate_print_text(order_data, print_method)
        default_printer = win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(default_printer)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Print Job", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        if print_method == "escpos":
            win32print.WritePrinter(hPrinter, print_text.encode('utf-8'))
        else:
            win32print.WritePrinter(hPrinter, print_text.encode("utf-8"))
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        win32print.ClosePrinter(hPrinter)

        logger.info(f"订单 {order_data.get('order_id')} 已使用 {print_method} 方式打印到打印机 {default_printer}")
        return True
    except Exception as e:
        logger.error(f"打印订单 {order_data.get('order_id')} 时出现错误: {e}")
        return False