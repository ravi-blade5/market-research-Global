from __future__ import annotations

from google.cloud import tasks_v2
from google.protobuf import duration_pb2

from app.config import Settings


class RunTaskDispatcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = tasks_v2.CloudTasksClient()

    def enqueue_run(self, run_id: str) -> str:
        if not self.settings.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required for Cloud Tasks dispatch")
        if not self.settings.public_base_url:
            raise ValueError("PUBLIC_BASE_URL is required for Cloud Tasks dispatch")
        if not self.settings.task_dispatch_token:
            raise ValueError("TASK_DISPATCH_TOKEN is required for Cloud Tasks dispatch")

        parent = self.client.queue_path(
            self.settings.gcp_project_id,
            self.settings.cloud_tasks_location,
            self.settings.cloud_tasks_queue,
        )
        deadline = duration_pb2.Duration()
        deadline.FromSeconds(max(15, min(self.settings.cloud_tasks_dispatch_deadline_seconds, 1800)))
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.settings.public_base_url.rstrip('/')}/api/runs/{run_id}/execute-task",
                "headers": {
                    "X-Task-Dispatch-Token": self.settings.task_dispatch_token,
                    "Content-Type": "application/json",
                },
                "body": b"{}",
            },
            "dispatch_deadline": deadline,
        }
        response = self.client.create_task(request={"parent": parent, "task": task})
        return response.name


def should_use_cloud_tasks(settings: Settings) -> bool:
    return settings.run_execution_backend.lower().strip() in {"cloud_tasks", "cloudtasks", "tasks"}
