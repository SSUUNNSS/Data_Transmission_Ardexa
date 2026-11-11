from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SENDER = PROJECT_ROOT / "tests" / "send_ardexa_api_payload.py"
LOG_PATH = PROJECT_ROOT / "logs" / "hams_hall_scheduled_upload.log"
SITES = (
    {
        "name": "Hams Hall 01",
        "config": PROJECT_ROOT / "config" / "Hams_Hall_local.json",
        "device_code_map": PROJECT_ROOT / "config" / "Hams_Hall_DevCode.json",
        "device_id": "77eba054-9702-44c1-945c-9fe704e0af7e",
    },
    {
        "name": "Hams Hall 02",
        "config": PROJECT_ROOT / "config" / "Hams_Hall_02_local.json",
        "device_code_map": PROJECT_ROOT / "config" / "Hams_Hall_DevCode_02.json",
        "device_id": "138ae3eb-b170-4ba4-9cf0-6752c4e425a2",
    },
    {
        "name": "Hams Hall 03",
        "config": PROJECT_ROOT / "config" / "Hams_Hall_03_local.json",
        "device_code_map": PROJECT_ROOT / "config" / "Hams_Hall_DevCode_03.json",
        "device_id": "06e7ba01-1085-41d6-8dd5-d6b73617a420",
    },
    {
        "name": "Hams Hall 04",
        "config": PROJECT_ROOT / "config" / "Hams_Hall_04_local.json",
        "device_code_map": PROJECT_ROOT / "config" / "Hams_Hall_DevCode_04.json",
        "device_id": "126b0b2d-5bde-4848-a274-27d3aecda300",
    },
)


def configure_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hams_hall_scheduler")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def site_command(site: dict[str, str]) -> list[str]:
    return [
        sys.executable,
        str(SENDER),
        "--config",
        str(site["config"]),
        "--device-code-map",
        str(site["device_code_map"]),
        "--device-id",
        site["device_id"],
        "--all-exact-devices",
        "--max-payload-bytes",
        "60000",
        "--independent-messages",
        "--publish",
    ]


def run_site(site: dict[str, str], logger: logging.Logger) -> bool:
    logger.info("Starting %s upload", site["name"])
    print(f"[{site['name']}] Upload starting", flush=True)
    result = subprocess.run(
        site_command(site),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.stdout:
        logger.info("%s output:\n%s", site["name"], result.stdout.rstrip())
        summary_prefixes = (
            "HTTP API status:",
            "Exact-matched supported sources:",
            "Excluded API sources",
            "Telemetry packets:",
            "Packet mode:",
            "Telemetry packet ",
            "Telesignaling publish succeeded:",
            "No nonzero mapped telesignaling points",
        )
        for line in result.stdout.splitlines():
            if line.startswith(summary_prefixes):
                print(f"[{site['name']}] {line}", flush=True)
    if result.stderr:
        logger.warning("%s errors:\n%s", site["name"], result.stderr.rstrip())
    if result.returncode == 0:
        logger.info("%s upload completed", site["name"])
        print(f"[{site['name']}] Upload completed", flush=True)
        return True
    logger.error("%s upload failed with exit code %s", site["name"], result.returncode)
    print(f"[{site['name']}] Upload failed (exit code {result.returncode})", flush=True)
    return False


def main() -> int:
    logger = configure_logging()
    logger.info("Starting scheduled cycle at %s", datetime.now(timezone.utc).isoformat())
    results = [run_site(site, logger) for site in SITES]
    logger.info("Scheduled cycle finished; successful_sites=%s/%s", sum(results), len(results))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())