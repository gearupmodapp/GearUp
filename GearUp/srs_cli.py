#!/usr/bin/env python3
import json
import os
import struct
import shutil
import subprocess
import sys
if sys.platform == "win32":
    import ctypes
    # SEM_FAILCRITICALERRORS = 0x0001, SEM_NOGPFAULTERRORBOX = 0x0002, SEM_NOOPENFILEERRORBOX = 0x8000
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding='utf-8')
from pathlib import Path


def norm_token(token: str) -> str:
    t = token.strip().strip('"').strip("'")
    return t


def build_paths() -> dict[str, Path]:
    if getattr(sys, "frozen", False):
        toolkit = Path(sys.executable).resolve().parent
    else:
        toolkit = Path(__file__).resolve().parent
    root = toolkit.parent
    return {
        "toolkit": toolkit,
        "root": root,
        "data_dat": root / "Data" / "CDFILES.DAT",
        "data_archive": root / "Data" / "archive.ar",
        "extract_script": toolkit / "scripts" / "extract_cdfiles.py",
        "src_archive_legacy": toolkit / "archive.ar",
        "workspace": root / "SRS Workspace",
        "workspace_archive": root / "SRS Workspace" / "archive.ar",
        "workspace_models": root / "SRS Workspace" / "modeles",
        "workspace_textures": root / "SRS Workspace" / "textures",
        "workspace_sounds": root / "SRS Workspace" / "sounds",
        "workspace_texts": root / "SRS Workspace" / "texts",
        "technyx_exe": toolkit / "Technyx" / "technyx_toolset.exe",
        "technyx_cwd": toolkit / "Technyx",
    }


def ensure_workspace_dirs(paths: dict[str, Path]) -> None:
    paths["workspace"].mkdir(parents=True, exist_ok=True)
    paths["workspace_archive"].mkdir(parents=True, exist_ok=True)
    paths["workspace_models"].mkdir(parents=True, exist_ok=True)
    paths["workspace_textures"].mkdir(parents=True, exist_ok=True)
    paths["workspace_sounds"].mkdir(parents=True, exist_ok=True)
    paths["workspace_texts"].mkdir(parents=True, exist_ok=True)


def print_output_location(path: Path) -> None:
    print(f"You can find the file(s) in -> {path.resolve()}")


def _python_runner() -> str | None:
    current = Path(sys.executable).name.lower()
    if current.startswith("python"):
        return sys.executable
    py_launcher = shutil.which("py")
    if py_launcher:
        return py_launcher
    python_exe = shutil.which("python")
    if python_exe:
        return python_exe
    return None


def cmd_extract(paths: dict[str, Path]) -> int:
    ensure_workspace_dirs(paths)

    if not paths["data_dat"].exists():
        print(f"ERR: missing {paths['data_dat']}")
        return 1
    if not paths["extract_script"].exists():
        print(f"ERR: missing {paths['extract_script']}")
        return 1

    runner = _python_runner()
    if runner is None:
        print("ERR: no Python interpreter found (py/python) for extract step")
        return 1

    print("===== Extracting archive.ar =====", flush=True)
    cmd = [
        runner,
        str(paths["extract_script"]),
        str(paths["data_dat"]),
        str(paths["workspace_archive"]),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    proc = subprocess.run(cmd, text=True, input="y\n", creationflags=flags)
    if proc.returncode == 0:
        print_output_location(paths["workspace_archive"])
    return proc.returncode


def collect_arc_files(src_root: Path) -> list[Path]:
    if not src_root.exists():
        return []
    files = [p for p in src_root.rglob("*") if p.is_file() and p.suffix.lower() == ".arc"]
    files.sort(key=lambda p: str(p).lower())
    return files


def resolve_requested(arcs: list[Path], raw_list: str, mode: str = "glb") -> list[tuple[str, Path | None]]:
    tokens = [norm_token(t) for t in raw_list.split(",")]
    tokens = [t for t in tokens if t]

    by_name = {p.name.lower(): p for p in arcs}
    by_stem = {}
    for p in arcs:
        key = p.stem.lower()
        by_stem.setdefault(key, p)

    out: list[tuple[str, Path | None]] = []
    for token in tokens:
        t = token.replace("\\", "/").split("/")[-1]
        tl = t.lower()
        candidate = by_name.get(tl)
        if candidate is None and tl.endswith(".arc"):
            stem = Path(t).stem.lower()
            candidate = by_stem.get(stem)
        
        if mode == "dds":
            out_name = f"{Path(t).name}"
        else:
            out_name = f"{Path(t).stem}.glb"
            
        out.append((out_name, candidate))
    return out


def invalid_selected_tokens(raw_list: str, allowed_exts: tuple[str, ...]) -> list[str]:
    tokens = [norm_token(t) for t in raw_list.split(",")]
    tokens = [t for t in tokens if t]
    allowed = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_exts)
    invalid: list[str] = []
    for token in tokens:
        t = token.replace("\\", "/").split("/")[-1]
        tl = t.lower()
        if not any(tl.endswith(ext) for ext in allowed):
            invalid.append(t)
    return invalid


def _format_allowed_exts(allowed_exts: tuple[str, ...]) -> str:
    exts = [ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_exts]
    if len(exts) == 1:
        return exts[0]
    return " or ".join(exts)


def final_summary(ok: int, err: int, skipped: int, total: int) -> str:
    parts = []
    if ok > 0:
        parts.append(f"[{ok}]=OK")
    if err > 0:
        parts.append(f"[{err}]=err")
    if skipped > 0:
        parts.append(f"[{skipped}]=SKIP - Already exists")
    parts.append(f"[{total}]=Total")
    return "Conversion completed! " + ", ".join(parts)


def final_build_summary(ok: int, err: int, skipped: int, total: int) -> str:
    parts = []
    if ok > 0:
        parts.append(f"[{ok}]=OK")
    if err > 0:
        parts.append(f"[{err}]=err")
    if skipped > 0:
        parts.append(f"[{skipped}]=SKIP - Already exists")
    parts.append(f"[{total}]=Total")
    return "Build completed! " + ", ".join(parts)


def _resolve_build_arc_targets(archive_root: Path, glb_name: str) -> list[Path]:
    stem = Path(glb_name).stem.upper()
    exact_name = stem + ".ARC"
    all_arcs = [p for p in archive_root.rglob("*") if p.is_file() and p.suffix.lower() == ".arc"]
    exact = [p for p in all_arcs if p.name.upper() == exact_name]
    exact.sort(key=lambda p: p.name.upper())
    return exact


def _build_texture_single(dds_path: Path, workspace_archive: Path, dat_path: Path, archive_path: Path) -> tuple[bool, str]:
    """Pack a single .dds texture back into its containing .ARC and then into archive.ar."""
    if not dat_path.exists() or not archive_path.exists():
        return False, "Missing dat_path or archive_path"
    
    dds_data = dds_path.read_bytes()
    if len(dds_data) <= 128:
        return False, "DDS file is too small to contain a valid header"
        
    target_name = dds_path.stem.lower()
    
    payload_start = 128
    fourcc = dds_data[84:88]
    if dds_data[80] & 0x04 and fourcc == b'DX10':
        payload_start = 148
    
    raw_payload = dds_data[payload_start:]
    payload_len = len(raw_payload)
    
    matches = []
    
    # 1. Scan all ARCs in workspace to find this texture entry
    for arc_path in workspace_archive.rglob("*.arc"):
        try:
            arc_bytes = bytearray(arc_path.read_bytes())
            if len(arc_bytes) < 16:
                continue
            ne = struct.unpack_from('<I', arc_bytes, 4)[0] & 0xFFFFFF
            db = 0x80 + ne * 16
            
            en = b''
            for i in range(ne):
                o = 0x80+i*16
                if o+16 <= len(arc_bytes) and arc_bytes[o+12] == 0xFD:
                    ro = struct.unpack_from('<I', arc_bytes, o+4)[0]
                    sz = (arc_bytes[o+13]<<16) | (arc_bytes[o+14]<<8) | arc_bytes[o+15]
                    en = arc_bytes[db+ro : db+ro+sz]
                    break
                    
            for i in range(ne):
                o = 0x80+i*16
                if o+16 <= len(arc_bytes) and arc_bytes[o+12] == 0x1:
                    ro = struct.unpack_from('<I', arc_bytes, o+4)[0]
                    sz = (arc_bytes[o+13]<<16) | (arc_bytes[o+14]<<8) | arc_bytes[o+15]
                    no = struct.unpack_from('<i', arc_bytes, o+8)[0]
                    if no >= 0:
                        name_b = en[no : en.find(b'\0', no)]
                        name_str = name_b.decode('utf-8', 'ignore').lower()
                        import re
                        mo = re.search(r'\.(tga|dds|png)(\[\d+\])?$', name_str)
                        if mo:
                            base_name = name_str[:mo.start(1)-1]
                            frame_suffix = mo.group(2) or ""
                            compare_name = base_name + frame_suffix
                            compare_name2 = base_name + (mo.group(2) or "[00]")
                            if compare_name == target_name or compare_name2 == target_name:
                                matches.append((arc_path, db + ro, sz))
                                """
                                Continue searching without breaking. 
                                A single texture file can be referenced multiple times 
                                within the same archive (e.g., neon animations or frames).
                                """
        except Exception:
            continue
            
    if not matches:
        return False, f"Texture {target_name} not found inside any .ARC file in workspace."
        
    # Read width, height, mips from the new DDS header
    # DDS Header Offset 12: Height, 16: Width, 28: MipMapCount
    new_h, new_w = struct.unpack_from('<II', dds_data, 12)
    new_mips = struct.unpack_from('<I', dds_data, 28)[0]
    if new_mips == 0:
        new_mips = 1

    cdmap = _build_cdfiles_map(dat_path)
    patched_arcs = []
    
    with open(archive_path, "r+b") as fh:
        # 2. Patch all matched ARCs
        for arc_path, target_abs_off, target_entry_sz in matches:
            arc = bytearray(arc_path.read_bytes())
            if len(arc) < target_abs_off + 20:
                print(f"Skipping {arc_path.name}: Corrupted or empty ARC file.")
                continue
            
            # Check if the ARC has 24-byte or 20-byte header
            b16 = arc[target_abs_off + 16 : target_abs_off + 20]
            is_ascii = all(32 <= b <= 126 for b in b16)
            hdr_size = 24 if (not is_ascii and struct.unpack_from('<I', b16, 0)[0] == 41) else 20
            
            # Verify dimensions, mipmaps and format before injecting!
            original_w, original_h, original_mips = struct.unpack_from('<III', arc, target_abs_off)
            if new_w != original_w or new_h != original_h:
                # Do not modify headers or log warnings for resolution mismatches.
                # In game, textures with identical names across different archives (e.g. cars vs UI)
                # can have different resolutions.
                # If resolutions don't match, this DDS belongs to another archive branch.
                # We skip silently to avoid corrupting models.
                continue
            if is_ascii:
                if fourcc != b16:
                    continue
            
            # Strict size matching to prevent ANY chance of game buffer under/overflows
            max_allowed = target_entry_sz - hdr_size
            
            current_raw_payload = raw_payload
            current_payload_len = payload_len
            if current_payload_len > max_allowed:
                current_raw_payload = current_raw_payload[:max_allowed]
                current_payload_len = max_allowed

            arc[target_abs_off + hdr_size : target_abs_off + hdr_size + current_payload_len] = current_raw_payload
            
            arc_path.write_bytes(arc)
            
            # Push updated ARC to archive.ar
            match_key = None
            arc_name_upper = arc_path.name.upper()
            for k in cdmap:
                if k.split("/")[-1].upper() == arc_name_upper:
                    match_key = k
                    break
                    
            if match_key is None:
                continue
                
            byte_off, stored_size, _orig_name = cdmap[match_key]
            if len(arc) != stored_size:
                print(f"Skipping {arc_path.name}: size mismatch (ARC is {len(arc)}, stored in archive is {stored_size})")
                continue
                
            fh.seek(byte_off)
            fh.write(arc)
            if len(arc) >= 8:
                num_entries = struct.unpack_from("<I", arc, 4)[0] & 0x00FFFFFF
                fh.seek(byte_off + 4)
                fh.write(struct.pack("<I", num_entries))
                
            patched_arcs.append(arc_path.name)
            
    if not patched_arcs:
        return False, "Failed to inject into any matching ARC files (possibly size/dimension mismatch)."
        
    built_stem = dds_path.stem.lower()
    source_stem = Path(patched_arcs[0]).stem.lower()
    if built_stem != source_stem:
        return True, f"via {patched_arcs[0]}"
    else:
        return True, ""

