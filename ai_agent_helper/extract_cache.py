"""
Extract de_cache map data from CS2 VPK files.
Reads overview txt (for coordinates) and decodes the radar vtex_c → PNG.
Run: python extract_cache.py
Output: webapp/public/data/de_cache/data.json + radar.png
"""
import struct
import sys
import os
import json
from pathlib import Path

try:
    import vpk as vpklib
except ImportError:
    print("pip install vpk"); sys.exit(1)

try:
    import lz4.block as lz4block
except ImportError:
    print("pip install lz4"); sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("pip install Pillow"); sys.exit(1)

# ── find CS2 ──────────────────────────────────────────────────────────────────
def _find_cs2():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\WOW6432Node\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "InstallPath")[0])
    except Exception:
        raise RuntimeError("Steam not found in registry")
    lf = steam / "steamapps" / "libraryfolders.vdf"
    roots = [steam / "steamapps"]
    if lf.exists():
        for line in lf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if '"path"' in line.lower():
                p = line.split('"')[-2].replace("\\\\", "\\")
                roots.append(Path(p) / "steamapps")
    for root in roots:
        cs2 = root / "common" / "Counter-Strike Global Offensive" / "game" / "csgo"
        if cs2.exists():
            return cs2
    raise RuntimeError("CS2 csgo folder not found")

# ── parse overview txt ────────────────────────────────────────────────────────
def _parse_kv(text: str) -> dict:
    import re
    result = {}
    for line in text.splitlines():
        # strip inline // comments
        line = line.split("//")[0].strip()
        m = re.findall(r'"([^"]*)"', line)
        if len(m) >= 2:
            result[m[0]] = m[1]
    return result

