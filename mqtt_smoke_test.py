from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mqtt import DataType, MqttPublisher  # noqa: E402
from transmission.config import SendMode, load_runtime_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or send one MQTT telemetry smoke-test message."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "test_local.json",
        help="Runtime JSON config path (credentials are read from this file).",
    )
    parser.add_argument(
        "--send-mode",
        choices=[SendMode.NORMAL.value, SendMode.HISTORY_DATA.value],
        default=SendMode.NORMAL.value,
        help="Select the telemetry topic; defaults to normal.",
    )
    parser.add_argument(
        "--dev-char",
        default="MQTT_SMOKE_TEST",
        help="Device identifier included in the test payload.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Actually connect and publish. Without this flag, only preview the message.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config.expanduser().resolve())
    topic = (
        config.mqtt.topics.get_history_data_topic(config.mqtt.app_key)
        if args.send_mode == SendMode.HISTORY_DATA.value
        else config.mqtt.topics.get_topic(DataType.TELEMETRY, config.mqtt.app_key)
    )
    message = {
        "timestamp": int(time.time()),
        "psId": config.message.ps_id,
        "appkey": config.message.app_key,
        "source": config.message.source,
        "devChar": args.dev_char,
        "data": {"mqtt_smoke_test": 1},
    }

    print(f"Broker: {config.mqtt.host}:{config.mqtt.port}")
    print(f"TLS enabled by config: {config.mqtt.encrypted or config.mqtt.tls.enabled}")
    print(f"Topic: {topic}")
    print("Payload:")
    print(json.dumps(message, ensure_ascii=False, indent=2))

    if not args.publish:
        print("Preview only. Add --publish to send this test message.")
        return 0

    publisher = MqttPublisher(config.mqtt)
    try:
        publisher.connect()
        result = publisher.publish(message, DataType.TELEMETRY, topic_override=topic)
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
    raise SystemExit(main())