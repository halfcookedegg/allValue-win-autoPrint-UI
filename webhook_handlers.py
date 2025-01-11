from app import process_order_webhook
from flask import jsonify
import logging

logger = logging.getLogger(__name__)

class WebhookHandler:
    """Webhook 处理器的基类。"""
    def handle(self, request, data):
        """处理 Webhook 请求。"""
        raise NotImplementedError

class OrderPaidHandler(WebhookHandler):
    """处理 orders/paid Webhook。"""
    def handle(self, request, data):
        logger.info("orders/paid Webhook received (Not Implemented)")
        return jsonify({"status": "success",
                        "message": "orders/paid webhook received but not implemented yet"}), 200

# 为其他 topic 创建空处理类
class OrderPartiallyFulfilledHandler(WebhookHandler):
    """处理 orders/partially_fulfilled Webhook。"""
    def handle(self, request, data):
        logger.info("orders/partially_fulfilled Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "orders/partially_fulfilled webhook received but not implemented yet"}), 200

class OrderFulfilledHandler(WebhookHandler):
    """处理 orders/fulfilled Webhook。"""
    def handle(self, request, data):
        logger.info("orders/fulfilled Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "orders/fulfilled webhook received but not implemented yet"}), 200
class OrderCreateHandler(WebhookHandler):
    """处理 orders/create Webhook。"""
    def handle(self, request, data):
        logger.info("orders/create Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "orders/create webhook received but not implemented yet"}), 200

class OrderPaymentConfirmedHandler(WebhookHandler):
    def handle(self, request, data):
        order_node_id = data.get('orderNodeId')
        if not order_node_id:
            logger.warning("orders/payment_confirmed Webhook 缺少 orderNodeId")
            return jsonify({"status": "fail", "msg": "Missing orderNodeId"}), 400

        if not process_order_webhook(order_node_id): #复用process_order_webhook函数
            return jsonify({"status": "fail", "msg": "Failed to process order"}), 500

        return jsonify({"status": "success"}), 200

class RefundCreateHandler(WebhookHandler):
    """处理 refunds/create Webhook。"""
    def handle(self, request, data):
        logger.info("refunds/create Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "refunds/create webhook received but not implemented yet"}), 200

class GoodsCreateHandler(WebhookHandler):
    """处理 goods/create Webhook。"""
    def handle(self, request, data):
        logger.info("goods/create Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "goods/create webhook received but not implemented yet"}), 200

class GoodsUpdateHandler(WebhookHandler):
    """处理 goods/update Webhook。"""
    def handle(self, request, data):
        logger.info("goods/update Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "goods/update webhook received but not implemented yet"}), 200

class GoodsRemoveHandler(WebhookHandler):
    """处理 goods/remove Webhook。"""
    def handle(self, request, data):
        logger.info("goods/remove Webhook received (Not Implemented)")
        return jsonify({"status": "success", "message": "goods/remove webhook received but not implemented yet"}), 200


webhook_handlers = {
    "orders/paid": OrderPaidHandler(),
    "orders/partially_fulfilled": OrderPartiallyFulfilledHandler(),
    "orders/fulfilled": OrderFulfilledHandler(),
    "orders/create":OrderCreateHandler(),
    "orders/payment_confirmed":OrderPaymentConfirmedHandler(),
    "refunds/create": RefundCreateHandler(),
    "goods/create": GoodsCreateHandler(),
    "goods/update": GoodsUpdateHandler(),
    "goods/remove": GoodsRemoveHandler(),
}