def cmd_build(paths: dict[str, Path], selected: str | None) -> int:
    ensure_workspace_dirs(paths)

    if selected is None or selected == "__all_glb__" or selected == "__all_dds__" or selected == "__all_wav__" or selected == "__all_txt__" or selected == "__all_ogg__":
        glb_files = sorted(
            [p for p in paths["workspace_models"].glob("*.glb") if p.is_file()],
            key=lambda p: p.name.lower(),
        ) if selected in (None, "__all_glb__") else []
        
        dds_files = sorted(
            [p for p in paths["workspace_textures"].glob("*.dds") if p.is_file()],
            key=lambda p: p.name.lower(),
        ) if selected in (None, "__all_dds__") else []
        
        wav_files = sorted(
            [p for p in paths["workspace_sounds"].rglob("*.wav") if p.is_file()],
            key=lambda p: p.name.lower(),
        ) if selected in (None, "__all_wav__", "__all_ogg__") else []
        
        ogg_files = sorted(
            [p for p in paths["workspace_sounds"].rglob("*.ogg") if p.is_file()],
            key=lambda p: p.name.lower(),
        ) if selected in (None, "__all_ogg__", "__all_wav__") else []
        
        txt_files = sorted(
            [p for p in paths["workspace_texts"].rglob("*.txt") if p.is_file()],
            key=lambda p: p.name.lower(),
        ) if selected in (None, "__all_txt__") else []
        
        if not glb_files and not dds_files and not wav_files and not ogg_files and not txt_files:
            print(f"ERR: no suitable files found to build.")
            return 1
        tokens = [p.name for p in glb_files] + [p.name for p in dds_files] + [p.name for p in wav_files] + [p.name for p in ogg_files] + [p.name for p in txt_files]
        invalid: list[str] = []
        missing: list[str] = []
        resolved_paths: dict[str, Path] = {p.name: p for p in (glb_files + dds_files + wav_files + ogg_files + txt_files)}
    else:
        tokens = [norm_token(t) for t in selected.split(",")]
        tokens = [t for t in tokens if t]
        if not tokens:
            print("ERR: missing input file list.")
            return 1

        invalid: list[str] = []
        missing: list[str] = []
        resolved_paths: dict[str, Path] = {}

        for token in tokens:
            name = token.replace("\\", "/").split("/")[-1]
            if name.lower().endswith(".glb"):
                p = paths["workspace_models"] / name
                if p.exists(): resolved_paths[name] = p
                else: missing.append(name)
            elif name.lower().endswith(".dds"):
                p = paths["workspace_textures"] / name
                if p.exists(): resolved_paths[name] = p
                else: missing.append(name)
            elif name.lower().endswith(".wav"):
                found = list(paths["workspace_sounds"].rglob(name))
                if found: resolved_paths[name] = found[0]
                else: missing.append(name)
            elif name.lower().endswith(".ogg"):
                found = list(paths["workspace_sounds"].rglob(name))
                if found: resolved_paths[name] = found[0]
                else: missing.append(name)
            elif name.lower().endswith(".txt"):
                found = list(paths["workspace_texts"].rglob(name))
                if found: resolved_paths[name] = found[0]
                else: missing.append(name)
            else:
                invalid.append(name)

        if invalid:
            print("ERR: build accepts only .glb, .dds, .wav, .ogg, and .txt files.")
            print("Invalid:")
            for name in invalid:
                print(f"  - {name}")
            return 1

        if missing:
            print("ERR: missing input file(s) in workspace")
            print("Missing:")
            for name in missing:
                print(f"  - {name}")
            return 1

    if not paths["data_dat"].exists():
        print(f"ERR: missing {paths['data_dat']}")
        return 1

    if not paths["data_archive"].exists():
        print(f"ERR: missing {paths['data_archive']}")
        return 1

    exts = {token.split(".")[-1].lower() for token in tokens if "." in token}
    if exts == {"glb"}:
        process_label = "Models"
    elif exts == {"dds"}:
        process_label = "Textures"
    elif exts and exts <= {"wav", "ogg"}:
        process_label = "Sounds"
    elif exts == {"txt"}:
        process_label = "Texts"
    elif exts and exts <= {"wav", "ogg", "txt"}:
        process_label = "Sounds + Texts"
    else:
        process_label = "Files"

    print(f"===== Building {process_label} =====", flush=True)

    total = len(tokens)
    ok = 0
    err = 0
    skipped = 0

    for idx, token in enumerate(tokens, start=1):
        name = token.replace("\\", "/").split("/")[-1]
        
        if name.lower().endswith(".wav"):
            wav_path = resolved_paths.get(name) or list(paths["workspace_sounds"].rglob(name))[0]
            parent_folder = wav_path.parent.name
            
            cdmap = _build_cdfiles_map(paths["data_dat"])
            hdr_key = None
            for k in cdmap:
                if k.endswith(f"{parent_folder.lower()}.hdr"):
                    hdr_key = k
                    break
            
            if not hdr_key:
                err += 1
                print(f"[{idx}/{total}] ERR {name} - HDR mapped folder not found")
                continue
                
            byte_off, stored_size, orig_hdr_name = cdmap[hdr_key]
            orig_hdr = _get_blob_from_ar(paths["data_archive"], byte_off, stored_size)
            
            # SAFEGUARD: Heal corrupted headers in the archive from previous buggy writes
            orig_hdr_mutable = bytearray(orig_hdr)
            if orig_hdr_mutable.startswith(b"snda"):
                _, _, num_items = struct.unpack_from("<4sfI", orig_hdr_mutable, 0)
                for i in range(num_items):
                    item_pos = 32 + i * 64
                    sr = struct.unpack_from("<I", orig_hdr_mutable, item_pos + 20)[0]
                    if sr < 8000 or sr > 48000:
                        struct.pack_into("<I", orig_hdr_mutable, item_pos + 20, 44100) # Force 44100
                    struct.pack_into("<I", orig_hdr_mutable, item_pos + 28, 0) # Clear padding
            orig_hdr = bytes(orig_hdr_mutable)
            
            new_hdr, new_raw = build_hdr_raw_from_wavs(wav_path.parent, orig_hdr)
            new_off = patch_blob_to_ar(paths["data_archive"], byte_off, stored_size, new_hdr)
            _update_cdfiles_dat_entry(paths["data_dat"], hdr_key, len(new_hdr), new_off)
            
            raw_key = hdr_key[:-4] + ".raw"
            if raw_key in cdmap:
                raw_byte_off, raw_stored_size, _orig_raw_name = cdmap[raw_key]
                new_raw_off = patch_blob_to_ar(paths["data_archive"], raw_byte_off, raw_stored_size, new_raw)
                _update_cdfiles_dat_entry(paths["data_dat"], raw_key, len(new_raw), new_raw_off)
            
            ok += 1
            orig_name = orig_hdr_name.split('/')[-1]
            if Path(name).stem.lower() != Path(orig_name).stem.lower():
                print(f"[{idx}/{total}] OK {name} via {orig_name}")
            else:
                print(f"[{idx}/{total}] OK {name}")
            continue

        if name.lower().endswith(".ogg"):
            ogg_path = resolved_paths.get(name) or list(paths["workspace_sounds"].rglob(name))[0]
            
            cdmap = _build_cdfiles_map(paths["data_dat"])
            ogg_key = None
            for k in cdmap:
                if k.split('/')[-1].lower() == name.lower():
                    ogg_key = k
                    break
                    
            if not ogg_key:
                err += 1
                print(f"[{idx}/{total}] ERR {name} - matching OGG not found in Dat")
                continue
                
            byte_off, stored_size, orig_ogg_name = cdmap[ogg_key]
            
            new_ogg_data = ogg_path.read_bytes()
            new_off = patch_blob_to_ar(paths["data_archive"], byte_off, stored_size, new_ogg_data)
            _update_cdfiles_dat_entry(paths["data_dat"], ogg_key, len(new_ogg_data), new_off)
            
            ok += 1
            orig_name = orig_ogg_name.split('/')[-1]
            if Path(name).stem.lower() != Path(orig_name).stem.lower():
                print(f"[{idx}/{total}] OK {name} via {orig_name}")
            else:
                print(f"[{idx}/{total}] OK {name}")
            continue

        if name.lower().endswith(".txt"):
            txt_path = resolved_paths.get(name) or list(paths["workspace_texts"].rglob(name))[0]
            lda_name = txt_path.stem.lower() + ".lda"
            
            cdmap = _build_cdfiles_map(paths["data_dat"])
            lda_key = None
            for k in cdmap:
                if k.endswith(lda_name):
                    lda_key = k
                    break
                    
            if not lda_key:
                err += 1
                print(f"[{idx}/{total}] ERR {name} - matching LDA not found")
                continue
                
            byte_off, stored_size, orig_lda_name = cdmap[lda_key]
            orig_lda = _get_blob_from_ar(paths["data_archive"], byte_off, stored_size)
            
            new_lda = build_lda_from_txt(txt_path, orig_lda)
            new_off = patch_blob_to_ar(paths["data_archive"], byte_off, stored_size, new_lda)
            _update_cdfiles_dat_entry(paths["data_dat"], lda_key, len(new_lda), new_off)
            
            ok += 1
            orig_name = orig_lda_name.split('/')[-1]
            if Path(name).stem.lower() != Path(orig_name).stem.lower():
                print(f"[{idx}/{total}] OK {name} via {orig_name}")
            else:
                print(f"[{idx}/{total}] OK {name}")
            continue

        if name.lower().endswith(".dds"):
            dds_path = paths["workspace_textures"] / name
            success, msg = _build_texture_single(dds_path, paths["workspace_archive"], paths["data_dat"], paths["data_archive"])
            if success:
                ok += 1
                if msg:
                    print(f"[{idx}/{total}] OK {name} {msg}")
                else:
                    print(f"[{idx}/{total}] OK {name}")
            else:
                err += 1
                if "Not found" in msg or "not an identical structure" in msg:
                    print(f"[{idx}/{total}] SKIP {name} - {msg}")
                    err -= 1
                    skipped += 1
                elif "Already exists" in msg:
                    print(f"[{idx}/{total}] SKIP {name} - Already exists")
                    err -= 1
                    skipped += 1
                else:
                    print(f"[{idx}/{total}] ERR {name} - {msg}")
            continue

        # .glb handling
        glb_path = paths["workspace_models"] / name
        arc_targets = _resolve_build_arc_targets(paths["workspace_archive"], name)
        
        if not arc_targets:
            arc_name = Path(name).stem.upper() + ".ARC"
            print(f"[{idx}/{total}] ERR {name} - missing source ARC in archive.ar: {arc_name}")
            err += 1
            continue

        patched_any = False
        patched_sources = []
        for arc_path in arc_targets:
            try:
                if _build_single(glb_path, arc_path, paths["data_dat"], paths["data_archive"]):
                    patched_any = True
                    patched_sources.append(arc_path.name)
            except Exception as e:
                print(f"[{idx}/{total}] ERR {name} - build exception: {str(e)}")
                break

        if not patched_any:
            print(f"[{idx}/{total}] ERR {name} - failed to target archive data")
            err += 1
            continue
            
        orig_name = patched_sources[0]
        if Path(name).stem.lower() != Path(orig_name).stem.lower():
            print(f"[{idx}/{total}] OK {name} via {orig_name}")
        else:
            print(f"[{idx}/{total}] OK {name}")
        ok += 1

    print(final_build_summary(ok, err, skipped, total))
    print_output_location(paths["data_archive"])
    return 0 if err == 0 else 1

# ---------------------------------------------------------------------------
# GLB parsing helpers
# ---------------------------------------------------------------------------

_ARC_NODE_TYPES = {
    0x1c,  # Attachment
    0x1d,  # Model
    0x1e,  # DeformedModel
    0x1f,  # SkinnedModel
    0x20,  # AnimatedModel
    0x21,  # Skeleton
    0x25,  # Camera
    0x27,  # RigNode
    0x28,  # InstancedModel
    0x31,  # AnimatedNode
    0x35,  # UnkNode
    0x36,  # LightNode
}


