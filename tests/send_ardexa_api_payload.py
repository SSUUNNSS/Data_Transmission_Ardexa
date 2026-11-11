from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mqtt import DataType, MqttPublisher  # noqa: E402
from transmission.ardexa_payload import (  # noqa: E402
    build_hams_hall_telesignaling_payload,
    build_hams_hall_telemetry_payload,
    filter_exact_device_code_sources,
    load_hams_hall_mapping,
    split_telemetry_payload,
)
from transmission.config import load_runtime_config  # noqa: E402


DEFAULT_SOURCE = "BMU-01_LC-28_BSC-01_RACK-04"
DEFAULT_DEVICE_ID = "77eba054-9702-44c1-945c-9fe704e0af7e"
DEFAULT_WORKGROUP = "241429841"
DEFAULT_DEVICE_CODE_MAP = PROJECT_ROOT / "config" / "Hams_Hall_DevCode.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Hams Hall latest values and build a platform telemetry payload."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "Hams_Hall_local.json",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=PROJECT_ROOT / "config" / "data_type_mapping_hams_hall.json",
    )
    parser.add_argument("--workgroup", default=DEFAULT_WORKGROUP)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--source", help="One exact Ardexa source to send; omit with --all-exact-devices.")
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Multiple exact Ardexa sources to combine in one message.",
    )
    parser.add_argument(
        "--all-exact-devices",
        action="store_true",
        help="Send supported sources whose names exactly match Hams_Hall_DevCode.json.",
    )
    parser.add_argument(
        "--metric",
        help="Optional exact Ardexa metric name to include, e.g. 'DC Voltage'.",
    )
    parser.add_argument(
        "--dev-code",
        help="Override the platform topology code; otherwise load it from the device-code map.",
    )
    parser.add_argument("--device-code-map", type=Path, default=DEFAULT_DEVICE_CODE_MAP)
    parser.add_argument("--max-payload-bytes", type=int, default=65536)
    parser.add_argument(
        "--independent-messages",
        action="store_true",
        help="Set every telemetry chunk to packgeCount=1/packgeId=1 with a unique messageId.",
    )
    parser.add_argument("--output", type=Path, help="Optional output JSON file path.")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Actually publish after preview generation. Default is preview only.",
    )
    return parser.parse_args()


def get_api_token() -> str:
    token = os.getenv("ARDEXA_TOKEN")
    if token:
        return token
    if sys.platform == "win32":
        import winreg

        for hive, key_path in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    token, _ = winreg.QueryValueEx(key, "ARDEXA_TOKEN")
                    if token:
                        return str(token)
            except FileNotFoundError:
                continue
    raise ValueError("ARDEXA_TOKEN is not available in the process or Windows environment.")


