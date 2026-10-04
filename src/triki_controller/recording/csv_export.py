"""RAW CSV v1 export/import and session.json sidecar."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

from triki_controller.core.models import SCHEMA_VERSION, QualityFlags, RawSample

CSV_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "session_id",
    "connection_epoch",
    "sample_seq",
    "received_monotonic_ns",
    "source_notification_seqs_json",
    "protocol_revision",
    "raw_frame_hex",
    "accel_x_counts",
    "accel_y_counts",
    "accel_z_counts",
    "gyro_x_counts",
    "gyro_y_counts",
    "gyro_z_counts",
    "button",
    "device_tick",
    "battery_percent",
    "rssi_dbm",
    "quality_flags_json",
)


def _empty_null(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _button_to_csv(button: bool | None) -> str:
    if button is None:
        return ""
    return "1" if button else "0"


def _button_from_csv(raw: str) -> bool | None:
    if raw == "":
        return None
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise ValueError(f"invalid button field: {raw!r}")


def _optional_int(raw: str) -> int | None:
    if raw == "":
        return None
    return int(raw)


def _optional_float(raw: str) -> float | None:
    if raw == "":
        return None
    return float(raw)


@dataclass
class SessionSidecar:
    schema_version: int = SCHEMA_VERSION
    session_id: str = ""
    started_at_utc: str = ""
    clock_source: str = "host_monotonic_ns"
    application_version: str = "0.1.0"
    dependency_versions: dict[str, str] = field(default_factory=dict)
    device_metadata: dict[str, str] = field(
        default_factory=lambda: {
            "kind": "fake_synthetic",
            "note": "No physical CAP001; addresses omitted",
        }
    )
    protocol_evidence_reference: str = "synthetic-v0 (not HOM-27 measured)"
    profile_snapshot: dict[str, Any] | None = None
    calibration_snapshot: dict[str, Any] | None = None
    recording_complete: bool = False
    sample_count: int = 0
    parse_error_count: int = 0
    reconnect_count: int = 0
    notes: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> SessionSidecar:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("schema_version", -1)) != SCHEMA_VERSION:
            raise ValueError(f"unsupported session sidecar schema_version: {data.get('schema_version')}")
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


class RawCsvWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fp: TextIO | None = None
        self._writer: csv.DictWriter[str] | None = None
        self.rows_written = 0

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fp, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        self._writer.writeheader()

    def write_sample(self, sample: RawSample) -> None:
        if self._writer is None:
            raise RuntimeError("RawCsvWriter is not open")
        if sample.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {sample.schema_version}")
        row = {
            "schema_version": sample.schema_version,
            "session_id": sample.session_id,
            "connection_epoch": sample.connection_epoch,
            "sample_seq": sample.sample_seq,
            "received_monotonic_ns": sample.received_monotonic_ns,
            "source_notification_seqs_json": json.dumps(list(sample.source_notification_seqs)),
            "protocol_revision": sample.protocol_revision,
            "raw_frame_hex": sample.raw_frame.hex(),
            "accel_x_counts": sample.accel_counts[0],
            "accel_y_counts": sample.accel_counts[1],
            "accel_z_counts": sample.accel_counts[2],
            "gyro_x_counts": sample.gyro_counts[0],
            "gyro_y_counts": sample.gyro_counts[1],
            "gyro_z_counts": sample.gyro_counts[2],
            "button": _button_to_csv(sample.button),
            "device_tick": _empty_null(sample.device_tick),
            "battery_percent": _empty_null(sample.battery_percent),
            "rssi_dbm": _empty_null(sample.rssi_dbm),
            "quality_flags_json": json.dumps(sample.quality_flags.to_mapping(), sort_keys=True),
        }
        self._writer.writerow(row)
        self.rows_written += 1

    def flush(self) -> None:
        if self._fp is not None:
            self._fp.flush()

    def close(self) -> None:
        self.flush()
        if self._fp is not None:
            self._fp.close()
            self._fp = None
            self._writer = None

    def __enter__(self) -> RawCsvWriter:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class RawCsvReader:
    @staticmethod
    def read(path: Path) -> list[RawSample]:
        samples: list[RawSample] = []
        with path.open(newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            if reader.fieldnames is None:
                return samples
            missing = set(CSV_COLUMNS) - set(reader.fieldnames)
            if missing:
                raise ValueError(f"CSV missing columns: {sorted(missing)}")
            for row in reader:
                schema_version = int(row["schema_version"])
                if schema_version != SCHEMA_VERSION:
                    raise ValueError(f"unsupported schema_version: {schema_version}")
                flags_raw = json.loads(row["quality_flags_json"] or "{}")
                quality = QualityFlags(
                    incomplete_frame=bool(flags_raw.get("incomplete_frame", False)),
                    resync=bool(flags_raw.get("resync", False)),
                    discarded_bytes=int(flags_raw.get("discarded_bytes", 0)),
                    synthetic=bool(flags_raw.get("synthetic", False)),
                    not_measured=bool(flags_raw.get("not_measured", False)),
                    notes=tuple(flags_raw.get("notes") or ()),
                )
                samples.append(
                    RawSample(
                        schema_version=schema_version,
                        session_id=row["session_id"],
                        connection_epoch=int(row["connection_epoch"]),
                        sample_seq=int(row["sample_seq"]),
                        received_monotonic_ns=int(row["received_monotonic_ns"]),
                        source_notification_seqs=tuple(
                            json.loads(row["source_notification_seqs_json"] or "[]")
                        ),
                        protocol_revision=row["protocol_revision"],
                        raw_frame=bytes.fromhex(row["raw_frame_hex"]),
                        accel_counts=(
                            int(row["accel_x_counts"]),
                            int(row["accel_y_counts"]),
                            int(row["accel_z_counts"]),
                        ),
                        gyro_counts=(
                            int(row["gyro_x_counts"]),
                            int(row["gyro_y_counts"]),
                            int(row["gyro_z_counts"]),
                        ),
                        button=_button_from_csv(row["button"]),
                        device_tick=_optional_int(row["device_tick"]),
                        battery_percent=_optional_float(row["battery_percent"]),
                        rssi_dbm=_optional_int(row["rssi_dbm"]),
                        quality_flags=quality,
                    )
                )
        return samples


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_session_bundle(
    *,
    directory: Path,
    session_id: str,
    samples: Iterable[RawSample],
    parse_error_count: int = 0,
    reconnect_count: int = 0,
    application_version: str = "0.1.0",
    notes: list[str] | None = None,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "raw_samples.csv"
    sidecar_path = directory / "session.json"
    count = 0
    with RawCsvWriter(csv_path) as writer:
        for sample in samples:
            writer.write_sample(sample)
            count += 1
    sidecar = SessionSidecar(
        session_id=session_id,
        started_at_utc=utc_now_iso(),
        application_version=application_version,
        recording_complete=True,
        sample_count=count,
        parse_error_count=parse_error_count,
        reconnect_count=reconnect_count,
        notes=notes or ["slice1 offline synthetic recording"],
    )
    sidecar.write(sidecar_path)
    return csv_path, sidecar_path
