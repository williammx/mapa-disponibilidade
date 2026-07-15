import hashlib
import os
import shutil
from pathlib import Path
from typing import BinaryIO

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
STORAGE_ROOT = Path(os.getenv("PRIVATE_STORAGE_DIR", str(DATA_DIR / "storage")))


def safe_filename(value: str | None, fallback: str = "arquivo") -> str:
    name = os.path.basename(value or fallback).strip().replace("\\", "-").replace("/", "-")
    return name[:180] or fallback


def storage_path(storage_key: str) -> Path:
    path = (STORAGE_ROOT / storage_key).resolve()
    root = STORAGE_ROOT.resolve()
    if root not in path.parents and path != root:
        raise ValueError("storage key fora da raiz privada")
    return path


def write_stream(storage_key: str, stream: BinaryIO) -> tuple[int, str]:
    path = storage_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as target:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            target.write(chunk)
    return size, digest.hexdigest()


def copy_file(source: str | Path, storage_key: str) -> tuple[int, str]:
    source_path = Path(source)
    path = storage_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source_path.open("rb") as src, path.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            dst.write(chunk)
    return size, digest.hexdigest()


def copy_to_path(source_key: str, destination: str | Path) -> None:
    src = storage_path(source_key)
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def ensure_project_key(project_id: str, *parts: str) -> str:
    clean = [safe_filename(part, "file") for part in parts]
    return "/".join(["projects", project_id, *clean])
