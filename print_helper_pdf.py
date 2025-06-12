# print_helper_pdf.py (Linux专用版)

import logging
import datetime
import os
import subprocess
import tempfile
from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa  # 使用 xhtml2pdf 替代 WeasyPrint

logger = logging.getLogger(__name__)


# --- HTML和PDF生成逻辑 ---

def generate_receipt_html(order_data):
    """使用Jinja2模板从订单数据生成HTML字符串。"""
    # 假设 'templates' 文件夹位于运行 app.py 的当前工作目录
    template_folder_path = 'templates'
    try:
        env = Environment(
            loader=FileSystemLoader(searchpath=template_folder_path),
            autoescape=select_autoescape(['html', 'xml'])
        )
        template = env.get_template('receipt_template.html')
        context = {
            'order': order_data,
            'current_print_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        return template.render(context)
    except Exception as e:
        logger.error(f"渲染HTML模板时出错: {e}", exc_info=True)
        return None


def generate_pdf_from_html_content(html_content, pdf_filepath):
    """使用 xhtml2pdf 将HTML字符串转换为PDF文件。"""
    logger.info("正在使用 xhtml2pdf 生成PDF...")
    try:
        # 使用 'w+b' 模式打开文件，供 xhtml2pdf 写入二进制数据
        with open(pdf_filepath, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(
                html_content,  # HTML源内容
                dest=pdf_file,  # 目标PDF文件对象
                encoding='UTF-8'  # 确保使用UTF-8编码
            )

        # 检查转换过程中是否有错误
        if pisa_status.err:
            logger.error(f"xhtml2pdf 转换错误, 错误码: {pisa_status.err}, {pisa_status.log}")
            return False

        logger.info(f"PDF文件已通过 xhtml2pdf 成功生成: {pdf_filepath}")
        return True
    except Exception as e:
        logger.error(f"使用 xhtml2pdf 生成PDF时发生未知错误: {e}", exc_info=True)
        return False


def silent_print_pdf(pdf_filepath, printer_name=None):
    """在Linux上使用CUPS的'lp'命令尝试静默打印。"""
    try:
        args = ['lp']
        if printer_name:
            # -d 参数指定目标打印机队列名称
            args.extend(['-d', printer_name])

        args.append(pdf_filepath)

        logger.info(f"PDF (Linux): 正在通过 'lp' 命令打印文件 '{pdf_filepath}' 到打印机 '{printer_name or '默认'}'")
        subprocess.run(args, check=True, timeout=30)
        logger.info(f"PDF (Linux): 文件已通过 'lp' 命令发送到打印队列。")
        return True
    except FileNotFoundError:
        logger.error("PDF (Linux): 'lp' 命令未找到。请确认CUPS客户端(cups-client)是否已在Linux系统中安装。")
        return False
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"PDF (Linux): 通过 'lp' 命令打印时出错: {e}", exc_info=True)
        return False


# --- 供 app.py 调用的主函数 ---
def print_order(order_data, printer_name=None, keep_pdf_for_internal_debug=False):
    """
    主接口函数：生成PDF并调用Linux打印函数。
    """
    logger.info(f"PDF模块 (Linux版): 处理订单 {order_data.get('order_id')}，打印机: '{printer_name or '默认'}'")

    # 1. 生成HTML
    html_content = generate_receipt_html(order_data)
    if not html_content:
        logger.error("PDF模块: 生成HTML内容失败。")
        return False

    # 2. 生成PDF
    fd, pdf_filepath = tempfile.mkstemp(suffix=".pdf", prefix="receipt_")
    os.close(fd)
    logger.debug(f"PDF模块: 临时PDF文件路径: {pdf_filepath}")

    if not generate_pdf_from_html_content(html_content, pdf_filepath):
        if os.path.exists(pdf_filepath):
            try:
                os.unlink(pdf_filepath)
            except OSError:
                pass
        return False

    # 3. 调用Linux打印函数
    print_success = silent_print_pdf(pdf_filepath, printer_name)

    # 4. 清理临时文件
    if not keep_pdf_for_internal_debug:
        if os.path.exists(pdf_filepath):
            try:
                os.unlink(pdf_filepath)
                logger.info(f"PDF模块: 临时PDF文件 {pdf_filepath} 已删除。")
            except OSError as e:
                logger.warning(f"PDF模块: 删除临时PDF文件 {pdf_filepath} 失败: {e}")
    else:
        logger.info(f"PDF模块: 调试模式，保留PDF文件: {pdf_filepath}")

    return print_success


# --- 用于模块独立测试的代码 ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 准备测试数据
    sample_data = {
        "shop_name": "Linux模块测试店铺",
        "order_id": "PDF_LINUX_001",
        "created_at": datetime.datetime.now().isoformat(),
        # ... 其他你模板需要的字段 ...
    }

    logger.info("--- 开始 print_helper_pdf.py (Linux版) 模块独立测试 ---")

    # 直接调用主函数进行测试
    # 在没有打印机的环境下，可以只测试PDF生成，并保留文件
    print_order(sample_data, printer_name="TestPrinter", keep_pdf_for_internal_debug=True)
    # 这会生成一个PDF文件在你的临时目录，你可以去找到它并检查内容
    logger.info("--- 独立测试结束 ---")

