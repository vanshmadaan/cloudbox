import json
from typing import Any, Dict, Optional
import aioboto3
from botocore.config import Config

from app.core.config import settings
from app.core.logging import logger


class QueueService:
    """
    AWS SQS Asynchronous message dispatcher for background processing tasks.
    """

    def __init__(
        self,
        queue_url: Optional[str] = None,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.queue_url = queue_url or settings.SQS_QUEUE_URL
        self.region_name = region_name or settings.AWS_REGION
        self.endpoint_url = endpoint_url or settings.SQS_ENDPOINT_URL or None

        self.session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            aws_session_token=settings.AWS_SESSION_TOKEN,
            region_name=self.region_name,
        )
        self.boto_config = Config(
            retries={"max_attempts": 3, "mode": "standard"},
        )

    async def enqueue_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        delay_seconds: int = 0,
    ) -> Optional[str]:
        """
        Send a task message to the SQS queue.
        If SQS is not configured (e.g. local dev without SQS), logs message and returns None.
        """
        message_body = {
            "task_type": task_type,
            "payload": payload,
        }

        if not self.queue_url:
            logger.info(
                f"[QueueService-Local/Mock] Enqueued task '{task_type}': {json.dumps(payload)}"
            )
            return "mock-message-id"

        try:
            async with self.session.client(
                "sqs",
                endpoint_url=self.endpoint_url,
                config=self.boto_config,
            ) as sqs:
                response = await sqs.send_message(
                    QueueUrl=self.queue_url,
                    MessageBody=json.dumps(message_body),
                    DelaySeconds=delay_seconds,
                )
                message_id = response.get("MessageId")
                logger.info(f"Task '{task_type}' sent to SQS with MessageId {message_id}")
                return message_id
        except Exception as e:
            logger.error(f"Failed to send task '{task_type}' to SQS: {str(e)}")
            # In a resilient backend, we log the failure but do not break user-facing HTTP flow
            return None


def get_queue_service() -> QueueService:
    return QueueService()

