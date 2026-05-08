"""Find m_angEyeAngles offset by scanning the schema metadata in client.dll."""
import struct

DLL = r"D:\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\bin\win64\client.dll"
TARGET = b"m_angEyeAngles\x00"

data = open(DLL, "rb").read()

# Parse PE sections for RVA->raw conversion
pe = struct.unpack_from("<I", data, 0x3C)[0]
ns = struct.unpack_from("<H", data, pe + 6)[0]
os_ = struct.unpack_from("<H", data, pe + 20)[0]
so = pe + 24 + os_
sections = []
for i in range(ns):
    s = so + i * 40
    va  = struct.unpack_from("<I", data, s + 12)[0]
    rs  = struct.unpack_from("<I", data, s + 16)[0]
    ro  = struct.unpack_from("<I", data, s + 20)[0]
    vs  = struct.unpack_from("<I", data, s + 8)[0]
    sections.append((va, ro, min(vs, rs)))

def rva_to_raw(rva):
    for va, ro, sz in sections:
        if va <= rva < va + sz:
            return ro + (rva - va)
    return None

image_base = struct.unpack_from("<Q", data, pe + 24 + 24)[0]

# Find all occurrences of the field name string
pos = 0
print(f"Scanning for '{TARGET.decode().rstrip(chr(0))}' in client.dll...")
found = []
while True:
    idx = data.find(TARGET, pos)
    if idx == -1:
        break
    found.append(idx)
    pos = idx + 1

print(f"Found {len(found)} occurrence(s) at raw offsets: {[hex(x) for x in found]}")
print()

# For each occurrence, scan nearby memory for a plausible offset value
# cs2-dumper schema layout: name pointer, then field offset is stored as uint32 nearby
for raw_str in found[:5]:
    str_rva = None
    for va, ro, sz in sections:
        if ro <= raw_str < ro + sz:
            str_rva = va + (raw_str - ro)
            break
    str_va = image_base + str_rva if str_rva else 0
    print(f"  String at raw=0x{raw_str:X}  RVA=0x{str_rva:X}  VA=0x{str_va:X}")

    # Search for pointers to this string in the binary (schema registration)
    str_va_bytes = struct.pack("<Q", str_va)
    ref_pos = 0
    refs = []
    while len(refs) < 5:
        ref = data.find(str_va_bytes, ref_pos)
        if ref == -1:
            break
        refs.append(ref)
        ref_pos = ref + 1

    for ref_raw in refs:
        # Read 64 bytes before and after the pointer to find the offset value
        chunk = data[ref_raw - 32: ref_raw + 64]
        # The field offset in cs2 schema is typically stored as a 32-bit int
        # Look for values in a plausible range (0x3000 - 0x5000 for deep pawn fields)
        for off in range(0, len(chunk) - 4, 4):
            val = struct.unpack_from("<I", chunk, off)[0]
            if 0x2000 < val < 0x8000:
                print(f"    ref@raw=0x{ref_raw:X} +{off-32:+d}: offset candidate = 0x{val:X} ({val})")
    print()
