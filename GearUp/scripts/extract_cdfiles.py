#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path


ENTRY_STREAM_FILE = 4


def read_u32_le(data: bytes, off: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, off)[0], off + 4


def read_c_string(buf: bytes, off: int) -> str:
    end = buf.find(b"\x00", off)
    if end == -1:
        end = len(buf)
    return buf[off:end].decode("utf-8", errors="replace")


def decode_cat_name(data: bytes, abs_off: int, names: list[str]) -> str:
    out = []
    i = abs_off
    while i < len(data):
        cur = data[i]
        i += 1
        if cur == 0:
            break
        idx = 0
        if cur & 0x80:
            idx = (cur & 0x7F) << 8
            if i >= len(data):
                break
            cur = data[i]
            i += 1
        idx |= cur
        if idx == 0 or idx > len(names):
            break
        out.append(names[idx - 1])
    return "".join(out)


def normalize_rel_path(p: str) -> str:
    # Keep extraction inside output root and map separators consistently.
    p = p.replace("\\", "/").lstrip("/")
    safe_parts = []
    for part in p.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            continue
        safe_parts.append(part)
    return "/".join(safe_parts)


def find_archive_files(dat_path: Path) -> tuple[list[Path], bool]:
    base = dat_path.parent
    single = [base / "archive.ar", base / "ARCHIVE.AR"]
    for candidate in single:
        if candidate.exists():
            return [candidate], False

    parts = []
    for i in range(4):
        p = base / f"archive{i}.ar"
        if p.exists():
            parts.append(p)
    if parts:
        return parts, True

    raise FileNotFoundError("archive.ar/ARCHIVE.AR or archive0-3.ar were not found next to CDFILES.DAT")


def extract_v3(dat_path: Path, out_dir: Path) -> tuple[int, int]:
    data = dat_path.read_bytes()
    off = 0

    magic = data[off:off + 4]
    off += 4
    if magic != b"file":
        raise ValueError(f"Unsupported header magic: {magic!r}")

    version, off = read_u32_le(data, off)
    if version != 3:
        raise ValueError(f"This fallback extractor only supports V3, got V{version}")

    (
        _code_version,
        _unk0a,
        _unk0b,
        num_search_paths,
        search_paths_size,
        num_files,
        archive_path_length,
        alignment,
        num_entries,
        _unk3,
        _null0a,
        _null0b,
    ) = struct.unpack_from("<f11I", data, off)
    off += 48

    off += num_search_paths * 4
    off += search_paths_size
    off += archive_path_length

    file_offsets = struct.unpack_from(f"<{num_files}I", data, off)
    off += num_files * 4
    file_sizes = struct.unpack_from(f"<{num_files}I", data, off)
    off += num_files * 4

    tree_offsets = struct.unpack_from(f"<{num_entries}I", data, off)
    off += num_entries * 4

    file_ids_raw = struct.unpack_from(f"<{num_entries}I", data, off)
    off += num_entries * 4

    # Platform=AUTO in SRS PC, little-endian path in original code reads streamIds.
    stream_ids = struct.unpack_from(f"<{num_entries}I", data, off)
    off += num_entries * 4

    num_names, off = read_u32_le(data, off)
    names_buffer_size, off = read_u32_le(data, off)

    name_offsets = struct.unpack_from(f"<{num_names}I", data, off)
    off += num_names * 4

    names_begin = off
    names = [read_c_string(data, names_begin + n_off) for n_off in name_offsets]

    off += names_buffer_size
    rel_origin = off

    archive_paths, stream_parts = find_archive_files(dat_path)
    archives = [p.open("rb") for p in archive_paths]

    written = 0
    seen = 0
    errors = 0
    skipped = 0
    total_eligible = sum(1 for raw_id in file_ids_raw if ((raw_id >> 28) & 0xF) == ENTRY_STREAM_FILE)

    try:
        for idx_entry in range(num_entries):
            raw_id = file_ids_raw[idx_entry]
            file_id = raw_id & 0x0FFFFFFF
            entry_type = (raw_id >> 28) & 0xF

            # Match official extractor behavior: only StreamFile entries.
            if entry_type != ENTRY_STREAM_FILE:
                continue

            seen += 1

            if file_id >= num_files:
                errors += 1
                print(f"[{seen}/{total_eligible}] ERR invalid_file_id_{file_id}")
                continue

            stream_id = stream_ids[idx_entry] if stream_parts else 0
            if stream_id >= len(archives):
                errors += 1
                print(f"[{seen}/{total_eligible}] ERR invalid_stream_id_{stream_id}")
                continue

            stream = archives[stream_id]
            stream.seek(file_offsets[file_id] * alignment)
            payload = bytearray(stream.read(file_sizes[file_id]))

            if len(payload) == 0:
                skipped += 1
                print(f"[{seen}/{total_eligible}] SKIP {Path(decode_cat_name(data, rel_origin + tree_offsets[idx_entry], names)).name} (Empty)")
                continue

            name_abs_off = rel_origin + tree_offsets[idx_entry]
            file_name = decode_cat_name(data, name_abs_off, names)
            rel_name = normalize_rel_path(file_name)
            if not rel_name:
                errors += 1
                print(f"[{seen}/{total_eligible}] ERR invalid_name")
                continue

            if rel_name.upper().endswith(".ARC") and len(payload) > 7:
                payload[7] = 3

            out_path = out_dir / rel_name
            if out_path.exists():
                skipped += 1
                print(f"[{seen}/{total_eligible}] SKIP {Path(rel_name).name} - Already exists")
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                out_path.write_bytes(payload)
            except Exception:
                errors += 1
                print(f"[{seen}/{total_eligible}] ERR {Path(rel_name).name}")
                continue

            written += 1
            source_name = Path(stream.name).name
            print(f"[{seen}/{total_eligible}] OK {Path(rel_name).name}")
    finally:
        for f in archives:
            f.close()

    details = []
    if written > 0:
        details.append(f"[{written}]=OK")
    if errors > 0:
        details.append(f"[{errors}]=err")
    if skipped > 0:
        details.append(f"[{skipped}]=SKIP - Already exists")
    details.append(f"[{total_eligible}]=Total")
    print("Extraction completed! " + ", ".join(details))

    return written, seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract SRS CDFILES.DAT (V3) + archive.ar")
    parser.add_argument("dat", help="Path to CDFILES.DAT")
    parser.add_argument("out", help="Output directory")
    args = parser.parse_args()

    dat_path = Path(args.dat).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    written, seen = extract_v3(dat_path, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