def _trs_to_matrix(t: list, r: list, s: list) -> list[float]:
    """GLTF TRS → column-major 4x4 matrix (16 floats)."""
    tx, ty, tz = t
    qx, qy, qz, qw = r
    sx, sy, sz = s
    m00 = (1.0 - 2.0 * (qy * qy + qz * qz)) * sx
    m10 = (2.0 * (qx * qy + qw * qz)) * sx
    m20 = (2.0 * (qx * qz - qw * qy)) * sx
    m01 = (2.0 * (qx * qy - qw * qz)) * sy
    m11 = (1.0 - 2.0 * (qx * qx + qz * qz)) * sy
    m21 = (2.0 * (qy * qz + qw * qx)) * sy
    m02 = (2.0 * (qx * qz + qw * qy)) * sz
    m12 = (2.0 * (qy * qz - qw * qx)) * sz
    m22 = (1.0 - 2.0 * (qx * qx + qy * qy)) * sz
    return [m00, m10, m20, 0.0,
            m01, m11, m21, 0.0,
            m02, m12, m22, 0.0,
            tx,  ty,  tz,  1.0]


def _parse_glb_nodes(glb_path: Path) -> list[dict]:
    """Return list of {name, matrix} from a GLB file."""
    data = glb_path.read_bytes()
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != 0x46546C67:
        return []
    j_len = struct.unpack_from("<I", data, 12)[0]
    jd = json.loads(data[20 : 20 + j_len])
    result: list[dict] = []
    for node in jd.get("nodes", []):
        name = node.get("name", "")
        if "matrix" in node:
            m = [float(v) for v in node["matrix"]]
        else:
            t = node.get("translation", [0.0, 0.0, 0.0])
            r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
            s = node.get("scale", [1.0, 1.0, 1.0])
            m = _trs_to_matrix(t, r, s)
        result.append({"name": name, "matrix": m})
    return result


def _parse_glb_prims_raw(glb_path: Path) -> list[dict]:
    """
    Return one entry per GLB primitive (across all meshes, in mesh/prim order):
            {
                positions: [(x,y,z),...], normals: [(x,y,z),...], uvs: [(u,v),...], count: int,
                vtx_start: int | None, vtx_count: int, range_contiguous: bool,
                positions_all: [(x,y,z),...], normals_all: [(x,y,z),...], uvs_all: [(u,v),...],
                raw_indices: [int,...], index_count: int, mesh_idx: int, prim_idx: int,
            }
        When a primitive has indices, vertices are narrowed to the used vertex range.
    """
    data = glb_path.read_bytes()
    if struct.unpack_from("<I", data, 0)[0] != 0x46546C67:
        return []
    j_len = struct.unpack_from("<I", data, 12)[0]
    jd = json.loads(data[20 : 20 + j_len])
    bin_chunk_start = (20 + j_len + 3) & ~3
    bin_data = data[bin_chunk_start + 8 :]

    accessors    = jd.get("accessors", [])
    buffer_views = jd.get("bufferViews", [])
    meshes       = jd.get("meshes", [])

    def _read_acc(acc_idx: int) -> list:
        acc = accessors[acc_idx]
        bv  = buffer_views[acc["bufferView"]]
        bv_off    = bv.get("byteOffset", 0)
        bv_stride = bv.get("byteStride", 0)
        acc_off   = acc.get("byteOffset", 0)
        count     = acc["count"]
        comp_type = acc["componentType"]
        type_str  = acc["type"]
        comp_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
        comp_fmts   = {5126: ("f", 4), 5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}
        nc = comp_counts.get(type_str, 1)
        fmt_char, comp_size = comp_fmts.get(comp_type, ("f", 4))
        element_size = nc * comp_size
        stride = bv_stride if bv_stride else element_size
        base   = bv_off + acc_off
        result = []
        for i in range(count):
            off = base + i * stride
            vals = struct.unpack_from(f"<{nc}{fmt_char}", bin_data, off)
            result.append(vals if nc > 1 else vals[0])
        return result

    entries: list[dict] = []
    for mesh_idx, mesh in enumerate(meshes):
        for prim_idx, prim in enumerate(mesh.get("primitives", [])):
            attrs = prim.get("attributes", {})
            pos_idx = attrs.get("POSITION")
            if pos_idx is None:
                continue
            positions_all = _read_acc(pos_idx)
            normals_all   = _read_acc(attrs["NORMAL"])      if "NORMAL"      in attrs else []
            uvs_all       = _read_acc(attrs["TEXCOORD_0"])  if "TEXCOORD_0"  in attrs else []
            raw_indices = [int(i) for i in _read_acc(prim["indices"])] if "indices" in prim else list(range(len(positions_all)))

            vtx_start: int | None = None
            range_contiguous = False

            if raw_indices:
                used_indices = sorted(set(raw_indices))
                if used_indices:
                    vtx_start = used_indices[0]
                    range_contiguous = used_indices == list(range(used_indices[0], used_indices[-1] + 1))
                    if range_contiguous:
                        begin = used_indices[0]
                        end = used_indices[-1] + 1
                        positions = positions_all[begin:end]
                        normals = normals_all[begin:end] if normals_all else []
                        uvs = uvs_all[begin:end] if uvs_all else []
                    else:
                        positions = [positions_all[i] for i in used_indices]
                        normals = [normals_all[i] for i in used_indices] if normals_all else []
                        uvs = [uvs_all[i] for i in used_indices] if uvs_all else []
                else:
                    positions = []
                    normals = []
                    uvs = []
            else:
                positions = positions_all
                normals = normals_all
                uvs = uvs_all

            entries.append({
                "positions": positions,
                "normals":   normals,
                "uvs":       uvs,
                "positions_all": positions_all,
                "normals_all":   normals_all,
                "uvs_all":       uvs_all,
                "raw_indices":   raw_indices,
                "index_count":   len(raw_indices),
                "mesh_idx":      mesh_idx,
                "prim_idx":      prim_idx,
                "count":     len(positions),
                "vtx_start": vtx_start,
                "vtx_count": len(positions),
                "range_contiguous": range_contiguous,
            })
    return entries


def _parse_glb_vertex_buffers(glb_path: Path) -> list[dict]:
    """
    Extract vertex data from a GLB file.
    Returns a list of dicts, one per unique (POSITION bufferView), each with:
      {
        'positions': list of (x,y,z) tuples   — float32
        'normals':   list of (x,y,z) tuples   — float32, may be empty
        'uvs':       list of (u,v)   tuples   — float32, may be empty
        'count':     int
      }
    Buffer views that share the same BV for POSITION are merged into one entry.
    """
    data = glb_path.read_bytes()
    if struct.unpack_from("<I", data, 0)[0] != 0x46546C67:
        return []
    j_len = struct.unpack_from("<I", data, 12)[0]
    jd = json.loads(data[20 : 20 + j_len])

    # Locate the binary chunk
    bin_chunk_start = 20 + j_len
    # align to 4
    bin_chunk_start = (bin_chunk_start + 3) & ~3
    # skip chunk header (length + type)
    bin_data_offset = bin_chunk_start + 8
    bin_data = data[bin_data_offset:]

    accessors   = jd.get("accessors", [])
    buffer_views = jd.get("bufferViews", [])
    meshes       = jd.get("meshes", [])

    def _read_acc(acc_idx: int, expected_type: str) -> list:
        acc = accessors[acc_idx]
        bv  = buffer_views[acc["bufferView"]]
        bv_off    = bv.get("byteOffset", 0)
        bv_stride = bv.get("byteStride", 0)
        acc_off   = acc.get("byteOffset", 0)
        count     = acc["count"]
        comp_type = acc["componentType"]  # 5126 = float32, 5121 = uint8, 5123 = uint16
        type_str  = acc["type"]           # SCALAR, VEC2, VEC3, VEC4

        comp_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
        comp_fmts   = {5126: ("f", 4), 5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}

        nc = comp_counts.get(type_str, 1)
        fmt_char, comp_size = comp_fmts.get(comp_type, ("f", 4))
        element_size = nc * comp_size
        stride = bv_stride if bv_stride else element_size

        base = bv_off + acc_off
        result = []
        for i in range(count):
            off = base + i * stride
            vals = struct.unpack_from(f"<{nc}{fmt_char}", bin_data, off)
            result.append(vals if nc > 1 else vals[0])
        return result

    # We want one entry per primitive (each primitive maps to one VB in ARC)
    entries = []
    seen_prim_keys: set = set()

    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            pos_idx = attrs.get("POSITION")
            if pos_idx is None:
                continue
            # key by bufferView of POSITION to deduplicate shared VBs
            pos_bv = accessors[pos_idx].get("bufferView")
            key = (pos_bv, pos_idx)
            if key in seen_prim_keys:
                continue
            seen_prim_keys.add(key)

            positions = _read_acc(pos_idx, "VEC3")
            normals   = _read_acc(attrs["NORMAL"], "VEC3")   if "NORMAL"     in attrs else []
            uvs       = _read_acc(attrs["TEXCOORD_0"], "VEC2") if "TEXCOORD_0" in attrs else []

            entries.append({
                "positions": positions,
                "normals":   normals,
                "uvs":       uvs,
                "count":     len(positions),
            })
    return entries


# ---------------------------------------------------------------------------
# ARC parsing helpers
# ---------------------------------------------------------------------------

_VB_FLAG_POSITION     = 1 << 0
_VB_FLAG_NORMAL       = 1 << 2
_VB_FLAG_COLOR        = 1 << 1
_VB_FLAG_UV0          = 1 << 3
_VB_FLAG_UV1          = 1 << 4
_VB_FLAG_UV2          = 1 << 5
_VB_FLAG_BONE_WEIGHT  = 1 << 6
_VB_FLAG_DEFORM_CURVE = 1 << 7


def _parse_arc_vertex_buffers(arc_data: bytes) -> list[dict]:
    """
    Return list of vertex buffers found in ARC (type 0x10).
    Each entry: {abs_data_off, num_vertices, stride, flags,
                 pos_offset, norm_offset, uv_offset}
    Only buffers that have POSITION are returned.
    """
    return list(_parse_arc_vbs_dict(arc_data).values())


def _parse_arc_vbs_dict(arc_data: bytes) -> dict[int, dict]:
    """
    Return {slot_index: vb_info} for every type-0x10 VB entry that has POSITION.
    slot_index = the entry's first 4-byte field (e.index in the ARC C++ code).
    """
    result: dict[int, dict] = {}
    if len(arc_data) < 8:
        return result
    ne_ver = struct.unpack_from("<I", arc_data, 4)[0]
    num_entries: int = ne_ver & 0x00FFFFFF
    data_base = 0x80 + num_entries * 16

    for i in range(num_entries):
        off = 0x80 + i * 16
        if off + 16 > len(arc_data):
            break
        t = arc_data[off + 12]
        if t != 0x10:
            continue
        slot = struct.unpack_from("<I", arc_data, off)[0]
        rel_off = struct.unpack_from("<I", arc_data, off + 4)[0]
        abs_off = data_base + rel_off
        if abs_off + 12 > len(arc_data):
            continue
        num_verts, stride, flags = struct.unpack_from("<III", arc_data, abs_off)
        if not (flags & _VB_FLAG_POSITION):
            continue

        cur = 0
        pos_off = norm_off = uv_off = -1
        if flags & _VB_FLAG_POSITION:
            pos_off = cur; cur += 12
        if flags & _VB_FLAG_NORMAL:
            norm_off = cur; cur += 12
        if flags & _VB_FLAG_COLOR:
            cur += 4
        if flags & _VB_FLAG_UV0:
            uv_off = cur; cur += 8

        result[slot] = {
            "abs_data_off": abs_off + 12,
            "num_vertices": num_verts,
            "stride": stride,
            "flags": flags,
            "pos_offset": pos_off,
            "norm_offset": norm_off,
            "uv_offset": uv_off,
        }

    return result


def _parse_arc_ibs_dict(arc_data: bytes) -> dict[int, list[int]]:
    """Return {slot_index: [indices...]} for every type-0x0F index buffer entry."""
    result: dict[int, list[int]] = {}
    if len(arc_data) < 8:
        return result
    ne_ver = struct.unpack_from("<I", arc_data, 4)[0]
    num_entries: int = ne_ver & 0x00FFFFFF
    data_base = 0x80 + num_entries * 16

    for i in range(num_entries):
        off = 0x80 + i * 16
        if off + 16 > len(arc_data):
            break
        t = arc_data[off + 12]
        if t != 0x0F:
            continue
        slot = struct.unpack_from("<I", arc_data, off)[0]
        rel_off = struct.unpack_from("<I", arc_data, off + 4)[0]
        abs_off = data_base + rel_off
        if abs_off + 4 > len(arc_data):
            continue
        num_indices = struct.unpack_from("<I", arc_data, abs_off)[0]
        data_off = abs_off + 4
        byte_len = num_indices * 2
        if data_off + byte_len > len(arc_data):
            continue
        indices = list(struct.unpack_from(f"<{num_indices}H", arc_data, data_off))
        for tri_off in range(0, len(indices) - 2, 3):
            indices[tri_off], indices[tri_off + 1] = indices[tri_off + 1], indices[tri_off]
        result[slot] = indices

    return result