def load_config_values(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("Runtime config must be a JSON object.")
    return config


def fetch_latest_values(token: str, workgroup: str, device_id: str) -> dict[str, Any]:
    url = (
        "https://eur1.ardexa.com/api/v1/devices/"
        f"{quote(workgroup, safe='')}/{quote(device_id, safe='')}/latestValues"
    )
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"table": "storage"},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Ardexa latestValues response must be a JSON object.")
    return payload


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    config_values = load_config_values(config_path)
    runtime_config = load_runtime_config(config_path)
    message_config = config_values.get("message", {})
    if not isinstance(message_config, dict):
        raise ValueError("Runtime config 'message' must be an object.")

    token = get_api_token()
    api_payload = fetch_latest_values(token, args.workgroup, args.device_id)
    mapping = load_hams_hall_mapping(args.mapping)
    with args.device_code_map.expanduser().resolve().open("r", encoding="utf-8") as code_file:
        device_codes = json.load(code_file)
    if not isinstance(device_codes, dict):
        raise ValueError("Device code map must be a JSON object.")
    if args.all_exact_devices and (args.source or args.sources or args.dev_code or args.metric):
        raise ValueError("--all-exact-devices cannot be combined with source/device/metric filters.")
    if args.source and args.sources:
        raise ValueError("Use either --source or --sources, not both.")
    if not args.all_exact_devices and not args.source:
        if not args.sources:
            args.source = DEFAULT_SOURCE
    if args.dev_code is not None:
        device_codes[args.source] = args.dev_code

    excluded_source_count = 0
    payload_source = api_payload
    if args.all_exact_devices:
        payload_source, excluded_source_count = filter_exact_device_code_sources(
            api_payload,
            device_id=args.device_id,
            device_codes=device_codes,
        )
    elif args.sources:
        api_records = api_payload.get(args.device_id)
        if not isinstance(api_records, dict):
            raise ValueError(f"API response has no records for device {args.device_id}.")
        missing_sources = [source for source in args.sources if source not in api_records]
        missing_codes = [source for source in args.sources if source not in device_codes]
        if missing_sources:
            raise ValueError(f"Requested API source(s) not found: {', '.join(missing_sources)}")
        if missing_codes:
            raise ValueError(f"Requested source(s) lack exact devCode entries: {', '.join(missing_codes)}")
        payload_source = {
            args.device_id: {source: api_records[source] for source in args.sources}
        }

    payload = build_hams_hall_telemetry_payload(
        payload_source,
        mapping,
        device_id=args.device_id,
        device_codes=device_codes,
        ps_id=str(message_config["ps_id"]),
        app_key=str(message_config["app_key"]),
        product_name=str(message_config["product_name"]),
        product_type=str(message_config["product_type"]),
        source_filter=None if args.all_exact_devices or args.sources else args.source,
        metric_filter=args.metric,
    )
    telemetry_packets = split_telemetry_payload(
        payload,
        args.max_payload_bytes,
        independent_messages=args.independent_messages,
    )
    signaling_payload = build_hams_hall_telesignaling_payload(
        payload_source,
        mapping,
        device_id=args.device_id,
        device_codes=device_codes,
        ps_id=str(message_config["ps_id"]),
        app_key=str(message_config["app_key"]),
        product_name=str(message_config["product_name"]),
        product_type=str(message_config["product_type"]),
        source_filter=None if args.all_exact_devices or args.sources else args.source,
        metric_filter=args.metric,
    )

    payload_to_write: Any = telemetry_packets if len(telemetry_packets) > 1 else telemetry_packets[0]
    payload_text = json.dumps(payload_to_write, ensure_ascii=False, indent=2)
    if args.output:
        output_path = args.output.expanduser().resolve()
        output_path.write_text(payload_text + "\n", encoding="utf-8")
        print(f"Payload written to: {output_path}")
    elif not args.all_exact_devices:
        print(payload_text)

    data_type = DataType.TELEMETRY
    topic = runtime_config.mqtt.topics.get_topic(data_type, runtime_config.mqtt.app_key)
    print(f"HTTP API status: 200")
    if args.all_exact_devices:
        print(f"Exact-matched supported sources: {sum(len(group['devList']) for packet in telemetry_packets for group in packet['businessData'])}")
        print(f"Excluded API sources (no exact devCode or unsupported type): {excluded_source_count}")
    print(f"Telemetry packets: {len(telemetry_packets)}")
    if args.independent_messages:
        print("Packet mode: independent messages (packgeCount=1, packgeId=1)")
    for packet in telemetry_packets:
        packet_bytes = len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        packet_devices = sum(len(group["devList"]) for group in packet["businessData"])
        print(f"  packet {packet['packgeId']}/{packet['packgeCount']}: {packet_devices} devices, {packet_bytes} bytes")
    print(f"Telemetry MQTT topic: {topic}")
    signaling_topic = runtime_config.mqtt.topics.get_topic(DataType.TELESIGNALING, runtime_config.mqtt.app_key)
    if signaling_payload is not None:
        print("Nonzero telesignaling payload:")
        print(json.dumps(signaling_payload, ensure_ascii=False, indent=2))
        print(f"Telesignaling MQTT topic: {signaling_topic}")
    else:
        print("No nonzero mapped telesignaling points; no faultdata message will be sent.")
    if not args.publish:
        print("Preview only. Add --publish to send this payload.")
        return 0

    publisher = MqttPublisher(runtime_config.mqtt)
    try:
        publisher.connect()
        for packet in telemetry_packets:
            result = publisher.publish(packet, data_type)
            if not result.success:
                print(
                    f"Telemetry packet {packet['packgeId']} failed after {result.attempts} attempt(s).",
                    file=sys.stderr,
                )
                return 1
            print(
                f"Telemetry packet {packet['packgeId']}/{packet['packgeCount']} published: "
                f"topic={result.topic}, payload_bytes={result.payload_bytes}"
            )
        if signaling_payload is not None:
            signaling_result = publisher.publish(signaling_payload, DataType.TELESIGNALING)
            if not signaling_result.success:
                print(
                    f"Telesignaling publish failed after {signaling_result.attempts} attempt(s).",
                    file=sys.stderr,
                )
                return 1
            print(
                f"Telesignaling publish succeeded: topic={signaling_result.topic}, "
                f"payload_bytes={signaling_result.payload_bytes}"
            )
        return 0
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, requests.RequestException, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from error