import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx2

from app.consumer import EVENTS_EXCHANGE, QUEUE
from app.core.config import settings

MANAGEMENT_PORT = os.environ.get("RABBITMQ_MANAGEMENT_PORT", "15673")
VHOST = quote(settings.RABBITMQ_VHOST, safe="")


def wait_until(condition: Callable[[], Any], *, timeout: float = 30) -> None:
    """Poll until a condition holds, so tests never rely on a fixed delay.

    Args:
        condition (Callable[[], Any]): Returns something truthy when met.
        timeout (float, optional): Seconds to wait. Defaults to 30.

    Raises:
        AssertionError: If the condition never holds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"Condition not met within {timeout} seconds")


class Broker:
    """RabbitMQ's management API, which is how the contract's publisher sends."""

    def __init__(self) -> None:
        self.api = httpx2.Client(
            base_url=f"http://127.0.0.1:{MANAGEMENT_PORT}/api",
            auth=(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD),
            timeout=10,
        )

    def reset_vhost(self) -> None:
        """Recreate the test vhost, so each module starts with no topology."""
        self.api.delete(f"/vhosts/{VHOST}")
        self.api.put(f"/vhosts/{VHOST}").raise_for_status()
        self.api.put(
            f"/permissions/{VHOST}/{settings.RABBITMQ_USER}",
            json={"configure": ".*", "write": ".*", "read": ".*"},
        ).raise_for_status()

    def publish(self, body: dict[str, Any] | str, routing_key: str) -> bool:
        """Publish a persistent message the way Discovery's outbox does.

        Args:
            body (dict[str, Any] | str): An event, or raw text to send as is.
            routing_key (str): The routing key.

        Returns:
            bool: Whether the broker routed the message to a queue.
        """
        response = self.api.post(
            f"/exchanges/{VHOST}/{EVENTS_EXCHANGE}/publish",
            json={
                "properties": {"delivery_mode": 2, "content_type": "application/json"},
                "routing_key": routing_key,
                "payload": body if isinstance(body, str) else json.dumps(body),
                "payload_encoding": "string",
            },
        )
        response.raise_for_status()
        return response.json()["routed"]

    def get(self, path: str) -> Any:
        """Read a management API resource in the test vhost.

        Args:
            path (str): Resource type and name, such as `queues/name`.

        Returns:
            Any: The decoded response.
        """
        kind, _, rest = path.partition("/")
        response = self.api.get(f"/{kind}/{VHOST}/{rest}")
        response.raise_for_status()
        return response.json()

    def peek(self, queue: str) -> list[dict[str, Any]]:
        """Read a queue's waiting messages and leave them in place.

        Args:
            queue (str): Queue name.

        Returns:
            list[dict[str, Any]]: The messages, live rather than from the
            management API's delayed statistics.
        """
        response = self.api.post(
            f"/queues/{VHOST}/{queue}/get",
            json={"count": 100, "ackmode": "ack_requeue_true", "encoding": "auto"},
        )
        response.raise_for_status()
        return response.json()


class ConsumerProcess:
    """The real `python -m app.consumer`, started as it would be in production."""

    def __init__(self, log: Path, **env: str) -> None:
        self.log = log
        self.env = env
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        """Start the process and wait until it is consuming.

        A process that fails to start is stopped before raising. Left running
        it would reconnect and re-declare topology under later tests.

        Raises:
            AssertionError: If it exits or never starts consuming.
        """
        with self.log.open("ab") as output:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "app.consumer"],
                env=os.environ | self.env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            wait_until(self._is_consuming)
        except AssertionError as error:
            self.stop()
            raise AssertionError(f"{error}\n{self.logs()[-2000:]}") from None

    def _is_consuming(self) -> bool:
        """Check this process's own log, since nothing else is exclusive to it.

        Returns:
            bool: True once the process has started consuming.

        Raises:
            AssertionError: If the process has already exited.
        """
        assert self.process is not None
        if self.process.poll() is not None:
            raise AssertionError("Consumer exited during startup")
        return f"Consuming {QUEUE}" in self.logs()

    def stop(self) -> None:
        """Stop the process."""
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None

    def logs(self) -> str:
        """Return everything the process has logged.

        Returns:
            str: The log text.
        """
        return self.log.read_text(encoding="utf-8", errors="replace")
