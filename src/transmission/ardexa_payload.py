from __future__ import annotations

import json
import secrets
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


DEVICE_TYPES = {
    "RACK": "24",
    "DCDC": "25",
    "EMS": "26",
    "PCS": "37",
    "LC300": "47",
    "BSC": "52",
}
ZERO_CHANNEL_DEVICE_TYPES = frozenset({"11", "17", "13"})


def channel_id_for_device_type(device_type: str, ps_id: str) -> str:
    """Use channel 0 for platform device types 11, 17, and 13; otherwise use psId."""
    return "0" if str(device_type) in ZERO_CHANNEL_DEVICE_TYPES else str(ps_id)


def infer_hams_hall_device_type(source: str) -> tuple[str, str]:
    """Return the platform device name and code from the final source segment."""
    final_segment = source.rsplit("_", 1)[-1].strip().upper()

    for prefix, device_name, device_code in (
        ("RACK-", "Rack", DEVICE_TYPES["RACK"]),
        ("DCDC", "DCDC", DEVICE_TYPES["DCDC"]),
        ("D-", "DCDC", DEVICE_TYPES["DCDC"]),
        ("EMS", "Energy management system", DEVICE_TYPES["EMS"]),
        ("PCS-", "PCS", DEVICE_TYPES["PCS"]),
        ("BSC-", "BSC", DEVICE_TYPES["BSC"]),
    ):
        if final_segment.startswith(prefix):
            return device_name, device_code

    if final_segment == "LC300":
        return "LC", DEVICE_TYPES["LC300"]

    raise ValueError(f"Unsupported Hams Hall device source: {source}")


def load_hams_hall_mapping(path: Path) -> dict[str, list[dict[str, Any]]]:
    with path.expanduser().resolve().open("r", encoding="utf-8") as mapping_file:
        mapping = json.load(mapping_file)
    if not isinstance(mapping, dict):
        raise ValueError("Hams Hall data type mapping must be a JSON object.")
    return mapping


def filter_exact_device_code_sources(
    api_payload: Mapping[str, Any],
    *,
    device_id: str,
    device_codes: Mapping[str, str],
) -> tuple[dict[str, Any], int]:
    """Keep only supported API sources with an exact devCode-map key match."""
    device_records = api_payload.get(device_id, api_payload)
    if not isinstance(device_records, Mapping):
        raise ValueError(f"API response has no records for device {device_id}.")

    selected: dict[str, Any] = {}
    for source, record in device_records.items():
        if source not in device_codes or not isinstance(record, Mapping):
            continue
        try:
            infer_hams_hall_device_type(str(source))
        except ValueError:
            continue
        selected[str(source)] = record

    if not selected:
        raise ValueError("No API sources exactly match a supported devCode-map entry.")
    return {device_id: selected}, len(device_records) - len(selected)


def split_telemetry_payload(
    payload: Mapping[str, Any],
    max_payload_bytes: int,
    *,
    independent_messages: bool = False,
) -> list[dict[str, Any]]:
    """Split telemetry by whole devices while keeping every encoded message under the limit."""
    if max_payload_bytes <= 0:
        raise ValueError("max_payload_bytes must be greater than zero.")

    business_data = payload.get("businessData")
    if not isinstance(business_data, list):
        raise ValueError("Telemetry payload businessData must be an array.")

    devices = []
    for business_item in business_data:
        if not isinstance(business_item, Mapping):
            raise ValueError("Telemetry businessData entries must be objects.")
        recv_time = business_item.get("recvTime")
        ps_id = business_item.get("psId")
        dev_list = business_item.get("devList")
        if not isinstance(dev_list, list):
            raise ValueError("Telemetry businessData devList must be an array.")
        for device in dev_list:
            devices.append((ps_id, recv_time, device))

    def make_packet(packet_devices: list[tuple[Any, Any, Any]]) -> dict[str, Any]:
        groups: dict[tuple[Any, Any], list[Any]] = {}
        for ps_id, recv_time, device in packet_devices:
            groups.setdefault((ps_id, recv_time), []).append(device)
        result = dict(payload)
        result["businessData"] = [
            {"psId": ps_id, "recvTime": recv_time, "devList": group_devices}
            for (ps_id, recv_time), group_devices in groups.items()
        ]
        return result

    def encoded_size(packet: Mapping[str, Any]) -> int:
        return len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    chunks: list[dict[str, Any]] = []
    current: list[tuple[Any, Any, Any]] = []
    for device in devices:
        candidate = make_packet([*current, device])
        if encoded_size(candidate) <= max_payload_bytes:
            current.append(device)
            continue
        if not current:
            source = device[2].get("devCode", "unknown") if isinstance(device[2], Mapping) else "unknown"
            raise ValueError(f"Single device devCode={source} exceeds the {max_payload_bytes}-byte packet limit.")
        chunks.append(make_packet(current))
        current = [device]
        if encoded_size(make_packet(current)) > max_payload_bytes:
            source = device[2].get("devCode", "unknown") if isinstance(device[2], Mapping) else "unknown"
            raise ValueError(f"Single device devCode={source} exceeds the {max_payload_bytes}-byte packet limit.")

    if current:
        chunks.append(make_packet(current))
    if not chunks:
        raise ValueError("Telemetry payload contains no devices to packetize.")

    packet_count = len(chunks)
    base_message_id = str(payload.get("messageId", ""))
    if independent_messages:
        prefix, separator, suffix_text = base_message_id.rpartition("_")
        try:
            base_suffix = int(suffix_text) if separator else 0
        except ValueError:
            prefix = base_message_id
            base_suffix = secrets.randbelow(100)
        if packet_count > 100:
            raise ValueError("Independent message IDs support at most 100 chunks per sendTime.")
        for index, chunk in enumerate(chunks):
            chunk["messageId"] = f"{prefix}_{(base_suffix + index) % 100:02d}"
            chunk["packgeCount"] = "1"
            chunk["packgeId"] = "1"
    else:
        for index, chunk in enumerate(chunks, start=1):
            chunk["packgeCount"] = str(packet_count)
            chunk["packgeId"] = str(index)
        if encoded_size(chunk) > max_payload_bytes:
            raise ValueError(f"Packet {chunk['packgeId']} exceeds the {max_payload_bytes}-byte message limit.")

    for index, chunk in enumerate(chunks, start=1):
        if encoded_size(chunk) > max_payload_bytes:
            raise ValueError(f"Message {index} exceeds the {max_payload_bytes}-byte message limit.")
    return chunks