# ── decode BC3 (DXT5) 4×4 block ───────────────────────────────────────────────
def _decode_dxt5_block(block: bytes, out: bytearray, bx: int, by: int, width: int):
    # Alpha: 6 bytes
    a0, a1 = block[0], block[1]
    abits = int.from_bytes(block[2:8], 'little')
    if a0 > a1:
        atab = [a0, a1,
                (6*a0+1*a1)//7, (5*a0+2*a1)//7, (4*a0+3*a1)//7,
                (3*a0+4*a1)//7, (2*a0+5*a1)//7, (1*a0+6*a1)//7]
    else:
        atab = [a0, a1,
                (4*a0+1*a1)//5, (3*a0+2*a1)//5, (2*a0+3*a1)//5, (1*a0+4*a1)//5,
                0, 255]

    # Color: 8 bytes (same as DXT1)
    c0 = int.from_bytes(block[8:10], 'little')
    c1 = int.from_bytes(block[10:12], 'little')
    cbits = int.from_bytes(block[12:16], 'little')

    def rgb565(c):
        r = ((c >> 11) & 0x1f) * 255 // 31
        g = ((c >> 5)  & 0x3f) * 255 // 63
        b = (c & 0x1f) * 255 // 31
        return r, g, b

    r0,g0,b0 = rgb565(c0)
    r1,g1,b1 = rgb565(c1)
    ctab = [
        (r0,g0,b0),
        (r1,g1,b1),
        ((2*r0+r1)//3, (2*g0+g1)//3, (2*b0+b1)//3),
        ((r0+2*r1)//3, (g0+2*g1)//3, (b0+2*b1)//3),
    ]

    for ty in range(4):
        for tx in range(4):
            px = bx * 4 + tx
            py = by * 4 + ty
            if px >= width:
                continue
            idx = ty * 4 + tx
            ai = (abits >> (idx * 3)) & 7
            ci = (cbits >> (idx * 2)) & 3
            r, g, b = ctab[ci]
            a = atab[ai]
            pos = (py * width + px) * 4
            out[pos]     = r
            out[pos + 1] = g
            out[pos + 2] = b
            out[pos + 3] = a

def _decode_bc3(data: bytes, width: int, height: int) -> Image.Image:
    out = bytearray(width * height * 4)
    blocks_x = (width  + 3) // 4
    blocks_y = (height + 3) // 4
    for by in range(blocks_y):
        for bx in range(blocks_x):
            off = (by * blocks_x + bx) * 16
            _decode_dxt5_block(data[off:off+16], out, bx, by, width)
    return Image.frombuffer("RGBA", (width, height), bytes(out), "raw", "RGBA", 0, 1)

# ── vtex_c reader ─────────────────────────────────────────────────────────────
def _read_vtex(data: bytes) -> bytes:
    """Return raw BC3 bytes from a Source 2 vtex_c file."""
    # Skip REDI/DATA block preamble to find VTexData
    # Search for DATA block header
    pos = 0
    while pos < len(data) - 8:
        tag = data[pos:pos+4]
        if tag == b'DATA':
            block_offset = pos + 4
            block_size = struct.unpack_from('<I', data, block_offset)[0]
            # VTexData starts right after the 8-byte block header
            vd_start = block_offset + 4
            # version(2) + flags(2) + reflectivity(16) + width(2) + height(2) + depth(2) + format(1) + mip(1) + picmip(4)
            version, flags = struct.unpack_from('<HH', data, vd_start)
            width, height  = struct.unpack_from('<HH', data, vd_start + 20)
            depth, fmt, mip = struct.unpack_from('<HBB', data, vd_start + 24)
            extra_count     = struct.unpack_from('<I', data, vd_start + 28)[0]
            print(f"  VTexData: v={version} {width}x{height} fmt={fmt} mips={mip} extras={extra_count}")

            # Each extra data entry is 8 bytes (type + offset)
            tex_data_start = vd_start + 32 + extra_count * 8
            tex_data = data[tex_data_start:]

            if fmt == 28:
                # Try LZ4 block decompress → expect BC3 size
                expected = width * height  # 1 byte/px for BC3 (8bpp)
                try:
                    raw = lz4block.decompress(tex_data, uncompressed_size=expected)
                    print(f"  LZ4 decompress OK → {len(raw)} bytes")
                    return raw
                except Exception as e:
                    print(f"  LZ4 failed: {e}")
                # Try treating as raw BC3
                bc3_expected = width * height  # = blocks_x * blocks_y * 16
                if len(tex_data) >= bc3_expected:
                    print(f"  Using raw BC3 ({len(tex_data)} bytes)")
                    return tex_data[:bc3_expected]
            break
        pos += 1
    raise ValueError("DATA block not found or unsupported format")

def main():
    csgo = _find_cs2()
    pak = csgo / "pak01_dir.vpk"
    print(f"Opening VPK: {pak}")
    pk = vpklib.open(str(pak))

    # ── read overview txt ──
    txt_path = "resource/overviews/de_cache.txt"
    print(f"Reading {txt_path} ...")
    txt_data = pk.get_file(txt_path).read().decode("utf-8", errors="replace")
    kv = _parse_kv(txt_data)
    print(f"  KV: {kv}")

    out_dir = Path(__file__).parent.parent / "webapp" / "public" / "data" / "de_cache"
    out_dir.mkdir(parents=True, exist_ok=True)

    data_json = {
        "x": float(kv.get("pos_x", 0)),
        "y": float(kv.get("pos_y", 0)),
        "scale": float(kv.get("scale", 1)),
    }
    (out_dir / "data.json").write_text(json.dumps(data_json, indent="\t"))
    print(f"  Wrote data.json: {data_json}")

    # ── read vtex_c ──
    vtex_path = "panorama/images/overheadmaps/de_cache_radar_psd.vtex_c"
    print(f"Reading {vtex_path} ...")
    vtex_data = pk.get_file(vtex_path).read()
    print(f"  vtex_c size: {len(vtex_data)} bytes")
    print(f"  First bytes: {vtex_data[:16].hex()}")

    raw_bc3 = _read_vtex(vtex_data)

    # Decode BC3 → RGBA image
    print("Decoding BC3 → RGBA ...")
    img = _decode_bc3(raw_bc3, 1024, 1024)
    img = img.convert("RGBA")
    out_png = out_dir / "radar.png"
    img.save(str(out_png))
    print(f"  Saved {out_png}")

    # Also create a background.png (blurred/dark version)
    bg = img.convert("RGBA")
    out_bg = out_dir / "background.png"
    bg.save(str(out_bg))
    print(f"  Saved {out_bg}")

    print("\nDone! de_cache is ready.")

if __name__ == "__main__":
    main()
