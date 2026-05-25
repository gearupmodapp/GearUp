import os
import sys
from pathlib import Path

def extract_dds_from_arc(arc_path, out_dir):
    try:
        data = arc_path.read_bytes()
    except Exception as e:
        print(f"Error reading {arc_path.name}: {e}")
        return 0
        
    count = 0
    idx = 0
    while True:
        # Search for DDS magic "DDS "
        idx = data.find(b'DDS ', idx)
        if idx == -1:
            break
        
        next_idx = data.find(b'DDS ', idx + 4)
        if next_idx == -1:
            chunk = data[idx:]
        else:
            chunk = data[idx:next_idx]
            
        out_name = f"{arc_path.stem}_{count:03d}.dds"
        out_file = out_dir / out_name
        try:
            out_file.write_bytes(chunk)
            count += 1
        except Exception as e:
            pass
        
        idx += 4
        
    return count

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: extract_arc_dds.py <arc_folder> <out_folder>")
        sys.exit(1)
        
    in_folder = Path(sys.argv[1])
    out_folder = Path(sys.argv[2])
    out_folder.mkdir(parents=True, exist_ok=True)
    
    total = 0
    for arc_file in in_folder.rglob("*.ARC"):
        c = extract_dds_from_arc(arc_file, out_folder)
        if c > 0:
            print(f"[{c}/{c}] OK *.DDS")
        total += c
    print(f"Total DDS extracted: {total}")
