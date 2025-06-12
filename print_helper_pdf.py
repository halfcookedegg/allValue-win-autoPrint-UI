# print_helper_pdf.py

import logging
import datetime
import os
import subprocess
import tempfile
import win32print
from jinja2 import Environment, FileSystemLoader, select_autoescape


try:
    from weasyprint import HTML, CSS

    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    _temp_logger = logging.getLogger(__name__)
    _temp_logger.warning("WeasyPrint库未安装。请运行 'pip install WeasyPrint'。PDF生成功能将不可用。")
except OSError as e:
    WEASYPRINT_AVAILABLE = False
    _temp_logger = logging.getLogger(__name__)
    _temp_logger.warning(f"WeasyPrint 底层依赖可能缺失 : {e}。PDF生成功能将不可用。")

logger = logging.getLogger(__name__)


def generate_receipt_html(order_data):
    template_folder_path = 'templates'

    try:
        env = Environment(
            loader=FileSystemLoader(searchpath=template_folder_path),
            autoescape=select_autoescape(['html', 'xml'])
        )
        template = env.get_template('receipt_template.html')  # 模板文件名

        context = {
            'order': order_data,
            'current_print_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        html_output = template.render(context)
        return html_output
    except ImportError:
        logger.error("Jinja2库似乎未正确安装。")
        return None
    except Exception as e:
        logger.error(f"渲染HTML模板 'receipt_template.html' 时出错: {e}", exc_info=True)
        return None


def generate_pdf_from_html_content(html_content, pdf_filepath):
    """使用 WeasyPrint 将HTML字符串转换为PDF文件。"""
    if not WEASYPRINT_AVAILABLE:
        logger.error("PDF模块: WeasyPrint库不可用，无法生成PDF。")
        return False
    try:
        page_style = CSS(string='@page { size: 72mm auto; margin: 0; }')

        HTML(string=html_content, base_url=os.getcwd()).write_pdf(
            pdf_filepath,
            stylesheets = [page_style]
        )
        logger.info(f"PDF文件已生成: {pdf_filepath}")
        return True
    except Exception as e:
        logger.error(f"从HTML生成PDF时出错: {e}", exc_info=True)
        return False




def silent_print_pdf_windows(pdf_filepath, printer_name=None):
    """
    在Windows上尝试静默打印PDF文件。
    优先使用SumatraPDF（如果可用），其次尝试Acrobat Reader。
    """
    # 尝试 SumatraPDF
    sumatra_exe_path = "SumatraPDF.exe"  # 假设在系统PATH中或当前目录
    try:
        # subprocess.run([sumatra_exe_path, "-help"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        #                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        # logger.info(f"尝试使用SumatraPDF: {sumatra_exe_path}")

        print_args = [sumatra_exe_path, "-print-to"]
        target_printer = printer_name
        if not target_printer:
            try:
                target_printer = win32print.GetDefaultPrinter()
                logger.info(f"未指定打印机，将使用默认打印机 (SumatraPDF): {target_printer}")
            except Exception as e_printer:
                logger.error(f"获取默认打印机失败: {e_printer}。SumatraPDF打印需要有效打印机名。")
                return False

        print_args.append(target_printer)
        print_args.extend(["-silent", "-exit-when-done", pdf_filepath])

        logger.info(f"执行SumatraPDF打印命令: {' '.join(print_args)}")
        subprocess.run(print_args, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        logger.info(f"PDF '{pdf_filepath}' 已通过SumatraPDF发送到打印队列。")
        return True
    except Exception as e_sumatra:  # 包括 FileNotFoundError, CalledProcessError, TimeoutExpired
        logger.warning(f"使用SumatraPDF打印失败: {e_sumatra}. 将尝试Acrobat Reader。")

        # 尝试 Acrobat Reader
        acrobat_common_paths = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Adobe", "Acrobat Reader DC", "Reader",
                         "AcroRd32.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Adobe", "Acrobat Reader DC", "Reader", "AcroRd32.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Adobe", "Reader 11.0", "Reader", "AcroRd32.exe"),
            # Acrobat Reader XI
            # 可以根据需要添加更多Acrobat版本的常见路径
        ]
        acrobat_exe_path = next((path for path in acrobat_common_paths if os.path.exists(path)), None)

        if not acrobat_exe_path:
            logger.error("SumatraPDF 和 Acrobat Reader 均无法用于静默打印。")
            logger.info("提示: 可以尝试 'os.startfile(pdf_filepath, \"print\")' 进行非静默打印作为后备。")
            return False
        try:
            logger.info(f"尝试使用Acrobat Reader: {acrobat_exe_path}")
            print_cmd = [acrobat_exe_path, "/N", "/T", pdf_filepath]  # /N 新实例, /T 打印
            target_printer_acrobat = printer_name
            if not target_printer_acrobat:
                try:
                    target_printer_acrobat = win32print.GetDefaultPrinter()
                    logger.info(f"未指定打印机，将使用默认打印机 (Acrobat): {target_printer_acrobat}")
                except Exception as e_printer:
                    logger.error(f"获取默认打印机失败: {e_printer}。Acrobat /T 命令需要有效打印机名。")
                    return False
            print_cmd.append(target_printer_acrobat)
            # Acrobat 的 /T 参数有时还需要驱动名和端口名，但对很多网络打印机，仅打印机名就够了。
            # print_cmd.extend([driver_name, port_name]) # 这两个通常难以动态获取且非必需

            logger.info(f"执行Acrobat Reader打印命令: {' '.join(print_cmd)}")
            subprocess.run(print_cmd, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            logger.info(f"PDF '{pdf_filepath}' 已通过Acrobat Reader发送到打印队列。")
            return True
        except Exception as e_acrobat:
            logger.error(f"使用Acrobat Reader打印失败: {e_acrobat}")
            return False


def print_order(order_data, printer_name=None, keep_pdf_for_internal_debug=False):
    """
    主接口函数：生成订单PDF并尝试静默打印。
    app.py 应确保 order_data 中包含 'shop_name' 等模板所需信息。
    """
    logger.info(f"PDF模块: 处理订单 {order_data.get('order_id')}，打印机: '{printer_name if printer_name else '默认'}'")

    if not WEASYPRINT_AVAILABLE:
        logger.error("PDF模块: WeasyPrint库或其依赖不可用，无法执行打印。")
        return False

    if 'shop_name' not in order_data:
        logger.warning("PDF模块: order_data 中缺少 'shop_name'。HTML模板将使用默认值或可能出错。")

    html_content = generate_receipt_html(order_data)
    if not html_content:
        logger.error("PDF模块: 生成HTML内容失败。")
        return False

    # 使用 tempfile 创建临时PDF文件
    fd, pdf_filepath = tempfile.mkstemp(suffix=".pdf", prefix="receipt_")
    os.close(fd)  # 关闭文件描述符，以便其他进程可以写入该路径

    logger.debug(f"PDF模块: 临时PDF文件路径: {pdf_filepath}")

    if not generate_pdf_from_html_content(html_content, pdf_filepath):
        if os.path.exists(pdf_filepath):
            try:
                os.unlink(pdf_filepath)
            except OSError:
                logger.debug(f"PDF模块: 清理生成失败的临时文件 {pdf_filepath} 时出错 (可能文件未完全创建)。")
        return False

    print_success = False
    if os.name == 'nt':  # Windows特定静默打印逻辑
        print_success = silent_print_pdf_windows(pdf_filepath, printer_name)
    else:
        logger.error(f"PDF模块: 此模块中的静默打印功能主要为Windows优化。当前系统: {os.name}。")
        # 可在此处添加针对其他操作系统的打印逻辑，或简单返回False

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


if __name__ == '__main__':
    # 配置基本日志，方便模块独立测试时查看输出
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    sample_order_data = {
        "shop_name": "美味轩PDF小票 (模块测试)",  # 确保测试时有shop_name
        "order_id": "PDF_MODULE_001",
        "created_at": datetime.datetime.now().isoformat(),
        "customer_info": {"firstName": "张", "lastName": "伟"},
        "shipping_address": {
            "phone": "13812345678",
            "address1": "演示省演示市演示区",
            "address2": "演示路123号",
            "zip": "100000",
            "countryCode": "CN"
        },
        "contact_email": "zhangwei@example.com",
        "line_items": [
            {"name": "招牌炒河粉", "quantity": 1, "option_values": ["加牛肉", "少油"]},
            {"name": "柠檬水", "quantity": 1, "option_values": []}
        ],
        "total_price": {"amount": "48.50", "currency_code": "CNY"},
        "customer_message": "请提供餐具，谢谢。"
    }

    logger.info("--- 开始 print_helper_pdf.py 模块独立测试 ---")

    # 1. 测试HTML和PDF生成 (核心功能)
    logger.info("步骤1: 测试HTML内容生成...")
    html_output = generate_receipt_html(sample_order_data)
    if html_output:
        test_pdf_filename = "test_receipt_standalone.pdf"
        logger.info(f"步骤2: 测试PDF文件生成 (保存为 {test_pdf_filename})...")
        if generate_pdf_from_html_content(html_output, test_pdf_filename):
            logger.info(f"测试PDF已生成: {test_pdf_filename}。请手动打开此文件检查内容和排版。")
        else:
            logger.error("模块独立测试：PDF生成失败。")
    else:
        logger.error("模块独立测试：HTML内容生成失败。")

    logger.info("--- print_helper_pdf.py 模块独立测试结束 ---")