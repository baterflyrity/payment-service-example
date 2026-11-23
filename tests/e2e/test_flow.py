"""E2E smoke-тест против поднятого ``docker compose``.

Сценарий: POST платежа → consumer обрабатывает событие из очереди →
платёж переходит в ``succeeded``/``failed`` → webhook приходит на локальный
HTTP-приёмник. Приёмник запускается отдельным контейнером в сети compose,
чтобы consumer мог до него достучаться по имени контейнера.

Запуск (стек уже поднят с тем же ``API_KEY``)::

    docker compose up -d --build
    E2E_API_KEY=$API_KEY uv run pytest -m e2e -q
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e

API_URL = os.getenv("E2E_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("E2E_API_KEY") or os.getenv("API_KEY") or "e2e-api-key"
COMPOSE_SERVICE = "consumer"

PAYMENT_PROCESSING_TIMEOUT_SECONDS = 45.0
WEBHOOK_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5

WEBHOOK_RECEIVER_SCRIPT = """
import http.server


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        with open("/out/webhook.json", "wb") as target:
            target.write(body)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


http.server.HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
"""


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def api_is_reachable() -> bool:
    try:
        response = httpx.get(f"{API_URL}/health", timeout=3.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def compose_container_id(service: str) -> str | None:
    result = docker(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.service={service}",
        check=False,
    )
    container_id = result.stdout.strip().splitlines()
    return container_id[0] if container_id else None


def container_image(container_id: str) -> str:
    return docker(
        "inspect",
        "-f",
        "{{.Config.Image}}",
        container_id,
    ).stdout.strip()


def container_network(container_id: str) -> str:
    networks = docker(
        "inspect",
        "-f",
        "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}",
        container_id,
    ).stdout.strip()
    return networks.splitlines()[0] if networks else ""


def wait_for_receiver(container_name: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        probe = docker(
            "exec",
            container_name,
            "python",
            "-c",
            "import socket; socket.create_connection(('127.0.0.1', 8000), 1)",
            check=False,
        )
        if probe.returncode == 0:
            return
        time.sleep(POLL_INTERVAL_SECONDS)

    message = probe.stderr.strip() or "receiver did not start"
    pytest.fail(f"Webhook receiver is not ready: {message}")


@pytest.fixture
def webhook_receiver() -> Iterator[tuple[str, Path]]:
    """Поднимает контейнер-приёмник webhook и отдаёт (URL, файл с телом)."""

    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not available")

    consumer_id = compose_container_id(COMPOSE_SERVICE)
    if consumer_id is None:
        pytest.skip(
            f"docker compose service '{COMPOSE_SERVICE}' is not running",
        )

    image = container_image(consumer_id)
    network = container_network(consumer_id)
    container_name = f"e2e-webhook-{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory() as directory:
        output_dir = Path(directory)
        webhook_file = output_dir / "webhook.json"

        docker(
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "--network",
            network,
            "-v",
            f"{output_dir}:/out",
            image,
            "python",
            "-c",
            WEBHOOK_RECEIVER_SCRIPT,
        )

        try:
            wait_for_receiver(container_name)
            yield f"http://{container_name}:8000/webhook", webhook_file
        finally:
            docker("rm", "-f", container_name, check=False)


def wait_for_payment_status(
    client: httpx.Client,
    payment_id: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    deadline = time.monotonic() + PAYMENT_PROCESSING_TIMEOUT_SECONDS
    last_status = "unknown"

    while time.monotonic() < deadline:
        response = client.get(f"{API_URL}/api/v1/payments/{payment_id}", headers=headers)
        if response.status_code == 200:
            payment = response.json()
            last_status = payment["status"]
            if last_status in {"succeeded", "failed"}:
                return payment
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        f"Payment {payment_id} was not processed within "
        f"{PAYMENT_PROCESSING_TIMEOUT_SECONDS:.0f} s (last status: {last_status})",
    )


def wait_for_webhook(webhook_file: Path) -> dict[str, Any]:
    deadline = time.monotonic() + WEBHOOK_TIMEOUT_SECONDS
    last_error = "file does not exist yet"

    while time.monotonic() < deadline:
        if webhook_file.exists():
            raw = webhook_file.read_bytes()
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    last_error = f"invalid JSON: {exc}"
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(f"Webhook was not received: {last_error}")


def test_payment_lifecycle_sends_webhook(webhook_receiver: tuple[str, Path]) -> None:
    if not api_is_reachable():
        pytest.skip(f"API is not reachable at {API_URL}")

    webhook_url, webhook_file = webhook_receiver

    headers = {
        "X-API-Key": API_KEY,
        "Idempotency-Key": f"e2e-{uuid.uuid4()}",
    }
    payload = {
        "amount": "42.00",
        "currency": "RUB",
        "description": "E2E smoke payment",
        "metadata": {"source": "pytest-e2e"},
        "webhook_url": webhook_url,
    }

    with httpx.Client(timeout=10.0) as client:
        created = client.post(
            f"{API_URL}/api/v1/payments",
            headers=headers,
            json=payload,
        )
        assert created.status_code == 202, created.text
        creation = created.json()
        payment_id = creation["payment_id"]
        assert creation["status"] == "pending"

        payment = wait_for_payment_status(client, payment_id, headers)

        assert payment["status"] in {"succeeded", "failed"}
        assert payment["processed_at"] is not None
        assert payment["amount"] == "42.00"

    webhook = wait_for_webhook(webhook_file)

    assert webhook["payment_id"] == payment_id
    assert webhook["status"] == payment["status"]
    assert webhook["amount"] == "42.00"
    assert webhook["currency"] == "RUB"
    assert webhook["event_id"]