def _parse_arc_mesh_primitives(arc_data: bytes) -> list[dict]:
    """
    Parse type-0x09 Mesh entries (skip 0x19 DeformedMesh).
    Returns ordered list of:
            {mesh_idx: int, prim_idx: int, abs_vb: int, abs_ib: int,
             idx_start: int, idx_count: int, vtx_start: int, vtx_count: int}
    in the same order arc_extract processes them (entry-table order).
    abs_vb = MeshHdr.vertexBaseIndex + PrimitiveHdr.vertexBufferIndex
    """
    if len(arc_data) < 8:
        return []
    ne_ver = struct.unpack_from("<I", arc_data, 4)[0]
    num_entries: int = ne_ver & 0x00FFFFFF
    data_base = 0x80 + num_entries * 16

    # read entry names
    entry_names = b""
    for i in range(num_entries):
        off = 0x80 + i * 16
        if arc_data[off + 12] == 0xFD:
            rel = struct.unpack_from("<I", arc_data, off + 4)[0]
            sz  = (arc_data[off+13]<<16)|(arc_data[off+14]<<8)|arc_data[off+15]
            abs_e = data_base + rel
            entry_names = arc_data[abs_e : abs_e + sz]
            break

    prims: list[dict] = []
    mesh_idx = 0
    for i in range(num_entries):
        off = 0x80 + i * 16
        if off + 16 > len(arc_data):
            break
        t = arc_data[off + 12]
        if t != 0x09:          # only regular Mesh (skip 0x19 DeformedMesh)
            continue
        rel_off = struct.unpack_from("<I", arc_data, off + 4)[0]
        abs_off = data_base + rel_off
        if abs_off + 52 > len(arc_data):
            continue

        # MeshHdr: numCameras(4) matBase(4) idxBase(4) vtxBase(4) unk0(4) deformIdx(4) unk1(4) unk2[5](20) numPrims(4)
        idxBase  = struct.unpack_from("<I", arc_data, abs_off + 8)[0]
        vtxBase  = struct.unpack_from("<I", arc_data, abs_off + 12)[0]
        numPrims = struct.unpack_from("<I", arc_data, abs_off + 48)[0]
        if numPrims == 0 or numPrims > 10000:
            continue

        poff = abs_off + 52
        for _pi in range(numPrims):
            if poff + 28 > len(arc_data):
                break
            # PrimitiveHdr: matIdx idxBufIdx vtxBufIdx vtxBegin numUsed off0 cnt0  (7×u32)
            _mat, ibIdx, vtxBufIdx = struct.unpack_from("<3I", arc_data, poff)
            poff += 28
            if poff + 4 > len(arc_data):
                break
            numMods = struct.unpack_from("<I", arc_data, poff)[0]; poff += 4
            for _mi in range(numMods):
                if poff + 4 > len(arc_data):
                    break
                mtype = struct.unpack_from("<I", arc_data, poff)[0]; poff += 4
                if mtype == 0:   # PrimitiveCluster
                    if poff + 16 > len(arc_data):
                        break
                    _idxStart, _idxCount, vtxStart, vtxCount = struct.unpack_from("<4I", arc_data, poff)
                    poff += 16
                    prims.append({
                        "mesh_idx":  mesh_idx,
                        "prim_idx":  _pi,
                        "abs_vb":    vtxBase + vtxBufIdx,
                        "abs_ib":    idxBase + ibIdx,
                        "idx_start": _idxStart,
                        "idx_count": _idxCount,
                        "vtx_start": vtxStart,
                        "vtx_count": vtxCount,
                    })
                elif mtype == 1:  # PrimitiveSkin
                    if poff + 4 > len(arc_data):
                        break
                    skinLen = struct.unpack_from("<I", arc_data, poff)[0]; poff += 4
                    poff += skinLen * 4
                else:
                    break  # unknown mod type — stop parsing this prim safely
        mesh_idx += 1
    return prims


def _partition_arc_prims_by_idx_count(glb_group: list[dict], arc_group: list[dict]) -> list[list[dict]] | None:
    """Partition consecutive ARC primitives so each GLB primitive consumes one index-count span."""
    partitions: list[list[dict]] = []
    arc_pos = 0

    for gp in glb_group:
        target = gp.get("index_count", 0)
        if target <= 0:
            return None
        total = 0
        start = arc_pos
        while arc_pos < len(arc_group) and total < target:
            total += arc_group[arc_pos]["idx_count"]
            arc_pos += 1
        if total != target:
            return None
        partitions.append(arc_group[start:arc_pos])

    return partitions if arc_pos == len(arc_group) else None


def _build_index_stream_patch_entries(arc_data: bytes, arc_prims: list[dict], glb_prims: list[dict]) -> list[dict]:
    """
    Build per-primitive patch data by aligning GLB and ARC triangle streams.
    Blender exports may duplicate vertices or merge consecutive primitives while
    preserving triangle order; this reconstructs ARC vertex order from indices.
    """
    arc_ibs_map = _parse_arc_ibs_dict(arc_data)
    if not arc_ibs_map:
        return []

    glb_by_mesh: dict[int, list[dict]] = {}
    for gp in glb_prims:
        if gp.get("positions_all"):
            glb_by_mesh.setdefault(gp["mesh_idx"], []).append(gp)

    arc_by_mesh: dict[int, list[dict]] = {}
    for ap in arc_prims:
        arc_by_mesh.setdefault(ap["mesh_idx"], []).append(ap)

    used_arc_meshes: set[int] = set()
    patch_entries: list[dict] = []

    for glb_group in glb_by_mesh.values():
        candidates: list[tuple[int, list[list[dict]]]] = []
        for arc_mesh_idx, arc_group in arc_by_mesh.items():
            if arc_mesh_idx in used_arc_meshes:
                continue
            partitions = _partition_arc_prims_by_idx_count(glb_group, arc_group)
            if partitions is not None:
                candidates.append((arc_mesh_idx, partitions))

        if len(candidates) != 1:
            return []

        arc_mesh_idx, partitions = candidates[0]
        used_arc_meshes.add(arc_mesh_idx)

        for gp, arc_span in zip(glb_group, partitions):
            raw_indices = gp.get("raw_indices") or []
            positions_all = gp.get("positions_all") or []
            normals_all = gp.get("normals_all") or []
            uvs_all = gp.get("uvs_all") or []
            if not raw_indices or not positions_all:
                return []

            seg_off = 0
            for ap in arc_span:
                seg_len = ap["idx_count"]
                glb_seg = raw_indices[seg_off : seg_off + seg_len]
                seg_off += seg_len

                arc_indices = arc_ibs_map.get(ap["abs_ib"])
                if arc_indices is None:
                    return []
                arc_seg = arc_indices[ap["idx_start"] : ap["idx_start"] + seg_len]
                if len(glb_seg) != seg_len or len(arc_seg) != seg_len:
                    return []

                local_to_src: dict[int, int] = {}
                for arc_idx, glb_idx in zip(arc_seg, glb_seg):
                    local_idx = int(arc_idx) - ap["vtx_start"]
                    src_idx = int(glb_idx)
                    if local_idx < 0 or local_idx >= ap["vtx_count"]:
                        continue
                    if src_idx < 0 or src_idx >= len(positions_all):
                        return []
                    local_to_src.setdefault(local_idx, src_idx)

                if len(local_to_src) != ap["vtx_count"]:
                    return []

                ordered_src = [local_to_src[k] for k in range(ap["vtx_count"])]
                normals = [normals_all[src_idx] for src_idx in ordered_src] if normals_all and all(src_idx < len(normals_all) for src_idx in ordered_src) else []
                uvs = [uvs_all[src_idx] for src_idx in ordered_src] if uvs_all and all(src_idx < len(uvs_all) for src_idx in ordered_src) else []
                patch_entries.append({
                    "arc_prim": ap,
                    "positions": [positions_all[src_idx] for src_idx in ordered_src],
                    "normals": normals,
                    "uvs": uvs,
                })

    return patch_entries


def _parse_arc_nodes(arc_data: bytes) -> list[dict]:
    """Return list of {name, tm0_abs} for every node-type entry in the ARC."""
    if len(arc_data) < 8:
        return []
    ne_ver = struct.unpack_from("<I", arc_data, 4)[0]
    num_entries: int = ne_ver & 0x00FFFFFF
    data_base = 0x80 + num_entries * 16

    # Find EntryNames blob first
    entry_names = b""
    for i in range(num_entries):
        off = 0x80 + i * 16
        if off + 16 > len(arc_data):
            break
        t = arc_data[off + 12]
        if t != 0xFD:
            continue
        rel_off = struct.unpack_from("<I", arc_data, off + 4)[0]
        sz = (arc_data[off + 13] << 16) | (arc_data[off + 14] << 8) | arc_data[off + 15]
        abs_off = data_base + rel_off
        entry_names = arc_data[abs_off : abs_off + sz]
        break

    nodes: list[dict] = []
    for i in range(num_entries):
        off = 0x80 + i * 16
        if off + 16 > len(arc_data):
            break
        t = arc_data[off + 12]
        if t not in _ARC_NODE_TYPES:
            continue
        rel_off = struct.unpack_from("<I", arc_data, off + 4)[0]
        name_off = struct.unpack_from("<i", arc_data, off + 8)[0]
        name = ""
        if name_off >= 0:
            end = entry_names.find(b"\x00", name_off)
            if end < 0:
                end = len(entry_names)
            name = entry_names[name_off:end].decode("utf-8", errors="replace")
        abs_off = data_base + rel_off
        # NodeBase layout: unk0[2] (8 bytes) then tm0 (64 bytes)
        tm0_abs = abs_off + 8
        nodes.append({"name": name, "tm0_abs": tm0_abs, "type": t})
    return nodes


# ---------------------------------------------------------------------------
# CDFILES.DAT helpers — compact version (v3 PC only)
# ---------------------------------------------------------------------------

def _cdfiles_read_c_string(buf: bytes, off: int) -> str:
    end = buf.find(b"\x00", off)
    return buf[off : (end if end >= 0 else len(buf))].decode("utf-8", errors="replace")


def _cdfiles_decode_cat_name(data: bytes, abs_off: int, names: list[str]) -> str:
    out: list[str] = []
    i = abs_off
    while i < len(data):
        cur = data[i]; i += 1
        if cur == 0:
            break
        idx = 0
        if cur & 0x80:
            idx = (cur & 0x7F) << 8
            if i >= len(data):
                break
            cur = data[i]; i += 1
        idx |= cur
        if idx == 0 or idx > len(names):
            break
        out.append(names[idx - 1])
    return "".join(out)


def _build_cdfiles_map(dat_path: Path) -> dict[str, tuple[int, int, str]]:
    """
    Parse CDFILES.DAT v3 (PC, little-endian).
    Returns {rel_path_lower: (byte_offset_in_archive, size_in_bytes, rel_path_original)}.
    """
    data = dat_path.read_bytes()
    if data[:4] != b"file":
        return {}
    version = struct.unpack_from("<I", data, 4)[0]
    if version != 3:
        return {}

    off = 8
    (
        _code_ver, _u0a, _u0b,
        num_search_paths, search_paths_size,
        num_files, archive_path_length,
        alignment, num_entries,
        _u3, _n0a, _n0b,
    ) = struct.unpack_from("<f11I", data, off)
    off += 48

    off += num_search_paths * 4
    off += search_paths_size
    off += archive_path_length

    file_offsets = struct.unpack_from(f"<{num_files}I", data, off); off += num_files * 4
    file_sizes   = struct.unpack_from(f"<{num_files}I", data, off); off += num_files * 4
    tree_offsets = struct.unpack_from(f"<{num_entries}I", data, off); off += num_entries * 4
    file_ids_raw = struct.unpack_from(f"<{num_entries}I", data, off); off += num_entries * 4
    _stream_ids  = struct.unpack_from(f"<{num_entries}I", data, off); off += num_entries * 4

    num_names = struct.unpack_from("<I", data, off)[0]; off += 4
    names_buffer_size = struct.unpack_from("<I", data, off)[0]; off += 4
    name_offsets = struct.unpack_from(f"<{num_names}I", data, off); off += num_names * 4
    names_begin = off
    names = [_cdfiles_read_c_string(data, names_begin + no) for no in name_offsets]
    off += names_buffer_size
    rel_origin = off

    result: dict[str, tuple[int, int, str]] = {}
    STREAM_FILE = 4
    for idx_entry in range(num_entries):
        raw_id = file_ids_raw[idx_entry]
        entry_type = (raw_id >> 28) & 0xF
        if entry_type != STREAM_FILE:
            continue
        file_id = raw_id & 0x0FFFFFFF
        if file_id >= num_files:
            continue
        abs_name_off = rel_origin + tree_offsets[idx_entry]
        rel_name = _cdfiles_decode_cat_name(data, abs_name_off, names)
        rel_name = rel_name.replace("\\", "/").lstrip("/")
        key = rel_name.lower()
        byte_offset = file_offsets[file_id] * alignment
        size = file_sizes[file_id]
        result[key] = (byte_offset, size, rel_name)
    return result


