import struct, json, time
from pathlib import Path

DLL = r"D:\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\bin\win64\client.dll"
CACHE = Path(__file__).parent / "offsets_cache.json"

# sig: 3-byte opcode prefix for a RIP-relative MOV, context bytes at +7 to reduce false matches
SIGS = {
    "dwEntityList":            (b"\x48\x89\x0D", b"\xe9"),
    "dwGlobalVars":            (b"\x48\x89\x15", b"\x48\x89\x42"),
    "dwLocalPlayerController": (b"\x48\x8B\x05", b"\x41\x89\xBE"),
    "dwViewMatrix":            (b"\x48\x8D\x0D", b"\x48\xC1\xE0\x06"),
}

data = open(DLL, "rb").read()
pe   = struct.unpack_from("<I", data, 0x3C)[0]
ns   = struct.unpack_from("<H", data, pe + 6)[0]
os_  = struct.unpack_from("<H", data, pe + 20)[0]
so   = pe + 24 + os_

sections = []
for i in range(ns):
    s = so + i*40
    va  = struct.unpack_from("<I", data, s+12)[0]
    rs  = struct.unpack_from("<I", data, s+16)[0]
    ro  = struct.unpack_from("<I", data, s+20)[0]
    vs  = struct.unpack_from("<I", data, s+8)[0]
    sections.append((va, ro, min(vs, rs)))

def raw_to_rva(raw):
    for va, ro, sz in sections:
        if ro <= raw < ro + sz:
            return va + (raw - ro)
    return None

results = {}
for name, (sig, ctx) in SIGS.items():
    pos, found = 0, None
    while True:
        idx = data.find(sig, pos)
        if idx == -1: break
        rva_instr_end = raw_to_rva(idx + 7)
        if rva_instr_end is not None:
            rel32 = struct.unpack_from("<i", data, idx+3)[0]
            target_rva = (rva_instr_end + rel32) & 0xFFFFFFFF
            ctx_ok = data[idx+7:idx+7+len(ctx)] == ctx
            if ctx_ok:
                found = target_rva
                break
        pos = idx + 1
    results[name] = found
    print(f"  {name:32s} = 0x{found:X}" if found else f"  {name:32s} = NOT FOUND")

print()
# Patch cache
if CACHE.exists():
    cache = json.loads(CACHE.read_text())
    for k, v in results.items():
        if v: cache["globals"][k] = v
    cache["_ts"] = time.time()
    CACHE.write_text(json.dumps(cache, indent=2))
    print("Patched", CACHE.name)
else:
    print(json.dumps(results, indent=2))
