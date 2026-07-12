from pathlib import Path

from django.conf import settings


def parse_multiply(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"true", "1", "yes"}


def stream_csv_file(file_path: Path, multiply: bool):
    if not multiply:
        return _single_pass_generator(file_path)
    return _multiplied_generator(
        file_path,
        settings.STREAM_MULTIPLIER,
        settings.STREAM_SIZE_LIMIT_BYTES,
    )


def _single_pass_generator(file_path: Path):
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(8192)
            if not chunk:
                break
            yield chunk


def _multiplied_generator(file_path: Path, multiplier: int, size_limit_bytes: int):
    window: list[bytes] = []
    window_size = 0
    bytes_sent = 0
    passes = 0

    with file_path.open("rb") as handle:
        while True:
            line = handle.readline()
            if not line:
                break
            window.append(line)
            window_size += len(line)

    if not window:
        return

    while passes < multiplier and bytes_sent < size_limit_bytes:
        for line in window:
            if bytes_sent + len(line) > size_limit_bytes:
                remaining = size_limit_bytes - bytes_sent
                if remaining > 0:
                    yield line[:remaining]
                    bytes_sent += remaining
                return
            yield line
            bytes_sent += len(line)
        passes += 1