def _format_recv_time(record: Mapping[str, Any]) -> str:
    raw_time = record.get("event_time") or record.get("Datetime")
    if not isinstance(raw_time, str) or not raw_time:
        raise ValueError("API record is missing event_time/Datetime.")

    timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.strftime("%Y%m%d%H%M%S%f")[:17]


def _as_protocol_value(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _is_nonzero(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        raise ValueError(f"Signaling value must be numeric, got {value!r}.")


def _message_envelope(
    *,
    app_key: str,
    product_name: str,
    product_type: str,
    send_time: Optional[datetime],
    random_suffix: Optional[int],
) -> tuple[dict[str, str], str]:
    now = send_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    send_time_text = now.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = secrets.randbelow(100) if random_suffix is None else random_suffix
    if not 0 <= suffix <= 99:
        raise ValueError("random_suffix must be between 0 and 99.")
    public_data = {
        "productName": product_name,
        "productSN": app_key,
        "productType": str(product_type),
        "sendTime": send_time_text,
    }
    return public_data, f"{app_key}_{send_time_text}_{suffix:02d}"


def build_hams_hall_telesignaling_payload(
    api_payload: Mapping[str, Any],
    mapping: Mapping[str, list[dict[str, Any]]],
    *,
    device_id: str,
    device_codes: Mapping[str, str],
    ps_id: str,
    app_key: str,
    product_name: str,
    product_type: str,
    send_time: Optional[datetime] = None,
    random_suffix: Optional[int] = None,
    source_filter: Optional[str] = None,
    metric_filter: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Build a faultdata payload from mapped, nonzero Ardexa signaling values."""
    device_records = api_payload.get(device_id, api_payload)
    if not isinstance(device_records, Mapping):
        raise ValueError(f"API response has no records for device {device_id}.")

    grouped_devices: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for source, record in device_records.items():
        if source_filter and source != source_filter:
            continue
        if not isinstance(record, Mapping):
            continue

        inferred_type, protocol_device_type = infer_hams_hall_device_type(str(source))
        dev_code = device_codes.get(str(source))
        if dev_code is None:
            raise ValueError(f"Missing topology devCode for source '{source}'.")

        data_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
        recv_time = _format_recv_time(record)
        for metric_name, value in record.items():
            if metric_filter and metric_name != metric_filter:
                continue
            entries = mapping.get(str(metric_name), [])
            signaling_entries = [
                entry
                for entry in entries
                if isinstance(entry, Mapping)
                and str(entry.get("type", "")).casefold() == "telesignaling"
                and str(entry.get("Device Type", "")).casefold() == inferred_type.casefold()
            ]
            if not signaling_entries or not _is_nonzero(value):
                continue

            for entry in signaling_entries:
                point_number = entry.get("Measurement Point Number")
                if point_number is None or str(point_number) == "测点编号":
                    continue

                metric_lower = str(metric_name).casefold()
                if "fault" in metric_lower:
                    fault_type = "1"
                elif "alarm" in metric_lower:
                    fault_type = "2"
                elif "prompt" in metric_lower:
                    fault_type = "3"
                else:
                    raise ValueError(f"Cannot infer faultType from signaling metric '{metric_name}'.")

                point_id = str(point_number)
                value_text = _as_protocol_value(value)
                if value_text is None:
                    continue
                event_key = (point_id, fault_type, value_text)
                data_by_key[event_key] = {
                    "faultType": fault_type,
                    "sourceType": "1",
                    "msgTime": recv_time,
                    "id": point_id,
                    "value": value_text,
                }

        if not data_by_key:
            continue

        chnnl_id = channel_id_for_device_type(protocol_device_type, ps_id)
        grouped_devices[recv_time][str(source)] = {
            "devType": protocol_device_type,
            "devCode": str(dev_code),
            "chnnlId": chnnl_id,
            "psKey": f"{ps_id}_{protocol_device_type}_{dev_code}_{chnnl_id}",
            "data": [data_by_key[key] for key in sorted(data_by_key)],
        }

    if not grouped_devices:
        return None

    public_data, message_id = _message_envelope(
        app_key=app_key,
        product_name=product_name,
        product_type=product_type,
        send_time=send_time,
        random_suffix=random_suffix,
    )
    business_data = [
        {
            "psId": str(ps_id),
            "dataList": [devices[source] for source in sorted(devices)],
        }
        for _, devices in sorted(grouped_devices.items())
    ]
    return {
        "messageId": message_id,
        "packgeCount": "1",
        "packgeId": "1",
        "publicData": public_data,
        "businessData": business_data,
    }


def build_hams_hall_telemetry_payload(
    api_payload: Mapping[str, Any],
    mapping: Mapping[str, list[dict[str, Any]]],
    *,
    device_id: str,
    device_codes: Mapping[str, str],
    ps_id: str,
    app_key: str,
    product_name: str,
    product_type: str,
    send_time: Optional[datetime] = None,
    random_suffix: Optional[int] = None,
    source_filter: Optional[str] = None,
    metric_filter: Optional[str] = None,
) -> dict[str, Any]:
    """Convert Ardexa latestValues records into the platform telemetry format."""
    device_records = api_payload.get(device_id, api_payload)
    if not isinstance(device_records, Mapping):
        raise ValueError(f"API response has no records for device {device_id}.")

    grouped_devices: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for source, record in device_records.items():
        if source_filter and source != source_filter:
            continue
        if not isinstance(record, Mapping):
            continue

        inferred_type, protocol_device_type = infer_hams_hall_device_type(str(source))
        dev_code = device_codes.get(str(source))
        if dev_code is None:
            raise ValueError(f"Missing topology devCode for source '{source}'.")

        data: dict[str, str] = {}
        for metric_name, value in record.items():
            if metric_filter and metric_name != metric_filter:
                continue
            protocol_value = _as_protocol_value(value)
            if protocol_value is None:
                continue

            entries = mapping.get(str(metric_name), [])
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                if str(entry.get("type", "")).casefold() != "telemetry":
                    continue
                if str(entry.get("Device Type", "")).casefold() != inferred_type.casefold():
                    continue

                point_number = entry.get("Measurement Point Number")
                if point_number is None or str(point_number) == "测点编号":
                    continue
                point_id = str(point_number)
                previous = data.get(point_id)
                if previous is not None and previous != protocol_value:
                    raise ValueError(
                        f"Conflicting values map to measurement point {point_id} for '{source}'."
                    )
                data[point_id] = protocol_value

        if not data:
            continue

        recv_time = _format_recv_time(record)
        grouped_devices[recv_time][str(source)] = {
            "devType": protocol_device_type,
            "devCode": str(dev_code),
            "chnnlId": channel_id_for_device_type(protocol_device_type, ps_id),
            "data": data,
        }

    if not grouped_devices:
        raise ValueError("No telemetry points matched the Hams Hall mapping.")

    now = send_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    send_time_text = now.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = secrets.randbelow(100) if random_suffix is None else random_suffix
    if not 0 <= suffix <= 99:
        raise ValueError("random_suffix must be between 0 and 99.")

    business_data = [
        {
            "psId": str(ps_id),
            "recvTime": recv_time,
            "devList": [devices[source] for source in sorted(devices)],
        }
        for recv_time, devices in sorted(grouped_devices.items())
    ]

    return {
        "messageId": f"{app_key}_{send_time_text}_{suffix:02d}",
        "packgeCount": "1",
        "packgeId": "1",
        "publicData": {
            "productName": product_name,
            "productSN": app_key,
            "productType": str(product_type),
            "sendTime": send_time_text,
        },
        "businessData": business_data,
    }