import win32print
import logging
import datetime
import os
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# 假设 letter 大小的纸张宽度为 8.5 英寸，这里我们使用 3 英寸作为小票宽度
MAX_WIDTH = 3.15 * inch
LEFT_MARGIN = 0.1 * inch  # 根据实际情况调整边距
TOP_MARGIN = 0.1 * inch

# 注册中文字体, 若需要, 请自行下载
pdfmetrics.registerFont(TTFont('SimSun', 'SimSun.ttf'))

def generate_pdf_content(order_data):
    """生成 PDF 内容。"""

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(MAX_WIDTH, letter[1]))  # 自定义页面宽度
    c.setFont("SimSun", 12)

    def center_text(text, y):
        """将文本居中对齐"""
        text_width = c.stringWidth(text, "SimSun", 12)
        x = (MAX_WIDTH - text_width) / 2
        c.drawString(x, y, text)

    def right_text(text, y):
        """将文本右对齐"""
        text_width = c.stringWidth(text, "SimSun", 12)
        x = MAX_WIDTH - text_width - LEFT_MARGIN
        c.drawString(x, y, text)

    y = letter[1] - TOP_MARGIN - inch # 初始 Y 坐标

    # 店铺名称 (居中)
    center_text("一品", y)  # 修改成你的店铺名称
    y -= 0.3 * inch

    # 订单信息
    c.drawString(LEFT_MARGIN, y, f"订单号: {order_data.get('order_id', '')}")
    y -= 0.2 * inch
    c.drawString(LEFT_MARGIN, y, f"下单时间: {order_data.get('created_at', '')[:19]}")  # 截取日期时间部分
    y -= 0.3 * inch

    # 客户信息
    customer_info = order_data.get("customer_info", {})
    shipping = order_data.get("shipping_address", {})
    c.drawString(LEFT_MARGIN, y, f"顾客姓名: {customer_info.get('firstName','')} {customer_info.get('lastName','')}")
    y -= 0.2 * inch
    c.drawString(LEFT_MARGIN, y, f"顾客电话: {shipping.get('phone','')}")
    y -= 0.2 * inch
    c.drawString(LEFT_MARGIN, y, f"顾客邮箱: {order_data.get('contact_email','')}")
    y -= 0.3 * inch

    # 收货地址

    address1 = shipping.get("address1", "")
    address2 = shipping.get("address2", "")
    zip_code = shipping.get("zip", "")
    country_code = shipping.get("countryCode", "")

    if address1:
        c.drawString(LEFT_MARGIN, y, address1)
        y -= 0.2 * inch
    if address2:
        c.drawString(LEFT_MARGIN, y, address2)
        y -= 0.2 * inch
    if zip_code or country_code:
        c.drawString(LEFT_MARGIN, y, f"{zip_code} {country_code}".strip())
        y -= 0.2 * inch

    # 分隔线
    c.line(LEFT_MARGIN, y, MAX_WIDTH - LEFT_MARGIN, y)
    y -= 0.2 * inch

    # 商品明细
    c.drawString(LEFT_MARGIN, y, "商品                          数量")
    y -= 0.3 * inch
    line_items = order_data.get("line_items", [])
    for item in line_items:
        item_name = item.get('name', '')
        quantity = item.get('quantity', 0)

        c.drawString(LEFT_MARGIN, y, f"{item_name}")
        y -= 0.2 * inch

        option_values = item.get("option_values", [])
        if option_values:
            c.drawString(LEFT_MARGIN + 0.2 * inch, y, f"  规格: {', '.join(option_values)}")
            y -= 0.2 * inch

        right_text(f"{quantity:2}", y)
        y -= 0.3 * inch

    # 分隔线
    c.line(LEFT_MARGIN, y, MAX_WIDTH - LEFT_MARGIN, y)
    y -= 0.2 * inch

    # 总计
    total_price_info = order_data.get("total_price", {})
    amount = total_price_info.get("amount", "0")
    currency = total_price_info.get("currency_code", "")
    right_text(f"总计: {amount} {currency}", y)
    y -= 0.4 * inch

    # 客户留言
    c.drawString(LEFT_MARGIN, y, f"客户留言: {order_data.get('customer_message', '')}")
    y -= 0.4 * inch

    # 打印时间
    center_text(f"打印时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", y)

    c.showPage()
    c.save()
    return buffer.getvalue()


def print_order(order_data):
    """
    生成 PDF 并打印订单。
    """
    try:
        pdf_content = generate_pdf_content(order_data)
        default_printer = win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(default_printer)


        # 获取打印机的信息
        printer_info = win32print.GetPrinter(hPrinter, 2)

        # 获取 pDevMode 结构
        pDevMode = printer_info['pDevMode']

        # 开始打印任务
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Order Print", None, "RAW"))  # 使用元组
        win32print.StartPagePrinter(hPrinter)

        # 直接将 PDF 内容发送到打印机
        win32print.WritePrinter(hPrinter, pdf_content)

        # 结束打印任务
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        win32print.ClosePrinter(hPrinter)

        logger.info(f"订单 {order_data.get('order_id')} 的 PDF 已发送到打印机 {default_printer}")
        return True
    except Exception as e:
        logger.error(f"打印订单 {order_data.get('order_id')} 的 PDF 时出现错误: {e}")
        return False