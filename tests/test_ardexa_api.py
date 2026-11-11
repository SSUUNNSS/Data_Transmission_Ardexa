import os
import json
import requests
from urllib.parse import quote

# This file is a manually run API smoke test, not a pytest test module.
__test__ = False

# ============================================================
# 1. Configuration
# ============================================================

# Ardexa has different cloud regions.
# Confirm which region your Workgroup belongs to.
BASE_URL = os.getenv(
    "ARDEXA_BASE_URL",
    "https://app.ardexa.com/api/v1"
).rstrip("/")

TOKEN = os.getenv("ARDEXA_TOKEN", "")
WORKGROUP = os.getenv("ARDEXA_WORKGROUP", "")

# Optional: specify a device and table for testing.
# If empty, the script selects the first available device/table.
DEVICE_ID = os.getenv("ARDEXA_DEVICE_ID", "")
TABLE_NAME = os.getenv("ARDEXA_TABLE", "")

TIMEOUT = 60

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
})


# ============================================================
# 2. HTTP Request Helper
# ============================================================

def api_get(endpoint, params=None):
    """
    Send GET request to Ardexa REST API.
    """

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"

    try:
        response = session.get(
            url,
            params=params,
            timeout=TIMEOUT
        )

        print(f"\nGET {response.url}")
        print(f"Status Code: {response.status_code}")

        response.raise_for_status()

        if response.status_code == 204:
            return None

        return response.json()

    except requests.exceptions.HTTPError as error:
        print(f"HTTP Error: {error}")
        print("Response:", response.text[:1000])
        return None

    except requests.exceptions.RequestException as error:
        print(f"Request Error: {error}")
        return None

    except ValueError:
        print("Response is not valid JSON.")
        return None


def path(value):
    """URL-encode a path component."""
    return quote(str(value), safe="")


ORG = path(WORKGROUP)


def print_json(data):
    print(json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
        default=str
    ))


# ============================================================
# 3. Test: List Devices
# ============================================================

def test_list_devices():

    print("\n========== TEST 1: LIST DEVICES ==========")

    data = api_get(
        f"/devices/{ORG}",
        params={"nameonly": "true"}
    )

    if not isinstance(data, list):
        return []

    print(f"\nTotal devices returned: {len(data)}")

    for device in data[:20]:
        print(
            f"Device ID: {device.get('id')}, "
            f"Name: {device.get('name')}"
        )

    return data


# ============================================================
# 4. Test: Device Metadata
# ============================================================

def test_device_metadata(device_id):

    print("\n========== TEST 2: DEVICE METADATA ==========")

    data = api_get(
        f"/devices/{ORG}/{path(device_id)}"
    )

    if not isinstance(data, dict):
        return None

    print("\nDevice information:")
    print("Device:", data.get("name"))
    print("ID:", data.get("id", data.get("_id")))
    print("Online:", data.get("online"))

    meta = data.get("meta") or {}

    print("\nMetadata sections:")
    print(list(meta.keys()))

    print("\nDetected Table / Source combinations:")

    for method in [
        "run",
        "tail",
        "watch",
        "unix_socket",
        "dynamic"
    ]:
        scenarios = meta.get(method, [])

        if not isinstance(scenarios, list):
            continue

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue

            table = scenario.get("table")
            source = scenario.get("source")

            if table or source:
                print(
                    f"Method={method}, "
                    f"Table={table}, "
                    f"Source={source}"
                )

    return data


# ============================================================
# 5. Test: List Tables
# ============================================================

def test_list_tables():

    print("\n========== TEST 3: LIST TABLES ==========")

    data = api_get(f"/tables/{ORG}")

    if not isinstance(data, list):
        return []

    print(f"\nTotal tables: {len(data)}")

    for table in data:
        print("Table:", table)

    return data


# ============================================================
# 6. Test: Table Schema
# ============================================================

def test_table_schema(table_name):

    print("\n========== TEST 4: TABLE SCHEMA ==========")

    data = api_get(
        f"/tables/{ORG}/{path(table_name)}"
    )

    if not isinstance(data, dict):
        return None

    print("\nTable:", table_name)
    print("Total Records:", data.get("count"))
    print("Type:", data.get("type"))

    fields = data.get("fields", {})

    print("\nAvailable Fields:")

    for field_name, details in fields.items():
        print(f"\nField: {field_name}")

        if isinstance(details, dict):
            print("  Type:", details.get("type"))
            print("  Unit:", details.get("units"))

    return data


# ============================================================
# 7. Test: Latest Values
# ============================================================

def test_latest_values(device_id, table_name):

    print("\n========== TEST 5: LATEST VALUES ==========")

    data = api_get(
        f"/devices/{ORG}/{path(device_id)}/latestValues",
        params={
            "table": table_name,
            "groupBy": "source"
        }
    )

    if data is not None:
        print("\nLatest values:")
        print_json(data)

    return data


# ============================================================
# 8. Test: Search Latest 5 Records
# ============================================================

def test_search_records(table_name):

    print("\n========== TEST 6: SEARCH RECORDS ==========")

    data = api_get(
        f"/tables/{ORG}/{path(table_name)}/search",
        params={
            "rows": 5,
            "sort": "-event_time"
        }
    )

    if not isinstance(data, dict):
        return None

    records = data.get("records", [])

    print("\nTotal matching Records:", data.get("totalRecords"))
    print("Returned Records:", len(records))

    for index, record in enumerate(records, start=1):

        print(f"\nRecord {index}:")
        print_json(record)

        if isinstance(record, dict):
            print("Field count:", len(record))

    return data


# ============================================================
# 9. Main
# ============================================================

def main():

    if not TOKEN:
        raise SystemExit("Please set the ARDEXA_TOKEN environment variable.")

    if not WORKGROUP:
        raise SystemExit(
            "ARDEXA_WORKGROUP is not set. Find your Ardexa workgroup, then "
            "set ARDEXA_WORKGROUP before running this API smoke test."
        )

    print("========================================")
    print("       ARDEXA API CONNECTION TEST")
    print("========================================")

    print("Base URL:", BASE_URL)
    print("Workgroup:", WORKGROUP)

    # 1. List devices
    devices = test_list_devices()

    # 2. Select device
    device_id = DEVICE_ID

    if not device_id and devices:
        device_id = devices[0].get("id")

    # 3. Device metadata
    if device_id:
        test_device_metadata(device_id)
    else:
        print("\nNo device available for testing.")

    # 4. List tables
    tables = test_list_tables()

    # 5. Select table
    table_name = TABLE_NAME

    if not table_name and tables:
        table_name = tables[0]

    if table_name:

        # 6. Table structure
        test_table_schema(table_name)

        # 7. Latest values
        if device_id:
            test_latest_values(device_id, table_name)

        # 8. Search records
        test_search_records(table_name)

    else:
        print("\nNo table available for testing.")

    print("\n========================================")
    print("          TEST COMPLETED")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    finally:
        session.close()