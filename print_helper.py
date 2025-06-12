# print_helper.py (Linux专用版 - 完整代码)

import logging
import datetime
import subprocess  # 用于调用外部命令

logger = logging.getLogger(__name__)


def generate_print_text(order_data):
    """
    生成完整的 ESC/POS 打印指令序列。
    """
    MAX_WIDTH = 32

    # 辅助函数，用于生成带换行的对齐文本
    def escpos_center_text(text):
        return b'\x1B\x61\x01' + text.encode('utf-8') + b'\x0A'

    def escpos_right_text(text):
        return b'\x1B\x61\x02' + text.encode('utf-8') + b'\x0A'

    def escpos_left_text(text):
        return b'\x1B\x61\x00' + text.encode('utf-8') + b'\x0A'

    # 定义ESC/POS指令常量
    INIT = b'\x1B\x40'
    SET_UTF8_ENCODING = b'\x1C\x28\x43\x01\x00\x30\x32'
    SELECT_SIMPLIFIED_CHINESE_FONT = b'\x1C\x28\x43\x03\x00\x3C\x00\x14'
    TXT_NORMAL = b'\x1B\x21\x00'
    CUT = b'\x1D\x56\x41\x00'  # 使用全切且不额外进纸
    LF = b'\x0A'

    # --- 开始构建指令 ---
    commands = b''
    commands += INIT
    commands += SET_UTF8_ENCODING
    commands += SELECT_SIMPLIFIED_CHINESE_FONT

    # 店铺名称 (假设 app.py 会注入 shop_name)
    shop_name = order_data.get('shop_name', '你的店铺名')
    commands += b'\x1B\x61\x01'  # 居中
    commands += shop_name.encode('utf-8') + LF
    commands += b'\x1B\x61\x00'  # 恢复左对齐
    commands += LF

    # 订单信息
    commands += escpos_left_text(f"订单号: {order_data.get('order_id', '')}")
    commands += escpos_left_text(f"下单时间: {order_data.get('created_at', '')[:19]}")
    commands += LF

    # 客户信息
    shipping = order_data.get("shipping_address", {})
    s_fname = shipping.get('firstName', '')
    s_lname = shipping.get('lastName', '')
    c_fname = order_data.get("customer_info", {}).get('firstName', '')
    c_lname = order_data.get("customer_info", {}).get('lastName', '')
    customer_name = f"{s_fname} {s_lname}".strip() or f"{c_fname} {c_lname}".strip() or "(无姓名)"

    commands += escpos_left_text(f"顾客姓名: {customer_name}")
    commands += escpos_left_text(f"顾客电话: {shipping.get('phone', '')}")
    commands += LF

    # 收货地址
    address1 = shipping.get("address1", "")
    address2 = shipping.get("address2", "")
    zip_code = shipping.get("zip", "")
    country_code = shipping.get("countryCode", "")

    if address1:
        commands += escpos_left_text(address1)
    if address2:
        commands += escpos_left_text(address2)
    if zip_code or country_code:
        commands += escpos_left_text(f"{zip_code} {country_code}".strip())
    commands += LF

    # 分隔线
    commands += b'-' * MAX_WIDTH + LF

    # 商品明细表头
    commands += ("商品".ljust(MAX_WIDTH - 4) + "数量").encode('utf-8') + LF
    commands += b'-' * MAX_WIDTH + LF

    # 商品列表
    line_items = order_data.get("line_items", [])
    for item in line_items:
        # 商品名
        commands += escpos_left_text(item.get('name', ''))

        # 数量，单独一行右对齐
        quantity_str = str(item.get('quantity', 0))
        commands += b'\x1B\x61\x02'  # 右对齐
        commands += quantity_str.encode('utf-8') + LF
        commands += b'\x1B\x61\x00'  # 恢复左对齐

        # 规格
        option_values = item.get("option_values", [])
        if option_values:
            options_str = f"  规格: {', '.join(option_values)}"
            commands += escpos_left_text(options_str)

        commands += LF  # 每个商品后留出空行

    # 分隔线
    commands += b'-' * MAX_WIDTH + LF

    # 总计
    total_price_info = order_data.get("total_price", {})
    amount = total_price_info.get("amount", 0)
    try:
        # 确保金额以两位小数格式显示
        amount_str = f"{float(amount):.2f}"
    except (ValueError, TypeError):
        amount_str = str(amount)
    currency = total_price_info.get("currency_code", "")
    commands += escpos_right_text(f"总计: {amount_str} {currency}")
    commands += LF

    # 客户留言
    customer_message = order_data.get('customer_message')
    if customer_message:
        commands += escpos_left_text(f"客户留言: {customer_message}")
        commands += LF

    # 打印时间
    print_time_str = f"打印时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commands += escpos_center_text(print_time_str)
    commands += LF

    # 结尾空白并切纸
    commands += LF + LF + CUT

    return commands


def print_order(order_data, printer_name=None):
    """
    主接口函数：生成ESC/POS指令并调用Linux的lp命令打印。
    """
    logger.info(f"ESC/POS模块 (Linux版): 处理订单 {order_data.get('order_id')}，打印机: '{printer_name or '默认'}'")

    # 1. 生成ESC/POS指令字节流
    print_commands = generate_print_text(order_data)
    if not print_commands:
        logger.error("ESC/POS模块: 生成打印指令失败。")
        return False

    # 2. 在Linux上使用'lp -o raw'命令发送原始指令
    try:
        args = ['lp', '-o', 'raw']
        if printer_name:
            args.extend(['-d', printer_name])

        logger.info(f"ESC/POS (Linux): 正在通过 'lp -o raw' 命令发送指令到打印机 '{printer_name or '默认'}'")
        subprocess.run(args, input=print_commands, check=True, timeout=15)

        logger.info("ESC/POS (Linux): 'lp' 命令执行成功，指令已发送。")
        return True
    except FileNotFoundError:
        logger.error("ESC/POS (Linux): 'lp' 命令未找到。请确认CUPS客户端(cups-client)是否已在Linux系统中安装。")
        return False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"ESC/POS (Linux): 通过 'lp' 命令打印时出错: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"ESC/POS (Linux): 打印时发生未知错误: {e}", exc_info=True)
        return False
