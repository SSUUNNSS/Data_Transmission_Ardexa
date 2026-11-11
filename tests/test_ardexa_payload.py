import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transmission.ardexa_payload import (
    build_hams_hall_telesignaling_payload,
    build_hams_hall_telemetry_payload,
    channel_id_for_device_type,
    filter_exact_device_code_sources,
    infer_hams_hall_device_type,
    split_telemetry_payload,
)


class HamsHallPayloadTests(unittest.TestCase):
    def test_channel_id_rule(self):
        for device_type in ("11", "17", "13"):
            with self.subTest(device_type=device_type):
                self.assertEqual(channel_id_for_device_type(device_type, "63"), "0")
                self.assertEqual(channel_id_for_device_type(device_type, "64"), "0")
        self.assertEqual(channel_id_for_device_type("24", "63"), "63")
        self.assertEqual(channel_id_for_device_type("52", "64"), "64")

    def test_infers_device_type_from_final_source_segment(self):
        cases = {
            "BMU-01_LC-01_BSC-01": ("BSC", "52"),
            "BMU-01_LC-01_BSC-01_RACK-01": ("Rack", "24"),
            "BMU-01_LC-01_LC300": ("LC", "47"),
            "BMU-01_LC-01_PCS-01": ("PCS", "37"),
            "BMU-01_LC-01_DCDC-01": ("DCDC", "25"),
            "BMU-01_LC-01_D-07": ("DCDC", "25"),
            "BMU-01_LC-01_EMS-01": ("Energy management system", "26"),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(infer_hams_hall_device_type(source), expected)

    def test_builds_soc_telemetry_payload_with_17_digit_recv_time(self):
        source = "BMU-01_LC-28_BSC-01_RACK-04"
        api_payload = {
            "device-uuid": {
                source: {
                    "SOC": 70.9,
                    "event_time": "2026-11-03T09:48:41.259+00:00",
                    "source": source,
                }
            }
        }
        mapping = {
            "SOC": [
                {"Measurement Point Number": "31003", "type": "Telemetry", "Device Type": "Rack"},
                {"Measurement Point Number": "50054", "type": "Telemetry", "Device Type": "BSC"},
            ]
        }

        payload = build_hams_hall_telemetry_payload(
            api_payload,
            mapping,
            device_id="device-uuid",
            device_codes={source: "42"},
            ps_id="63",
            app_key="app-key",
            product_name="BW Hams Hall",
            product_type="1063",
            send_time=datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc),
            random_suffix=22,
            source_filter=source,
            metric_filter="SOC",
        )

        self.assertEqual(payload["messageId"], "app-key_20261103100000_22")
        self.assertEqual(payload["packgeCount"], "1")
        self.assertEqual(payload["packgeId"], "1")
        self.assertEqual(payload["publicData"], {
            "productName": "BW Hams Hall",
            "productSN": "app-key",
            "productType": "1063",
            "sendTime": "20261103100000",
        })
        self.assertEqual(payload["businessData"], [{
            "psId": "63",
            "recvTime": "20261103094841259",
            "devList": [{
                "devType": "24",
                "devCode": "42",
                "chnnlId": "63",
                "data": {"31003": "70.9"},
            }],
        }])

    def test_requires_topology_code_for_mapped_device(self):
        source = "BMU-01_LC-01_BSC-01_RACK-01"
        with self.assertRaisesRegex(ValueError, "Missing topology devCode"):
            build_hams_hall_telemetry_payload(
                {"device-uuid": {source: {"SOC": 70.9, "event_time": "2026-11-03T09:00:00Z"}}},
                {"SOC": [{"Measurement Point Number": "31003", "type": "Telemetry", "Device Type": "Rack"}]},
                device_id="device-uuid",
                device_codes={},
                ps_id="63",
                app_key="app-key",
                product_name="BW Hams Hall",
                product_type="1063",
                source_filter=source,
            )

    def test_builds_only_nonzero_telesignaling_points(self):
        source = "BMU-01_LC-01_BSC-01_RACK-01"
        api_payload = {
            "device-uuid": {
                source: {
                    "CMU Fault: Short Circuit": 1,
                    "CMU Alarm 2: Pack Under Voltage": 0,
                    "event_time": "2026-11-04T09:10:11.123+00:00",
                }
            }
        }
        mapping = {
            "CMU Fault: Short Circuit": [
                {"Measurement Point Number": "33667", "type": "Telesignaling", "Device Type": "Rack"}
            ],
            "CMU Alarm 2: Pack Under Voltage": [
                {"Measurement Point Number": "33611", "type": "Telesignaling", "Device Type": "Rack"}
            ],
        }

        payload = build_hams_hall_telesignaling_payload(
            api_payload,
            mapping,
            device_id="device-uuid",
            device_codes={source: "10003"},
            ps_id="63",
            app_key="app-key",
            product_name="BW Hams Hall",
            product_type="1063",
            send_time=datetime(2026, 11, 4, 9, 11, tzinfo=timezone.utc),
            random_suffix=7,
            source_filter=source,
        )

        self.assertEqual(payload["businessData"], [{
            "psId": "63",
            "dataList": [{
                "devType": "24",
                "devCode": "10003",
                "chnnlId": "63",
                "psKey": "63_24_10003_63",
                "data": [{
                    "faultType": "1",
                    "sourceType": "1",
                    "msgTime": "20261104091011123",
                    "id": "33667",
                    "value": "1",
                }],
            }],
        }])

    def test_returns_none_when_no_nonzero_signaling_points(self):
        source = "BMU-01_LC-01_BSC-01_RACK-01"
        payload = build_hams_hall_telesignaling_payload(
            {"device-uuid": {source: {"CMU Fault: Short Circuit": 0, "event_time": "2026-11-04T09:10:11Z"}}},
            {"CMU Fault: Short Circuit": [{"Measurement Point Number": "33667", "type": "Telesignaling", "Device Type": "Rack"}]},
            device_id="device-uuid",
            device_codes={source: "10003"},
            ps_id="63",
            app_key="app-key",
            product_name="BW Hams Hall",
            product_type="1063",
            source_filter=source,
        )
        self.assertIsNone(payload)

    def test_exact_device_code_filter_does_not_normalize_source_names(self):
        api_payload = {
            "device-uuid": {
                "BMU-01_LC-01_BSC-01": {"SOC": 50},
                "BMU-01_LC-01_A-01_BSC-01": {"SOC": 51},
                "BMU-01_LC-01_A-01_BSC-01_RACK-01": {"SOC": 52},
                "BMU-01_LC-01_BSC-01_DH-01": {"SOC": 53},
            }
        }
        filtered, excluded = filter_exact_device_code_sources(
            api_payload,
            device_id="device-uuid",
            device_codes={
                "BMU-01_LC-01_A-01_BSC-01": "10002",
                "BMU-01_LC-01_A-01_BSC-01_RACK-01": "10003",
                "BMU-01_LC-01_BSC-01_DH-01": "10004",
            },
        )
        self.assertEqual(
            set(filtered["device-uuid"]),
            {"BMU-01_LC-01_A-01_BSC-01", "BMU-01_LC-01_A-01_BSC-01_RACK-01"},
        )
        self.assertEqual(excluded, 2)

    def test_splits_telemetry_packets_under_byte_limit(self):
        devices = [
            {
                "devType": "24",
                "devCode": str(index),
                "chnnlId": "63",
                "data": {"31003": "70.9", "31001": "1386.4"},
            }
            for index in range(10)
        ]
        payload = {
            "messageId": "app-key_20261104100000_01",
            "packgeCount": "1",
            "packgeId": "1",
            "publicData": {
                "productName": "BW Hams Hall",
                "productSN": "app-key",
                "productType": "1063",
                "sendTime": "20261104100000",
            },
            "businessData": [{"psId": "63", "recvTime": "20261104095959000", "devList": devices}],
        }
        packets = split_telemetry_payload(payload, 500)
        self.assertGreater(len(packets), 1)
        self.assertEqual([packet["packgeId"] for packet in packets], [str(i) for i in range(1, len(packets) + 1)])
        self.assertTrue(all(packet["packgeCount"] == str(len(packets)) for packet in packets))
        self.assertTrue(all(
            len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 500
            for packet in packets
        ))
        flattened = [device for packet in packets for group in packet["businessData"] for device in group["devList"]]
        self.assertEqual(flattened, devices)

    def test_splits_into_independent_messages_with_unique_ids(self):
        payload = {
            "messageId": "app-key_20261104100000_20",
            "packgeCount": "1",
            "packgeId": "1",
            "publicData": {"productName": "BW Hams Hall", "productSN": "app-key", "productType": "1063", "sendTime": "20261104100000"},
            "businessData": [{
                "psId": "63",
                "recvTime": "20261104095959000",
                "devList": [
                    {"devType": "24", "devCode": str(index), "chnnlId": "63", "data": {"31003": "70.9"}}
                    for index in range(8)
                ],
            }],
        }

        messages = split_telemetry_payload(payload, 450, independent_messages=True)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(message["packgeCount"] == "1" for message in messages))
        self.assertTrue(all(message["packgeId"] == "1" for message in messages))
        self.assertEqual(len({message["messageId"] for message in messages}), len(messages))
        self.assertTrue(all(
            len(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 450
            for message in messages
        ))


if __name__ == "__main__":
    unittest.main()