# ---------------------------------------------------------------------------
# Core build: patch ARC + archive.ar for one file
# ---------------------------------------------------------------------------

def _update_cdfiles_dat_entry(dat_path: Path, match_key: str, new_size: int, new_offset: int = -1) -> bool:
    """Updates the size (and optionally offset) of a specific entry in CDFILES.DAT."""
    data = bytearray(dat_path.read_bytes())
    if data[:4] != b"file":
        return False
    version = struct.unpack_from("<I", data, 4)[0]
    if version != 3:
        return False

    off = 8
    (
        _code_ver, _u0a, _u0b,
        num_search_paths, search_paths_size,
        num_files, archive_path_length,
        alignment, num_entries,
        _u3, _n0a, _n0b,
    ) = struct.unpack_from("<f11I", data, off)
    
    base_off = 56 + num_search_paths * 4 + search_paths_size + archive_path_length
    file_offsets_offset = base_off
    file_sizes_offset = base_off + num_files * 4
    
    cdmap = _build_cdfiles_map(dat_path)
    if match_key not in cdmap:
        return False
        
    # Rebuild the full map including file_id for write-offset calculation.
    off2 = 56 + num_search_paths * 4 + search_paths_size + archive_path_length
    off2 += num_files * 4 * 2
    tree_offsets = struct.unpack_from(f"<{num_entries}I", data, off2); off2 += num_entries * 4
    file_ids_raw = struct.unpack_from(f"<{num_entries}I", data, off2); off2 += num_entries * 4
    _stream_ids  = struct.unpack_from(f"<{num_entries}I", data, off2); off2 += num_entries * 4
    num_names = struct.unpack_from("<I", data, off2)[0]; off2 += 4
    names_buffer_size = struct.unpack_from("<I", data, off2)[0]; off2 += 4
    name_offsets = struct.unpack_from(f"<{num_names}I", data, off2); off2 += num_names * 4
    names_begin = off2
    names = [_cdfiles_read_c_string(data, names_begin + no) for no in name_offsets]
    off2 += names_buffer_size
    rel_origin = off2

    STREAM_FILE = 4
    found_file_id = -1
    for idx_entry in range(num_entries):
        raw_id = file_ids_raw[idx_entry]
        entry_type = (raw_id >> 28) & 0xF
        if entry_type != STREAM_FILE:
            continue
        file_id = raw_id & 0x0FFFFFFF
        if file_id >= num_files:
            continue
        abs_name_off = rel_origin + tree_offsets[idx_entry]
        rel_name = _cdfiles_decode_cat_name(data, abs_name_off, names).replace("\\", "/").lstrip("/").lower()
        if rel_name == match_key:
            found_file_id = file_id
            break

    if found_file_id == -1:
        return False

    if new_offset != -1:
        scaled_offset = new_offset // alignment
        struct.pack_into("<I", data, file_offsets_offset + found_file_id * 4, scaled_offset)
    struct.pack_into("<I", data, file_sizes_offset + found_file_id * 4, new_size)
    dat_path.write_bytes(data)
    return True


def _get_blob_from_ar(archive_path: Path, byte_offset: int, size: int) -> bytes:
    with open(archive_path, "rb") as fh:
        fh.seek(byte_offset)
        return fh.read(size)


def patch_blob_to_ar(archive_path: Path, byte_offset: int, stored_size: int, blob: bytes, alignment: int = 2048) -> int:
    """Overwrites if blob fits, otherwise appends to end of archive and returns new offset."""
    with open(archive_path, "r+b") as fh:
        if len(blob) <= stored_size:
            fh.seek(byte_offset)
            fh.write(blob)
            return -1 # means didn't change offset
        else:
            fh.seek(0, 2) # EOF
            current_eof = fh.tell()
            # Align padding
            rem = current_eof % alignment
            if rem != 0:
                fh.write(b"\x00" * (alignment - rem))
            new_off = fh.tell()
            fh.write(blob)
            return new_off


import wave

def build_lda_from_txt(txt_path: Path, orig_lda_data: bytes) -> bytes:
    raw = txt_path.read_bytes()
    if raw.startswith(b'\xff\xfe'):
        lines = raw.decode("utf-16le").splitlines()
    elif raw.startswith(b'\xfe\xff'):
        lines = raw.decode("utf-16be").splitlines()
    elif raw.startswith(b'\xef\xbb\xbf'):
        lines = raw.decode("utf-8-sig").splitlines()
    else:
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            lines = raw.decode("windows-1252", errors="ignore").splitlines()
            
    magic, _, orig_id0, orig_id1, _ = struct.unpack_from("<4s4I", orig_lda_data, 0)
    is_utf16 = (magic == b"lda1")
    
    encoded_strings = []
    offsets = []
    current_str_offset = 0
    
    for line in lines:
        offsets.append(current_str_offset)
        enc_line = line.encode("utf-16le", errors="replace") if is_utf16 else line.encode("utf-8", errors="replace")
        encoded_strings.append(enc_line + b"\x00")
        current_str_offset += len(encoded_strings[-1])
        
    num_items = len(lines)
    str_block = b"".join(encoded_strings)
    
    padding_uint = 0 
    header_size = 20 + (num_items * 4) + 4
    file_size = header_size + len(str_block)
    
    result = bytearray()
    result.extend(struct.pack("<4s4I", magic, file_size, orig_id0, orig_id1, num_items))
    for off in offsets:
        result.extend(struct.pack("<I", off))
    result.extend(struct.pack("<I", padding_uint))
    result.extend(str_block)
    
    return bytes(result)

def build_hdr_raw_from_wavs(wav_dir: Path, orig_hdr_data: bytes) -> tuple[bytes, bytes]:
    hdr_id, version, num_items = struct.unpack_from("<4sfI", orig_hdr_data, 0)
    items_offset = 32
    raw_blob = bytearray()
    new_hdr_blob = bytearray(orig_hdr_data)
    
    # Needs to match the order of the items by index
    # We look for all wav files and sort them. Usually named "0_xxx.wav", "1_yyy.wav" 
    wav_files = sorted(wav_dir.glob("*.wav"), key=lambda x: str(x.name).lower())
    
    for i, wav_path in enumerate(wav_files):
        if i >= num_items: break
        
        with wave.open(str(wav_path), 'rb') as w:
            if w.getnchannels() != 1:
                print(f"WRN: {wav_path.name} has {w.getnchannels()} channels. SRS requires MONO (1 channel). Expect issues or crash!")
            if w.getsampwidth() != 2:
                print(f"WRN: {wav_path.name} is not 16-bit. SRS requires 16-bit PCM. Expect issues or crash!")
            pcm_data = w.readframes(w.getnframes())
            
        item_pos = items_offset + i * 64
        cur_data_start = len(raw_blob)
        cur_data_size = len(pcm_data)
        
        struct.pack_into("<I", new_hdr_blob, item_pos + 24, cur_data_start)
        struct.pack_into("<I", new_hdr_blob, item_pos + 32, cur_data_size)
        
        raw_blob.extend(pcm_data)
            
    return (bytes(new_hdr_blob), bytes(raw_blob))

def _build_single(
    glb_path: Path,
    arc_workspace: Path,
    dat_path: Path,
    archive_path: Path,
) -> bool:
    glb_nodes = _parse_glb_nodes(glb_path)
    if not glb_nodes:
        return False

    arc_data = bytearray(arc_workspace.read_bytes())
    arc_nodes = _parse_arc_nodes(bytes(arc_data))
    if not arc_nodes:
        return False

    arc_by_name: dict[str, dict] = {}
    for n in arc_nodes:
        if n["name"]:
            arc_by_name[n["name"].lower()] = n

    changed = False
    for gn in glb_nodes:
        key = gn["name"].lower()
        an = arc_by_name.get(key)
        if an is None:
            continue
        tm0_abs = an["tm0_abs"]
        if tm0_abs + 64 > len(arc_data):
            continue
        new_tm0 = struct.pack("<16f", *gn["matrix"])
        if arc_data[tm0_abs : tm0_abs + 64] != new_tm0:
            arc_data[tm0_abs : tm0_abs + 64] = new_tm0
            changed = True

    arc_prims   = _parse_arc_mesh_primitives(bytes(arc_data))
    arc_vbs_map = _parse_arc_vbs_dict(bytes(arc_data))
    glb_prims   = _parse_glb_prims_raw(glb_path)

    patch_entries: list[dict] = []

    def _queue_patch(ap: dict, positions: list, normals: list, uvs: list) -> None:
        patch_entries.append({
            "arc_prim": ap,
            "positions": positions,
            "normals": normals,
            "uvs": uvs,
        })

    # Preferred path: Technyx exports shared POSITION accessors plus per-primitive
    # index ranges. Those ranges line up directly with ARC vtxStart/vtxCount.
    non_empty_glb_prims = [gp for gp in glb_prims if gp["positions"]]
    glb_by_range: dict[tuple[int, int], list[dict]] = {}
    can_match_by_range = len(non_empty_glb_prims) == len(arc_prims)

    if can_match_by_range:
        for gp in non_empty_glb_prims:
            vtx_start = gp.get("vtx_start")
            vtx_count = gp.get("vtx_count")
            if vtx_start is None or not gp.get("range_contiguous"):
                can_match_by_range = False
                break
            glb_by_range.setdefault((vtx_start, vtx_count), []).append(gp)

    if can_match_by_range:
        for ap in arc_prims:
            queue = glb_by_range.get((ap["vtx_start"], ap["vtx_count"]))
            if not queue:
                patch_entries.clear()
                can_match_by_range = False
                break
            gp = queue.pop(0)
            _queue_patch(ap, gp["positions"], gp["normals"], gp["uvs"])

        if can_match_by_range and any(queue for queue in glb_by_range.values()):
            patch_entries.clear()
            can_match_by_range = False

    if not patch_entries:
        patch_entries = _build_index_stream_patch_entries(bytes(arc_data), arc_prims, glb_prims)

    if not patch_entries:
        # Fallback for older/atypical exports: match by first vertex position.
        arc_prim_pos0: dict[tuple, list[int]] = {}
        for ai, ap in enumerate(arc_prims):
            slot = ap["abs_vb"]
            if slot not in arc_vbs_map:
                continue
            vb = arc_vbs_map[slot]
            if ap["vtx_start"] >= vb["num_vertices"] or vb["pos_offset"] < 0:
                continue
            base = vb["abs_data_off"] + ap["vtx_start"] * vb["stride"] + vb["pos_offset"]
            if base + 12 > len(arc_data):
                continue
            px, py, pz = struct.unpack_from("<3f", arc_data, base)
            key = (round(px, 5), round(py, 5), round(pz, 5))
            arc_prim_pos0.setdefault(key, []).append(ai)

        used_arc_idxs: set[int] = set()
        for gp in glb_prims:
            if not gp["positions"]:
                continue
            px, py, pz = gp["positions"][0]
            key = (round(px, 5), round(py, 5), round(pz, 5))
            candidates = arc_prim_pos0.get(key, [])
            arc_idx = None
            for ai in candidates:
                if ai not in used_arc_idxs:
                    arc_idx = ai
                    break
            if arc_idx is None:
                continue
            used_arc_idxs.add(arc_idx)
            ap = arc_prims[arc_idx]
            _queue_patch(ap, gp["positions"], gp["normals"], gp["uvs"])

    for patch in patch_entries:
        ap = patch["arc_prim"]
        slot = ap["abs_vb"]
        if slot not in arc_vbs_map:
            continue
        vb       = arc_vbs_map[slot]
        stride   = vb["stride"]
        data_off = vb["abs_data_off"]
        pos_off  = vb["pos_offset"]
        norm_off = vb["norm_offset"]
        uv_off   = vb["uv_offset"]
        positions = patch["positions"]
        normals = patch["normals"]
        uvs = patch["uvs"]
        n = min(ap["vtx_count"], len(positions))
        for k in range(n):
            arc_vb_idx = ap["vtx_start"] + k
            base = data_off + arc_vb_idx * stride

            if pos_off >= 0:
                px, py, pz = positions[k]
                packed = struct.pack("<3f", px, py, pz)
                if arc_data[base + pos_off : base + pos_off + 12] != packed:
                    arc_data[base + pos_off : base + pos_off + 12] = packed
                    changed = True

            if norm_off >= 0 and k < len(normals):
                nx, ny, nz = normals[k]
                packed = struct.pack("<3f", nx, ny, nz)
                if arc_data[base + norm_off : base + norm_off + 12] != packed:
                    arc_data[base + norm_off : base + norm_off + 12] = packed
                    changed = True

            if uv_off >= 0 and k < len(uvs):
                u, v = uvs[k]
                packed = struct.pack("<2f", u, v)
                if arc_data[base + uv_off : base + uv_off + 8] != packed:
                    arc_data[base + uv_off : base + uv_off + 8] = packed
                    changed = True

    if not changed:
        return True

    orig_header = arc_workspace.read_bytes()[:8]
    arc_data[:8] = orig_header
    arc_workspace.write_bytes(bytes(arc_data))

    if not dat_path.exists() or not archive_path.exists():
        return False

    cdmap = _build_cdfiles_map(dat_path)
    arc_stem = arc_workspace.name
    match_key: str | None = None
    for k in cdmap:
        if k.split("/")[-1].upper() == arc_stem.upper():
            match_key = k
            break
    if match_key is None:
        return False
    byte_off, stored_size, _orig_name = cdmap[match_key]
    if stored_size != len(arc_data):
        return False

    with open(archive_path, "r+b") as fh:
        fh.seek(byte_off)
        fh.write(arc_data)
        if len(arc_data) >= 8:
            num_entries = struct.unpack_from("<I", arc_data, 4)[0] & 0x00FFFFFF
            fh.seek(byte_off + 4)
            fh.write(struct.pack("<I", num_entries))

    return True


