import asyncio
import json
from typing import Any, Dict, List

from app.core.logging import logger
from app.worker.tasks import process_file_task, purge_retention_task


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for SQS event source mapping.
    Processes queued tasks asynchronously and returns batch item failures.
    """
    records: List[Dict[str, Any]] = event.get("Records", [])
    logger.info(f"Worker Lambda received {len(records)} records from SQS")

    batch_item_failures: List[Dict[str, str]] = []

    async def _process_all():
        for record in records:
            message_id = record.get("messageId", "")
            try:
                raw_body = record.get("body", "{}")
                data = json.loads(raw_body)
                task_type = data.get("task_type")
                payload = data.get("payload", {})

                logger.info(f"Processing SQS message {message_id} with task_type: {task_type}")

                if task_type == "process_file":
                    await process_file_task(payload)
                elif task_type == "purge_expired_files":
                    await purge_retention_task(payload)
                else:
                    logger.warning(f"Unknown task type received: {task_type}")

            except Exception as e:
                logger.error(f"Failed to process SQS record {message_id}: {str(e)}")
                batch_item_failures.append({"itemIdentifier": message_id})

    # Run the async batch processing
    asyncio.run(_process_all())

    # Return standard AWS SQS partial batch response
    return {"batchItemFailures": batch_item_failures}

