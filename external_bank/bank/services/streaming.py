import csv
import json
from pathlib import Path

from django.conf import settings


def parse_multiply(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"true", "1", "yes"}


def stream_json_file(file_path: Path, multiply: bool):
    if not multiply:
        return _single_pass_json_generator(file_path)
    return _multiplied_json_generator(
        file_path,
        settings.STREAM_MULTIPLIER,
        settings.STREAM_SIZE_LIMIT_BYTES,
    )


def _iter_csv_rows(file_path: Path):
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        try:
            headers = [header.strip() for header in next(reader)]
        except StopIteration:
            return

        for values in reader:
            if not values or all(not value.strip() for value in values):
                continue
            yield {
                header: values[index] if index < len(values) else ""
                for index, header in enumerate(headers)
            }


def _encode_row(row: dict[str, str]) -> bytes:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _single_pass_json_generator(file_path: Path):
    yield b"[\n"
    first = True
    for row in _iter_csv_rows(file_path):
        if not first:
            yield b",\n"
        yield _encode_row(row)
        first = False
    yield b"\n]"


def _multiplied_json_generator(file_path: Path, multiplier: int, size_limit_bytes: int):
    rows = list(_iter_csv_rows(file_path))
    if not rows:
        yield b"[]"
        return

    yield b"[\n"
    bytes_sent = 2
    first = True
    passes = 0

    while passes < multiplier and bytes_sent < size_limit_bytes:
        for row in rows:
            chunk = _encode_row(row)
            prefix = b"" if first else b",\n"
            candidate = prefix + chunk
            if bytes_sent + len(candidate) > size_limit_bytes:
                remaining = size_limit_bytes - bytes_sent
                if remaining > 0:
                    yield candidate[:remaining]
                yield b"\n]"
                return
            yield candidate
            bytes_sent += len(candidate)
            first = False
        passes += 1

    yield b"\n]"
