from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mqtt import DataType, MqttPublisher  # noqa: E402
from transmission.config import load_runtime_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or publish a custom JSON MQTT payload."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "test_local.json",
        help="Runtime config containing broker, TLS, and credentials.",
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=Path(__file__).resolve().parent / "sample_custom_payload.json",
        help="JSON file containing the complete payload object to send.",
    )
    parser.add_argument(
        "--data-type",
        choices=[item.value for item in DataType],
        default=DataType.TELEMETRY.value,
        help="Used to select the configured topic unless --topic is provided.",
    )
    parser.add_argument(
        "--topic",
        help="Optional explicit MQTT topic override.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Actually connect and publish. Without this flag, only preview.",
    )
    return parser.parse_args()


def load_payload(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open("r", encoding="utf-8") as payload_file:
        payload = json.load(payload_file)
    if not isinstance(payload, dict):
        raise ValueError("The payload JSON top level must be an object.")
    return payload


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config.expanduser().resolve())
    payload = load_payload(args.payload)
    data_type = DataType(args.data_type)
    topic = args.topic or config.mqtt.topics.get_topic(data_type, config.mqtt.app_key)

    print(f"Broker: {config.mqtt.host}:{config.mqtt.port}")
    print(f"TLS enabled by config: {config.mqtt.encrypted or config.mqtt.tls.enabled}")
    print(f"Data type: {data_type.value}")
    print(f"Topic: {topic}")
    print("Payload:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not args.publish:
        print("Preview only. Add --publish to send this payload.")
        return 0

    publisher = MqttPublisher(config.mqtt)
    try:
        publisher.connect()
        result = publisher.publish(payload, data_type, topic_override=topic)
        if not result.success:
            print(f"Publish failed after {result.attempts} attempt(s).", file=sys.stderr)
            return 1
        print(
            f"Publish succeeded: topic={result.topic}, "
            f"payload_bytes={result.payload_bytes}, attempts={result.attempts}"
        )
        return 0
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from error