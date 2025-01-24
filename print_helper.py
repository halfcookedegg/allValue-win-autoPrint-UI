import win32print
import logging
import datetime

logger = logging.getLogger(__name__)


def generate_print_text(order_data):
    """生成 ESC/POS 打印指令序列。"""

    MAX_WIDTH = 32  # 根据你的打印机和纸张宽度调整

    def escpos_center_text(text):
        """ESC/POS 居中对齐"""
        return b'\x1B\x61\x01' + text.encode('utf-8') + b'\x1B\x61\x00'

    def escpos_right_text(text):
        """ESC/POS 右对齐"""
        return b'\x1B\x61\x02' + text.encode('utf-8') + b'\x1B\x61\x00'

    def escpos_left_text(text):
        """ESC/POS 左对齐"""
        return b'\x1B\x61\x00' + text.encode('utf-8')

    # ESC/POS 指令序列
    INIT = b'\x1B\x40'  # 初始化打印机
    TXT_NORMAL = b'\x1B\x21\x00'  # 正常字体
    TXT_DOUBLE_HEIGHT = b'\x1B\x21\x10'  # 倍高字体
    TXT_DOUBLE_WIDTH = b'\x1B\x21\x20'  # 倍宽字体
    CUT = b'\x1D\x56\x41\x10'  # 切纸指令 (根据你的打印机修改)
    LF = b'\x0A'  # 换行
    SELECT_CHINESE = b'\x1B\x26\x03'  # 选择中文字符集
    # 中文可以用gbk或utf-8编码, 具体取决于你的打印机设置, 通常情况下, 打印机需要被设置为支持中文 (例如 SimSun) 才能正确打印中文
    ENCODING = 'utf-8'  # 或 'gbk'

    commands = b''
    commands += INIT
    commands += SELECT_CHINESE
    commands += escpos_center_text("一品香") + LF  # 店铺名称, 居中

    # 订单信息
    commands += TXT_NORMAL
    commands += escpos_left_text(f"订单号: {order_data.get('order_id', '')}") + LF
    commands += escpos_left_text(f"下单时间: {order_data.get('created_at', '')[:19]}") + LF
    commands += LF

    # 客户信息
    customer_info = order_data.get("customer_info", {})
    shipping = order_data.get("shipping_address", {})
    commands += escpos_left_text(
        f"顾客姓名: {customer_info.get('firstName', '')} {customer_info.get('lastName', '')}") + LF
    commands += escpos_left_text(f"顾客电话: {shipping.get('phone', '')}") + LF
    commands += escpos_left_text(f"顾客邮箱: {order_data.get('contact_email', '')}") + LF
    commands += LF

    # 收货地址
    address1 = shipping.get("address1", "")
    address2 = shipping.get("address2", "")
    zip_code = shipping.get("zip", "")
    country_code = shipping.get("countryCode", "")

    if address1:
        commands += escpos_left_text(address1) + LF
    if address2:
        commands += escpos_left_text(address2) + LF
    if zip_code or country_code:
        commands += escpos_left_text(f"{zip_code} {country_code}".strip()) + LF

    # 分隔线
    commands += escpos_left_text("-" * MAX_WIDTH) + LF

    # 商品明细
    commands += escpos_left_text("商品                          数量") + LF
    line_items = order_data.get("line_items", [])
    for item in line_items:
        item_name = item.get('name', '')
        quantity = item.get('quantity', 0)

        commands += escpos_left_text(f"{item_name}") + LF

        option_values = item.get("option_values", [])
        if option_values:
            commands += escpos_left_text(f"  规格: {', '.join(option_values)}") + LF

        commands += escpos_right_text(f"{quantity:2}") + LF

    # 分隔线
    commands += escpos_left_text("-" * MAX_WIDTH) + LF

    # 总计
    total_price_info = order_data.get("total_price", {})
    amount = total_price_info.get("amount", "0")
    currency = total_price_info.get("currency_code", "")
    commands += escpos_right_text(f"总计: {amount} {currency}") + LF
    commands += LF

    # 客户留言
    commands += escpos_left_text(f"客户留言: {order_data.get('customer_message', '')}") + LF
    commands += LF

    # 打印时间
    commands += escpos_center_text(f"打印时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}") + LF

    # 切纸
    commands += CUT

    return commands


def print_order(order_data):
    """
    使用 ESC/POS 指令打印订单。
    """
    try:
        print_commands = generate_print_text(order_data)
        default_printer = win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(default_printer)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Order Print", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, print_commands)
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        win32print.ClosePrinter(hPrinter)

        logger.info(f"订单 {order_data.get('order_id')} 已发送到打印机 {default_printer}")
        return True
    except Exception as e:
        logger.error(f"打印订单 {order_data.get('order_id')} 时出现错误: {e}")
        return False