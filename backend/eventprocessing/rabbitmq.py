import json
import logging
from datetime import datetime

import pika

from backend.config.settings import settings

logger = logging.getLogger(__name__)

QUEUES = [
    "alert_ingest",
    "stage1_identify",
    "stage2_execute",
    "stage3_validate",
]


class _DatetimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def get_connection() -> pika.BlockingConnection:
    params = pika.URLParameters(settings.rabbitmq_url)
    return pika.BlockingConnection(params)


def declare_queues(channel: pika.adapters.blocking_connection.BlockingChannel):
    for q in QUEUES:
        channel.queue_declare(queue=q, durable=True)


def publish(queue: str, message: dict):
    conn = get_connection()
    ch = conn.channel()
    declare_queues(ch)
    ch.basic_publish(
        exchange="",
        routing_key=queue,
        body=json.dumps(message, cls=_DatetimeEncoder),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    conn.close()


def consume(queue: str, callback):
    conn = get_connection()
    ch = conn.channel()
    declare_queues(ch)
    ch.basic_qos(prefetch_count=1)

    def _on_message(ch, method, _properties, body):
        msg = json.loads(body)
        try:
            callback(msg)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception("Error processing message from %s", queue)
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    ch.basic_consume(queue=queue, on_message_callback=_on_message)
    logger.info("Consuming from %s", queue)
    ch.start_consuming()