def run_arc_extract(technyx_exe: Path, technyx_cwd: Path, arc_file: Path, temp_out: Path) -> tuple[bool, Path | None]:
    config_src = technyx_cwd / "technyx_toolset.config"
    arc_copy = temp_out / arc_file.name
    try:
        if config_src.exists():
            config_text = config_src.read_text(encoding="utf-8")
            config_text = config_text.replace('create-zip="true"', 'create-zip="false"')
            (temp_out / config_src.name).write_text(config_text, encoding="utf-8")
        shutil.copy2(arc_file, arc_copy)
    except Exception:
        pass

    env = os.environ.copy()
    env["TEMP"] = str(temp_out)
    env["TMP"] = str(temp_out)

    cmd = [
        str(technyx_exe),
        "arc_extract",
        arc_copy.name,
    ]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
        proc = subprocess.run(cmd, cwd=str(temp_out), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", input="y\n" * 100, timeout=20, creationflags=flags)
    except subprocess.TimeoutExpired:
        with open("C:/Users/rober/Desktop/Street Racing Syndicate/gearup_err.log", "a", encoding="utf-8") as f:
            f.write(f"Error {arc_file.name}: TIMEOUT (took more than 20s)\n\n")
        return False, None
    except Exception as e:
        with open("C:/Users/rober/Desktop/Street Racing Syndicate/gearup_err.log", "a", encoding="utf-8") as f:
            f.write(f"Error {arc_file.name}: {str(e)}\n\n")
        return False, None

    if proc.returncode != 0:
        with open("C:/Users/rober/Desktop/Street Racing Syndicate/gearup_err.log", "a", encoding="utf-8") as f:
            f.write(f"Error {arc_file.name}: code {proc.returncode}\n{proc.stdout}\n{proc.stderr}\n\n")
        return False, None

    glbs = [p for p in temp_out.rglob("*.glb") if p.is_file()]
    if not glbs:
        return True, None

    glbs.sort(key=lambda p: str(p).lower())
    preferred = None
    for g in glbs:
        if g.stem.lower() == arc_file.stem.lower():
            preferred = g
            break
    if preferred is None:
        preferred = glbs[0]

    return True, preferred


def _fix_glb_lod_nodes(p):
    import json, struct
    try:
        data = bytearray(p.read_bytes())
        if data[0:4] != b'glTF': return

        jlen = struct.unpack_from('<I', data, 12)[0]
        try:
            jstr = data[20:20+jlen].decode('utf-8').rstrip(' 	')
            j = json.loads(jstr)
        except: return

        meshes = j.get('meshes', [])
        if len(meshes) <= 1: return
        
        nodes = j.get('nodes', [])
        if not nodes: return
        
        if len(nodes) == len(meshes):
            return

        old_node = nodes[0]
        matrix = old_node.get('matrix')
        new_nodes = []
        for i in range(len(meshes)):
            n = {'mesh': i, 'name': f'LOD{i+1}'}
            if matrix: n['matrix'] = matrix
            new_nodes.append(n)
            
        j['nodes'] = new_nodes
        j['scenes'][0]['nodes'] = list(range(len(new_nodes)))
        
        new_jstr = json.dumps(j, separators=(',', ':')).encode('utf-8')
        padding_len = (4 - (len(new_jstr) % 4)) % 4
        new_jstr += b' ' * padding_len
        
        new_data = bytearray()
        new_data.extend(struct.pack('<I', 0x46546C67))
        new_data.extend(struct.pack('<I', 2))
        new_data.extend(struct.pack('<I', 0)) 
        
        new_data.extend(struct.pack('<I', len(new_jstr)))
        new_data.extend(b'JSON')
        new_data.extend(new_jstr)
        
        bin_off = 20 + jlen
        if bin_off < len(data):
            new_data.extend(data[bin_off:])
            
        struct.pack_into('<I', new_data, 8, len(new_data))
        p.write_bytes(new_data)
    except Exception as e:
        pass


def _check_missing_textures(arc_path: Path, textures_dir: Path) -> int:
    try:
        arc_bytes = arc_path.read_bytes()
        if len(arc_bytes) < 16: return 2
        ne = struct.unpack_from('<I', arc_bytes, 4)[0] & 0xFFFFFF
        db = 0x80 + ne * 16

        en = b''
        for i in range(ne):
            o = 0x80 + i * 16
            if o + 16 <= len(arc_bytes) and arc_bytes[o + 12] == 0xFD:
                ro = struct.unpack_from('<I', arc_bytes, o + 4)[0]
                sz = (arc_bytes[o + 13] << 16) | (arc_bytes[o + 14] << 8) | arc_bytes[o + 15]
                en = arc_bytes[db + ro : db + ro + sz]
                break

        import re
        name_counts = {}
        for i in range(ne):
            o = 0x80 + i * 16
            if o + 16 <= len(arc_bytes) and arc_bytes[o + 12] == 0x1:
                sz = (arc_bytes[o + 13] << 16) | (arc_bytes[o + 14] << 8) | arc_bytes[o + 15]
                if sz <= 24:
                    continue
                no = struct.unpack_from('<i', arc_bytes, o + 8)[0]
                if no >= 0 and no < len(en):
                    name_b = en[no : en.find(b'\x00', no)]
                    name_str = name_b.decode('utf-8', 'ignore').strip()
                    ext_match = re.search(r'\.(tga|dds|png)(\[\d+\])?$', name_str, flags=re.IGNORECASE)
                    if ext_match:
                        base_name = name_str[:ext_match.start(1)-1]
                        name_counts[base_name] = name_counts.get(base_name, 0) + 1
        
        if not name_counts:
            return 2 # No textures in this archive
            
        expected = set()
        for base_name, total in name_counts.items():
            if total > 1:
                for idx in range(total):
                    expected.add(f"{base_name}[{idx:02d}]")
            else:
                expected.add(f"{base_name}")
                
        for tex_name in expected:
            found = False
            for ext in (".dds", ".png", ".tga", ".jpg"):
                if (textures_dir / f"{tex_name}{ext}").exists():
                    found = True
                    break
            if not found:
                return 0 # Missing textures found, need to process archive!
                
        return 1 # All expected textures already exist
    except Exception:
        return 2


def _extract_raw_textures_from_arc(arc_path: Path, out_dir: Path) -> int:
    try:
        arc_bytes = arc_path.read_bytes()
        if len(arc_bytes) < 16: return 0
        ne = struct.unpack_from('<I', arc_bytes, 4)[0] & 0xFFFFFF
        db = 0x80 + ne * 16

        en = b''
        for i in range(ne):
            o = 0x80 + i * 16
            if o + 16 <= len(arc_bytes) and arc_bytes[o + 12] == 0xFD:
                ro = struct.unpack_from('<I', arc_bytes, o + 4)[0]
                sz = (arc_bytes[o + 13] << 16) | (arc_bytes[o + 14] << 8) | arc_bytes[o + 15]
                en = arc_bytes[db + ro : db + ro + sz]
                break

        count = 0
        
        import re
        textures_to_extract = []
        name_counts = {}
        
        for i in range(ne):
            o = 0x80 + i * 16
            if o + 16 <= len(arc_bytes) and arc_bytes[o + 12] == 0x1:
                ro = struct.unpack_from('<I', arc_bytes, o + 4)[0]
                sz = (arc_bytes[o + 13] << 16) | (arc_bytes[o + 14] << 8) | arc_bytes[o + 15]
                if sz <= 24:
                    continue
                no = struct.unpack_from('<i', arc_bytes, o + 8)[0]
                if no >= 0 and no < len(en):
                    name_b = en[no : en.find(b'\x00', no)]
                    name_str = name_b.decode('utf-8', 'ignore').strip()
                    # Look for the final extension, possibly preceded by an index,
                    # and extract the clean base name
                    ext_match = re.search(r'\.(tga|dds|png)(\[\d+\])?$', name_str, flags=re.IGNORECASE)
                    if ext_match:
                        base_name = name_str[:ext_match.start(1)-1]
                        name_counts[base_name] = name_counts.get(base_name, 0) + 1
                        textures_to_extract.append((ro, sz, name_str, base_name, ext_match))

        seen_counts = {}
        for ro, sz, name_str, base_name, ext_match in textures_to_extract:
            file_data = arc_bytes[db + ro : db + ro + sz]
            if len(file_data) > 24:
                # Re-wrap Eutechnyx chunk into standard DDS
                w, h, mips = struct.unpack_from('<III', file_data, 0)
                magic = file_data[16:20]
                is_ascii = all(32 <= b <= 126 for b in magic)
                dds_hdr = bytearray(128)
                dds_hdr[:4] = b'DDS '
                hdr_size = 24 if (not is_ascii and struct.unpack_from('<I', file_data[16:20], 0)[0] == 41) else 20
                if is_ascii:
                    struct.pack_into('<IIIIIII', dds_hdr, 4, 124, 0x1007|0x1000|0x80000, h, w, 0, 0, mips if mips>0 else 1)
                    struct.pack_into('<II', dds_hdr, 76, 32, 4)
                    dds_hdr[84:88] = magic
                    struct.pack_into('<I', dds_hdr, 108, 0x1000)
                    payload = file_data[hdr_size:]
                else:
                    d3dfmt = struct.unpack_from('<I', file_data, 16)[0]
                    bpp = 32
                    payload = file_data[hdr_size:]
                    
                    # Process based on exact Direct3D format enum from byte 16
                    if d3dfmt == 41:  # D3DFMT_P8
                        bpp = 32
                        pitch = w * 4
                        struct.pack_into('<IIIIIII', dds_hdr, 4, 124, 0x100F, h, w, pitch, 0, mips if mips>0 else 1)
                        struct.pack_into('<II', dds_hdr, 76, 32, 0x41)
                        struct.pack_into('<IIIII', dds_hdr, 88, 32, 0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
                        struct.pack_into('<I', dds_hdr, 108, 0x1000)
                        
                        # Convert 8bpp to 32bpp A8R8G8B8 to ensure absolute format compatibility
                        palette = file_data[hdr_size : hdr_size + 1024]
                        pixels_8bpp = file_data[hdr_size + 1024:]
                        pixels_32bpp = bytearray(w * h * 4)
                        for idx in range(w * h):
                            if idx < len(pixels_8bpp):
                                c_idx = pixels_8bpp[idx]
                                c_start = c_idx * 4
                                r = palette[c_start]
                                g = palette[c_start + 1]
                                b = palette[c_start + 2]
                                a = palette[c_start + 3]
                                
                                # Eutechnyx palette format is usually RGBA, we need BGRA for DDS A8R8G8B8 mask.
                                # Also, many D3D palette games leave alpha channel 0 for opaque colors. Force opaque if alpha is 0.
                                if a == 0: a = 255
                                
                                pixels_32bpp[idx*4] = b
                                pixels_32bpp[idx*4+1] = g
                                pixels_32bpp[idx*4+2] = r
                                pixels_32bpp[idx*4+3] = a
                        payload = pixels_32bpp
                    else:
                        real_payload = len(payload)
                        raw_bpp = (real_payload * 8) / (w * h if w*h>0 else 1)
                        
                        if abs(raw_bpp - 12) <= 1:
                            bpp = 16
                            new_payload = bytearray(w * h * 2)
                            src = payload
                            dst = new_payload
                            for i in range(0, w * h, 2):
                                s_idx = (i * 3) // 2
                                if s_idx + 2 < len(src):
                                    b0, b1, b2 = src[s_idx], src[s_idx+1], src[s_idx+2]
                                    p1 = (b1 & 0xF0) << 4 | b0
                                    p2 = b2 << 4 | (b1 & 0x0F)
                                    p1 |= 0xF000
                                    p2 |= 0xF000
                                    dst[i*2] = p1 & 0xFF
                                    dst[i*2+1] = (p1 >> 8) & 0xFF
                                    if i+1 < w*h:
                                        dst[(i+1)*2] = p2 & 0xFF
                                        dst[(i+1)*2+1] = (p2 >> 8) & 0xFF
                            payload = dst
                            d3dfmt = 26  # Treat converted 12bpp as A4R4G4B4
                        elif d3dfmt == 26: bpp = 16  # A4R4G4B4
                        elif d3dfmt == 25: bpp = 16 # A1R5G5B5
                        elif d3dfmt == 24: bpp = 16 # X1R5G5B5
                        elif d3dfmt == 23: bpp = 16 # R5G6B5
                        elif d3dfmt == 22: bpp = 32 # X8R8G8B8
                        elif d3dfmt == 21: bpp = 32 # A8R8G8B8
                        elif d3dfmt == 20: bpp = 24 # R8G8B8
                        else:
                            if abs(raw_bpp - 8) < 4: bpp = 8
                            elif abs(raw_bpp - 16) < 4: bpp = 16
                            elif abs(raw_bpp - 24) < 4: bpp = 24
                            elif abs(raw_bpp - 32) < 4: bpp = 32
                            else: bpp = round(raw_bpp)

                        pitch = ((w * bpp + 31) // 32) * 4
                        struct.pack_into('<IIIIIII', dds_hdr, 4, 124, 0x100F, h, w, pitch, 0, mips if mips>0 else 1)
                        struct.pack_into('<II', dds_hdr, 76, 32, 0x41)
                        
                        if d3dfmt == 26: # A4R4G4B4
                            struct.pack_into('<IIIII', dds_hdr, 88, 16, 0x0f00, 0x00f0, 0x000f, 0xf000)
                        elif d3dfmt == 23: # R5G6B5
                            struct.pack_into('<IIIII', dds_hdr, 88, 16, 0xf800, 0x07e0, 0x001f, 0x0000)
                        elif bpp == 16: # A1R5G5B5 / X1R5G5B5 / default 16
                            struct.pack_into('<IIIII', dds_hdr, 88, 16, 0x7c00, 0x03e0, 0x001f, 0x8000 if d3dfmt == 25 else 0)
                        elif bpp == 32: 
                            struct.pack_into('<IIIII', dds_hdr, 88, 32, 0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)
                        elif bpp == 24: 
                            struct.pack_into('<IIIII', dds_hdr, 88, 24, 0x00ff0000, 0x0000ff00, 0x000000ff, 0x00000000)
                        elif bpp == 8:
                            struct.pack_into('<II', dds_hdr, 76, 32, 0x20)
                            struct.pack_into('<IIIII', dds_hdr, 88, 8, 0, 0, 0, 0)
                            
                        struct.pack_into('<I', dds_hdr, 108, 0x1000)
                
                file_data = bytes(dds_hdr) + payload

                # Determine the suffix from per-base frequency counters in the archive.
                seen_counts[base_name] = seen_counts.get(base_name, 0) + 1
                
                if name_counts[base_name] > 1:
                    frame_idx = seen_counts[base_name] - 1
                    name_str = f"{base_name}[{frame_idx:02d}].dds"
                else:
                    name_str = f"{base_name}.dds"
                    
            dst = out_dir / name_str
            try:
                # Overwrite directly. Keep the exact native name requested by the engine
                # to avoid breaking the link between the base and frames [01], [02]
                dst.write_bytes(file_data)
                count += 1
            except Exception:
                pass
                        
        return count
    except Exception as e:
        import traceback; traceback.print_exc(); return 0

def cmd_convert(paths: dict[str, Path], selected: str | None, mode: str = "glb") -> int:
    ensure_workspace_dirs(paths)

    src_root = paths["workspace_archive"]
    if not src_root.exists():
        src_root = paths["src_archive_legacy"]
        
    arcs = collect_arc_files(src_root)
    
    if mode == "dds":
        dst_root = paths["workspace_textures"]
        print("===== Converting Textures =====", flush=True)
    else:
        dst_root = paths["workspace_models"]
        print("===== Converting Models =====", flush=True)

    if selected:
        allowed = (".arc",)
        invalid = invalid_selected_tokens(selected, allowed)
        if invalid:
            print(f"ERR: selected files must use {_format_allowed_exts(allowed)} extension only.")
            print("Invalid:")
            for name in invalid:
                print(f"  - {name}")
            return 1
        queue = resolve_requested(arcs, selected, mode)
    else:
        if mode == "dds":
            # DDS mode has no 1-to-1 name mapping; run all ARCs and extract textures from each.
            queue = [(f"{p.name}", p) for p in arcs]
        else:
            queue = [(f"{p.stem}.glb", p) for p in arcs]

    total = len(queue)
    ok = 0
    err = 0
    skipped = 0

    if not paths["technyx_exe"].exists():
        for idx, (out_name, _) in enumerate(queue, start=1):
            print(f"[{idx}/{total}] ERR {out_name}")
            err += 1
        print(final_summary(ok, err, skipped, total))
        return 1

    seen_out_names: set[str] = set()

    import tempfile
    import concurrent.futures

    textures_dir = paths["workspace_textures"]
    textures_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a hidden/special '.temp' folder in dst_root for ARC processes
    temp_base = dst_root / ".temp"
    temp_base.mkdir(parents=True, exist_ok=True)

    def process_file(out_name: str, arc_file: Path, mode: str) -> tuple[str, str]:
        out_target = dst_root / out_name

        if arc_file is None or not arc_file.exists():
            return "ERR", f"ERR {out_name}"

        if arc_file.stat().st_size == 0:
            return "SKIP", f"SKIP {out_name}- Empty"

        with tempfile.TemporaryDirectory(prefix="srs_arc_temp_", dir=temp_base) as tmp_dir:
            tmp_path = Path(tmp_dir)
            success = False
            produced = None
            
            if mode == "glb":
                for attempt in range(2):
                    success, produced = run_arc_extract(paths["technyx_exe"], paths["technyx_cwd"], arc_file, tmp_path)
                    if success:
                        break
                        
                if not success:
                    return "ERR", f"ERR {out_name} - Extractor Failed"
                    
                if produced is None or not produced.exists():
                    return "SKIP", f"SKIP {out_name} - No model produced"
                    
                try:
                    shutil.move(str(produced), str(out_target))
                    _fix_glb_lod_nodes(out_target)
                    return "OK", f"OK {out_name} → Model"
                except Exception as e:
                    return "ERR", f"ERR {out_name} - {str(e)}"
                    
            elif mode == "dds":
                # Extract raw textures
                _extract_raw_textures_from_arc(arc_file, tmp_path)

                extracted_new_textures = False
                found_any_textures = False
                for tex_file in tmp_path.rglob("*"):
                    if tex_file.is_file() and tex_file.suffix.lower() in (".dds", ".png", ".tga", ".jpg"):
                        found_any_textures = True
                        dest_tex = textures_dir / tex_file.name
                        if not dest_tex.exists(): # avoid crash on overwrite
                            try:
                                shutil.move(str(tex_file), str(dest_tex))
                                extracted_new_textures = True
                            except Exception:
                                pass
                                
                if extracted_new_textures:
                    return "OK", f"OK {out_name} → Texture"
                elif found_any_textures:
                    return "SKIP", f"SKIP {out_name} - Already exists"
                else:
                    return "SKIP", f"SKIP {out_name} - No textures"

            return "ERR", f"ERR {out_name} - Unknown mode"

    jobs = []
    # Pre-filter
    for out_name, arc_file in queue:
        lower_name = out_name.lower()
        out_target = dst_root / out_name
        
        is_pre_skipped = False
        if lower_name in seen_out_names:
            is_pre_skipped = True
        elif mode == "glb" and out_target.exists():
            is_pre_skipped = True

        if is_pre_skipped:
            skipped += 1
            jobs.append((out_name, arc_file, True)) # is_pre_skipped
        else:
            seen_out_names.add(lower_name)
            jobs.append((out_name, arc_file, False))

    workers = min(32, (os.cpu_count() or 1) * 2)

    completed_so_far = 0

    if mode == "glb":
        # OPTIMIZATION: Batch processing to prevent Antivirus triggers from 10k process launches
        batch_dir = temp_base / "batch_glb"
        batch_dir.mkdir(parents=True, exist_ok=True)
        config_src = paths["technyx_cwd"] / "technyx_toolset.config"
        config_text = config_src.read_text(encoding="utf-8").replace('create-zip="true"', 'create-zip="false"') if config_src.exists() else ""

        batch_jobs = []
        for idx, (out_name, arc_file, is_pre_skipped) in enumerate(jobs, start=1):
            if is_pre_skipped:
                completed_so_far += 1
                print(f"[{completed_so_far}/{total}] SKIP {out_name} - Already exists", flush=True)
                continue
            batch_jobs.append((out_name, arc_file))

        if batch_jobs:
            print(f"Processing {len(batch_jobs)} models in bulk to speed things up...", flush=True)
            # Chunk size: 50 items per parallel thread
            chunk_size = 50
            chunks = [batch_jobs[i:i+chunk_size] for i in range(0, len(batch_jobs), chunk_size)]
            
            def process_chunk(c_idx, chunk):
                chunk_dir = batch_dir / f"chunk_{c_idx}"
                chunk_dir.mkdir(parents=True, exist_ok=True)
                if config_text:
                    (chunk_dir / config_src.name).write_text(config_text, encoding="utf-8")
                
                for out_name, arc_file in chunk:
                    link_name = Path(out_name).with_suffix(".ARC").name
                    tgt = chunk_dir / link_name
                    if not tgt.exists():
                        try: os.link(arc_file, tgt)
                        except: shutil.copy2(arc_file, tgt)
                
                cmd = [str(paths["technyx_exe"]), "arc_extract", "."]
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
                env = os.environ.copy()
                env["TEMP"] = str(chunk_dir)
                env["TMP"] = str(chunk_dir)
                subprocess.run(cmd, cwd=str(chunk_dir), env=env, capture_output=True, creationflags=flags)
                
                chunk_results = []
                for out_name, _ in chunk:
                    produced = chunk_dir / Path(out_name).with_suffix(".glb").name
                    final_target = dst_root / out_name
                    try:
                        if produced.exists():
                            shutil.move(str(produced), str(final_target))
                            _fix_glb_lod_nodes(final_target)
                            chunk_results.append((out_name, "OK", f"OK {out_name} → Model"))
                        else:
                            chunk_results.append((out_name, "ERR", f"ERR {out_name} - No model produced"))
                    except Exception as e:
                        chunk_results.append((out_name, "ERR", f"ERR {out_name} - {str(e)}"))
                return chunk_results

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, (os.cpu_count() or 1))) as executor:
                futures = [executor.submit(process_chunk, c_idx, chunk) for c_idx, chunk in enumerate(chunks)]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        res = future.result()
                        for out_name, status, msg in res:
                            completed_so_far += 1
                            if status == "OK": ok += 1
                            elif status == "ERR": err += 1
                            print(f"[{completed_so_far}/{total}] {msg}", flush=True)
                    except Exception as exc:
                        print(f"[{completed_so_far}/{total}] ERR - Chunk Exception: {exc}", flush=True)
                        err += len(chunks[0]) # approx

    elif mode == "dds":
        # OPTIMIZATION: No temp folders for python extracts, saving IO directly
        def process_dds(out_name: str, arc_file: Path) -> tuple[str, str]:
            if arc_file is None or not arc_file.exists(): return "ERR", f"ERR {out_name}"
            if arc_file.stat().st_size == 0: return "SKIP", f"SKIP {out_name}- Empty"
            
            # Pre-check is deferred to the worker thread to avoid blocking the main loop.
            check_state = _check_missing_textures(arc_file, textures_dir)
            if check_state == 1:
                return "SKIP", f"SKIP {out_name} - Already exists"
            elif check_state == 2:
                return "SKIP", f"SKIP {out_name} - No textures in archive"
                
            try:
                count = _extract_raw_textures_from_arc(arc_file, textures_dir)
                if count > 0:
                    return "OK", f"OK {out_name} → Texture"
                else:
                    return "SKIP", f"SKIP {out_name} - No textures"
            except Exception as e:
                return "ERR", f"ERR {out_name} - {str(e)}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {}
            for idx, (out_name, arc_file, is_pre_skipped) in enumerate(jobs, start=1):
                if is_pre_skipped:
                    completed_so_far += 1
                    print(f"[{completed_so_far}/{total}] SKIP {out_name} - Already exists", flush=True)
                    continue
                future = executor.submit(process_dds, out_name, arc_file)
                future_to_idx[future] = idx

            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                completed_so_far += 1
                try:
                    status, msg = future.result()
                    if status == "OK": ok += 1
                    elif status == "ERR": err += 1
                    elif status == "SKIP": skipped += 1
                    print(f"[{completed_so_far}/{total}] {msg}", flush=True)
                except Exception as exc:
                    print(f"[{completed_so_far}/{total}] ERR - Exception: {exc}", flush=True)
                    err += 1

    try:
        shutil.rmtree(temp_base, ignore_errors=True)
    except Exception:
        pass

    print(final_summary(ok, err, skipped, total))
    print_output_location(dst_root)
    return 0


def cmd_convert_sounds(paths: dict[str, Path], selected: str | None = None) -> int:
    ensure_workspace_dirs(paths)
    src_root = paths["workspace_archive"]
    if not src_root.exists():
        src_root = paths["src_archive_legacy"]
    if not src_root.exists():
        return 1

    dst_root = paths["workspace_sounds"]

    print("===== Converting Sounds =====", flush=True)
    hdrs = list({p for p in src_root.rglob("*.HDR")} | {p for p in src_root.rglob("*.hdr")})
    oggs = list({p for p in src_root.rglob("*.OGG")} | {p for p in src_root.rglob("*.ogg")})

    if selected:
        tokens = [norm_token(t).lower() for t in selected.split(",")]
        tokens = [t.replace("\\", "/").split("/")[-1] for t in tokens if t]
        invalid = [t for t in tokens if not (t.endswith(".hdr") or t.endswith(".ogg"))]
        if invalid:
            print("ERR: selected files must use .hdr or .ogg extension only.")
            print("Invalid:")
            for name in invalid:
                print(f"  - {name}")
            return 1
        if tokens:
            hdrs = [f for f in hdrs if f.name.lower() in tokens]
            oggs = [f for f in oggs if f.name.lower() in tokens]
    
    total = len(hdrs) + len(oggs)
    idx = 0
    ok = err = skipped = 0
    
    import zipfile
    for ogg in oggs:
        idx += 1
        out_ogg = dst_root / ogg.name
        if out_ogg.exists():
            skipped += 1
            print(f"[{idx}/{total}] SKIP {ogg.name} - Already exists")
        else:
            try:
                shutil.copy2(ogg, out_ogg)
                ok += 1
                print(f"[{idx}/{total}] OK {ogg.name} → Audio")
            except Exception as e:
                err += 1
                print(f"[{idx}/{total}] ERR {ogg.name} - {str(e)}")

    for hdr in hdrs:
        idx += 1
        expected_dir = dst_root / hdr.stem
        if expected_dir.exists() and any(expected_dir.iterdir()):
            skipped += 1
            print(f"[{idx}/{total}] SKIP {hdr.name} - Already exists")
            continue
            
        expected_dir.mkdir(exist_ok=True)
        try:
            config_src = paths["technyx_cwd"] / "technyx_toolset.config"
            if config_src.exists():
                tmp_cfg = hdr.parent / "technyx_toolset.config"
                config_text = config_src.read_text(encoding="utf-8").replace('create-zip="true"', 'create-zip="false"')
                tmp_cfg.write_text(config_text, encoding="utf-8")

            cmd = [str(paths["technyx_exe"]), "hdr_to_wav", str(hdr)]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            env = os.environ.copy()
            env["TEMP"] = str(hdr.parent)
            env["TMP"] = str(hdr.parent)
            subprocess.run(cmd, cwd=str(hdr.parent), env=env, capture_output=True, timeout=40, creationflags=flags)
            
            # Since create-zip="false", we should get a directory!
            wav_dir = hdr.parent / hdr.stem
            if not wav_dir.exists():
                wav_dir = hdr.parent / hdr.name
            
            # Check for zip just in case
            zip_file = hdr.parent / f"{hdr.stem}.zip"
            if not zip_file.exists():
                for f in hdr.parent.glob("*.zip"):
                    if f.stem.lower() == hdr.stem.lower():
                        zip_file = f
                        break
            
            found_wavs = False
            if wav_dir.exists() and wav_dir.is_dir():
                for root_file in wav_dir.iterdir():
                    shutil.copy2(root_file, expected_dir / root_file.name)
                try: shutil.rmtree(wav_dir, ignore_errors=True)
                except: pass
                found_wavs = True
                
            elif zip_file.exists():
                with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                    zip_ref.extractall(expected_dir)
                try: zip_file.unlink()
                except: pass
                try: (hdr.parent / f"{zip_file.name}.cache").unlink()
                except: pass
                found_wavs = True

            try: (hdr.parent / "technyx_toolset.config").unlink()
            except: pass

            if found_wavs:
                # Add index prefixes to preserve order based on HDR
                try:
                    hdr_data = hdr.read_bytes()
                    if hdr_data.startswith(b"snda"):
                        _, _, num_items = struct.unpack_from("<4sfI", hdr_data, 0)
                        hdr_names = []
                        for i in range(num_items):
                            ipos = 28 + i * 64
                            n_raw = hdr_data[ipos+4:ipos+24]
                            n_str = n_raw.split(b"\x00")[0].decode("ascii", errors="ignore")
                            hdr_names.append(n_str)
                        # Apply prefixes to files in expected_dir
                        for f in expected_dir.iterdir():
                            if not f.is_file(): continue
                            f_stem = f.name
                            if f_stem.lower().endswith(".wav"):
                                f_stem = f_stem[:-4]
                            idx_found = -1
                            for i, h_name in enumerate(hdr_names):
                                if h_name.lower() == f_stem.lower():
                                    idx_found = i
                                    break
                            if idx_found != -1:
                                f.rename(f.parent / f"{idx_found}_{f.name}")
                except Exception as e:
                    print(f"WRN: Could not add indexes to {hdr.name}: {e}")

                produced_types = set()
                for f in expected_dir.iterdir():
                    if f.is_file():
                        if f.suffix.lower() == ".wav":
                            produced_types.add("wav")
                        elif f.suffix.lower() == ".ogg":
                            produced_types.add("ogg")
                if produced_types:
                    ok += 1
                    print(f"[{idx}/{total}] OK {hdr.name} → Audio")
            else:
                # Determine expected types from HDR
                err += 1
                try:
                    hdr_data = hdr.read_bytes()
                    expected_types = set()
                    if hdr_data.startswith(b"snda"):
                        expected_types.add("wav")
                        if b"OGG" in hdr_data or b".ogg" in hdr_data.lower():
                            expected_types.add("ogg")
                    elif b"OGG" in hdr_data or b".ogg" in hdr_data.lower():
                        expected_types.add("ogg")
                    if not expected_types:
                        expected_types.add("wav")
                except Exception:
                    expected_types = {"wav"}

                produced_types = set()
                if expected_dir.exists():
                    for f in expected_dir.iterdir():
                        if f.is_file():
                            if f.suffix.lower() == ".wav":
                                produced_types.add("wav")
                            elif f.suffix.lower() == ".ogg":
                                produced_types.add("ogg")

                missing_types = expected_types - produced_types
                if missing_types:
                    if "wav" in missing_types and "ogg" in missing_types:
                        missing_str = "WAVs/OGGs"
                    elif "wav" in missing_types:
                        missing_str = "WAVs"
                    else:
                        missing_str = "OGGs"
                    print(f"[{idx}/{total}] ERR {hdr.name} - No {missing_str} produced")
                try:
                    if expected_dir.exists() and not any(expected_dir.iterdir()):
                        expected_dir.rmdir()
                except: pass
        except Exception as e:
            err += 1
            print(f"[{idx}/{total}] ERR {hdr.name} - {str(e)}")
            try:
                if expected_dir.exists() and not any(expected_dir.iterdir()):
                    expected_dir.rmdir()
            except: pass

    print(final_summary(ok, err, skipped, total))
    print_output_location(dst_root)
    return 0


def cmd_convert_texts(paths: dict[str, Path], selected: str | None = None) -> int:
    ensure_workspace_dirs(paths)
    src_root = paths["workspace_archive"]
    if not src_root.exists():
        src_root = paths["src_archive_legacy"]
    if not src_root.exists():
        return 1

    dst_root = paths["workspace_texts"]
    print("===== Converting Texts =====", flush=True)
    ldas = list({p for p in src_root.rglob("*.LDA")} | {p for p in src_root.rglob("*.lda")})

    if selected:
        tokens = [norm_token(t).lower() for t in selected.split(",")]
        tokens = [t.replace("\\", "/").split("/")[-1] for t in tokens if t]
        invalid = [t for t in tokens if not t.endswith(".lda")]
        if invalid:
            print("ERR: selected files must use .lda extension only.")
            print("Invalid:")
            for name in invalid:
                print(f"  - {name}")
            return 1
        if tokens:
            ldas = [f for f in ldas if f.name.lower() in tokens]
    
    total = len(ldas)
    idx = 0
    ok = err = skipped = 0
    
    for lda in ldas:
        idx += 1
        out_txt = dst_root / f"{lda.stem}.txt"
        if out_txt.exists() and out_txt.stat().st_size > 0:
            skipped += 1
            print(f"[{idx}/{total}] SKIP {lda.name} - Already exists")
            continue
            
        try:
            cmd = [str(paths["technyx_exe"]), "lda_to_txt", str(lda)]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            subprocess.run(cmd, cwd=str(lda.parent), capture_output=True, timeout=10, creationflags=flags)
            
            gen_txt = lda.with_suffix(".txt")
            if not gen_txt.exists():
                for f in lda.parent.glob("*.txt"):
                    if f.stem.lower() == lda.stem.lower():
                        gen_txt = f
                        break
                        
            if gen_txt.exists():
                shutil.move(str(gen_txt), str(out_txt))
                ok += 1
                print(f"[{idx}/{total}] OK {lda.name} → TXT")
            else:
                err += 1
                print(f"[{idx}/{total}] ERR {lda.name} - No text produced")
        except Exception as e:
            err += 1
            print(f"[{idx}/{total}] ERR {lda.name} - {str(e)}")
            
    print(final_summary(ok, err, skipped, total))
    print_output_location(dst_root)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return 1

    paths = build_paths()

    if args[0].lower() in ("extract", "x"):
        if len(args) >= 2 and args[1].lower() == "archive.ar":
            return cmd_extract(paths)
        return 1

    if args[0].lower() == "convert":
        if len(args) >= 2:
            if args[1].lower() in ("arc--glb", "-arc--glb"):
                selected = None
                if len(args) > 2:
                    selected = " ".join(args[2:])
                return cmd_convert(paths, selected, mode="glb")
            elif args[1].lower() in ("arc--dds", "-arc--dds"):
                selected = None
                if len(args) > 2:
                    selected = " ".join(args[2:])
                return cmd_convert(paths, selected, mode="dds")
            elif args[1].lower() in ("hdr--wav", "-hdr--wav"):
                selected = None
                if len(args) > 2:
                    selected = " ".join(args[2:])
                return cmd_convert_sounds(paths, selected)
            elif args[1].lower() in ("lda--txt", "-lda--txt"):
                selected = None
                if len(args) > 2:
                    selected = " ".join(args[2:])
                return cmd_convert_texts(paths, selected)
        return 1

    if args[0].lower() == "build":
        selected = " ".join(args[1:]) if len(args) > 1 else None
        return cmd_build(paths, selected)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
