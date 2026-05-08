#!/usr/bin/env python3
"""
cs2_radar — combined CS2 memory reader + WebSocket server + HTTP static server.
Double-click the compiled exe to start everything; a browser tab opens automatically.
"""
import asyncio
import ctypes
import ctypes.wintypes as wintypes
import http.server
import json
import logging
import logging.handlers
import struct
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    import websockets
except ImportError:
    print("[error] websockets not installed. Run: pip install websockets")
    sys.exit(1)

# ── config ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "config.json"
CACHE_FILE  = ROOT / "offsets_cache.json"
LOG_FILE    = ROOT / "radar.log"

WS_PORT       = 22006
HTTP_PORT     = 5173   # built-dist server; same port as Vite so URLs always match
POLL_INTERVAL = 0.033  # ~30 Hz
CACHE_MAX_AGE = 3600
DUMPER_BASE   = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output"

# ── logging ───────────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("radar")
    log.setLevel(logging.DEBUG)

    # Console — INFO and above, coloured level tag
    _COLOURS = {
        "DEBUG":    "\033[36m",   # cyan
        "INFO":     "\033[32m",   # green
        "WARNING":  "\033[33m",   # yellow
        "ERROR":    "\033[31m",   # red
        "CRITICAL": "\033[35m",   # magenta
    }
    _RESET = "\033[0m"

    class _ColouredFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            colour = _COLOURS.get(record.levelname, "")
            record.levelname = f"{colour}{record.levelname:<8}{_RESET}"
            return super().format(record)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(_ColouredFormatter(
        fmt="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    ))
    log.addHandler(console)

    # Rotating file — DEBUG and above, plain text, keeps last 2 × 1 MB
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    # Silence noisy websocket-client internal chatter
    logging.getLogger("websocket").setLevel(logging.WARNING)

    return log

log = _setup_logging()

# ── windows api ───────────────────────────────────────────────────────────────
TH32CS_SNAPPROCESS  = 0x00000002
TH32CS_SNAPMODULE   = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_VM_READ     = 0x0010
PROCESS_QUERY_INFO  = 0x0400
INVALID_HANDLE      = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      wintypes.LONG),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",        wintypes.DWORD),
        ("th32ModuleID",  wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage",  wintypes.DWORD),
        ("ProccntUsage",  wintypes.DWORD),
        ("modBaseAddr",   ctypes.POINTER(wintypes.BYTE)),
        ("modBaseSize",   wintypes.DWORD),
        ("hModule",       wintypes.HMODULE),
        ("szModule",      ctypes.c_char * 256),
        ("szExePath",     ctypes.c_char * 260),
    ]


# ── memory ────────────────────────────────────────────────────────────────────
class Memory:
    def __init__(self):
        self.handle = None
        self.pid    = None

    def find_pid(self, name: str) -> int | None:
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE:
            return None
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        try:
            if kernel32.Process32First(snap, ctypes.byref(entry)):
                while True:
                    if entry.szExeFile.decode() == name:
                        return entry.th32ProcessID
                    if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snap)
        return None

    def open(self, pid: int) -> bool:
        self.pid    = pid
        self.handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFO, False, pid)
        return bool(self.handle)

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None
            self.pid    = None

    def get_module_base(self, dll: str) -> int:
        snap = kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        if snap == INVALID_HANDLE:
            return 0
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        try:
            if kernel32.Module32First(snap, ctypes.byref(entry)):
                while True:
                    if entry.szModule.decode().lower() == dll.lower():
                        return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                    if not kernel32.Module32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snap)
        return 0

    def _read(self, address: int, size: int) -> bytes:
        if not address:
            return bytes(size)
        buf  = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read))
        return buf.raw

    def ptr(self, address: int) -> int:
        v = struct.unpack_from("<Q", self._read(address, 8))[0]
        # Require valid user-space pointer (> 4 KB, below Windows user-space ceiling)
        return v if 0x1000 <= v < 0x7FFFFFFFFFFF else 0

    def u64(self, address: int) -> int:
        return struct.unpack_from("<Q", self._read(address, 8))[0]

    def u32(self, address: int) -> int:
        return struct.unpack_from("<I", self._read(address, 4))[0]

    def i32(self, address: int) -> int:
        return struct.unpack_from("<i", self._read(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack_from("<f", self._read(address, 4))[0]

    def bool8(self, address: int) -> bool:
        d = self._read(address, 1)
        return bool(d[0])

    def cstring(self, address: int, max_len: int = 256) -> str:
        if not address:
            return ""
        data = self._read(address, max_len)
        end  = data.find(b"\x00")
        raw  = data[:end] if end != -1 else data
        return raw.decode("utf-8", errors="ignore")

    def msvc_string(self, address: int) -> str:
        """Read an MSVC std::string object stored at address in game memory."""
        if not address:
            return ""
        size = self.u32(address + 0x10)
        if size == 0 or size > 512:
            return ""
        if size < 16:
            raw = self._read(address, size)
        else:
            ptr = self.ptr(address)
            if not ptr:
                return ""
            raw = self._read(ptr, size)
        return raw.decode("utf-8", errors="ignore").rstrip("\x00")

    def string_field(self, address: int) -> str:
        """Read a schema string field — tries char* first, then MSVC string."""
        ptr = self.ptr(address)
        if ptr:
            s = self.cstring(ptr)
            if s:
                return s
        return self.msvc_string(address)


# ── offset loading ────────────────────────────────────────────────────────────
def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())


def _parse_fields(raw: dict) -> dict:
    """Normalize cs2-dumper client_dll.json into {ClassName: {field: offset}}."""
    # Unwrap {"client.dll": {"classes": {...}}} — actual format from cs2-dumper
    if len(raw) == 1:
        inner = next(iter(raw.values()))
        if isinstance(inner, dict):
            raw = inner

    # Unwrap {"classes": {...}, "enums": {...}}
    if "classes" in raw and isinstance(raw["classes"], dict):
        raw = raw["classes"]

    out = {}
    for cls, data in raw.items():
        if not isinstance(data, dict):
            continue
        fields = {}
        inner_fields = data.get("fields", data)  # prefer explicit "fields" key

        for fname, fdata in inner_fields.items():
            if isinstance(fdata, int):
                fields[fname] = fdata
            elif isinstance(fdata, dict):
                off = fdata.get("offset") or fdata.get("value", 0)
                if off:
                    fields[fname] = off

        if fields:
            out[cls] = fields

    log.debug("_parse_fields: parsed %d classes", len(out))
    return out


def load_offsets() -> dict:
    dll_path  = _find_client_dll()
    dll_mtime = dll_path.stat().st_mtime if dll_path else 0

    if CACHE_FILE.exists():
        try:
            cached   = json.loads(CACHE_FILE.read_text())
            cache_ts = cached.get("_ts", 0)
            # Cache is valid as long as client.dll hasn't changed since it was written.
            # No time-based expiry — offsets only go stale when the game updates.
            if cache_ts > dll_mtime:
                log.info("using cached offsets (client.dll unchanged)")
                return cached
            log.info("client.dll updated since last cache — rescanning...")
        except Exception:
            pass

    log.info("fetching offsets from cs2-dumper...")
    result = None
    try:
        raw_off    = _fetch(f"{DUMPER_BASE}/offsets.json")
        raw_client = _fetch(f"{DUMPER_BASE}/client_dll.json")

        client_globals = (
            raw_off.get("client.dll") or
            raw_off.get("offsets", {}).get("client.dll") or {}
        )

        result = {
            "_ts":     time.time(),
            "globals": client_globals,
            "fields":  _parse_fields(raw_client),
        }
        log.info("offsets fetched from cs2-dumper")
    except Exception as exc:
        log.warning("fetch failed: %s", exc)
        if CACHE_FILE.exists():
            log.info("falling back to cached offsets")
            result = json.loads(CACHE_FILE.read_text())
        else:
            log.critical("no cached offsets and fetch failed — cannot continue")
            sys.exit(1)

    # Always run local scanner to patch any offsets cs2-dumper may have wrong
    # for the currently installed client.dll build
    log.info("running local binary scan to verify/patch offsets...")
    _scan_globals_from_dll(result)   # saves cache internally
    return result

def _find_client_dll() -> Path | None:
    """Locate client.dll on disk using the same Steam registry search as MapExtractor."""
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"SOFTWARE\Valve\Steam", r"SOFTWARE\WOW6432Node\Valve\Steam"):
                try:
                    key  = winreg.OpenKey(hive, sub)
                    stem = Path(winreg.QueryValueEx(key, "InstallPath")[0])
                    dll  = stem / "steamapps/common/Counter-Strike Global Offensive/game/csgo/bin/win64/client.dll"
                    if dll.exists():
                        return dll
                except Exception:
                    pass
    except Exception:
        pass
    for drive in ("C", "D", "E"):
        dll = Path(f"{drive}:/Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/bin/win64/client.dll")
        if dll.exists():
            return dll
    return None


def _scan_globals_from_dll(offsets: dict) -> bool:
    """
    Scan client.dll on disk for global offsets using byte signatures.
    Patches offsets['globals'] in-place and saves the cache.
    Returns True if at least dwEntityList was found.
    """
    dll_path = _find_client_dll()
    if not dll_path:
        log.warning("offset scanner: client.dll not found on disk")
        return False

    log.info("offset scanner: scanning %s ...", dll_path.name)
    try:
        data = dll_path.read_bytes()
    except Exception as exc:
        log.warning("offset scanner: could not read client.dll: %s", exc)
        return False

    # Parse PE section table to build raw-offset -> RVA mapping
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

    def raw_to_rva(raw: int) -> int | None:
        for va, ro, sz in sections:
            if ro <= raw < ro + sz:
                return va + (raw - ro)
        return None

    # sig: (3-byte opcode, context bytes at +7)
    SIGS = {
        "dwEntityList":            (b"\x48\x89\x0D", b"\xe9"),
        "dwGlobalVars":            (b"\x48\x89\x15", b"\x48\x89\x42"),
        "dwLocalPlayerController": (b"\x48\x8B\x05", b"\x41\x89\xBE"),
        "dwViewMatrix":            (b"\x48\x8D\x0D", b"\x48\xC1\xE0\x06"),
    }

    found_any = False
    for name, (sig, ctx) in SIGS.items():
        pos = 0
        while True:
            idx = data.find(sig, pos)
            if idx == -1:
                break
            rva_end = raw_to_rva(idx + 7)
            if rva_end is not None and data[idx + 7: idx + 7 + len(ctx)] == ctx:
                rel32 = struct.unpack_from("<i", data, idx + 3)[0]
                target_rva = (rva_end + rel32) & 0xFFFFFFFF
                offsets["globals"][name] = target_rva
                log.info("offset scanner: %s = 0x%X", name, target_rva)
                found_any = True
                break
            pos = idx + 1

    # Also scan for field offsets stored in schema metadata (name string → nearby offset)
    FIELD_NAMES = {
        ("C_CSPlayerPawn",  "m_angEyeAngles"): 0x10,   # offset is +16 bytes after name ptr in schema entry
    }
    image_base_va = struct.unpack_from("<Q", data, pe + 24 + 24)[0]
    for (cls, field), schema_off in FIELD_NAMES.items():
        needle = field.encode() + b"\x00"
        str_raw = data.find(needle)
        if str_raw == -1:
            continue
        # Find section containing the string to get its VA
        for va, ro, sz in sections:
            if ro <= str_raw < ro + sz:
                str_va = image_base_va + va + (str_raw - ro)
                break
        else:
            continue
        # Search for pointer to this string
        str_va_bytes = struct.pack("<Q", str_va)
        ref = data.find(str_va_bytes)
        if ref == -1:
            continue
        # Read field offset at schema_off bytes after the name pointer
        field_off_raw = struct.unpack_from("<I", data, ref + schema_off)[0]
        if 0x100 < field_off_raw < 0x10000:
            offsets["fields"].setdefault(cls, {})[field] = field_off_raw
            log.info("offset scanner: %s.%s = 0x%X", cls, field, field_off_raw)
            found_any = True

    if found_any:
        offsets["_ts"] = time.time()
        try:
            CACHE_FILE.write_text(json.dumps(offsets, indent=2))
        except Exception:
            pass

    return found_any


# ── cs2 entity reading ────────────────────────────────────────────────────────
ENT_ENTRY_MASK   = 0x7FFF
INVALID_EHANDLE  = 0xFFFFFFFF

# weapon type ids from CCSWeaponBaseVData::m_WeaponType
_PRIMARY_TYPES   = {2, 3, 4, 5, 6}   # smg, rifle, shotgun, sniper, mg
_PISTOL_TYPE     = 1
_MELEE_TYPES     = {0, 8}             # knife, taser
_GRENADE_TYPE    = 9

_GRENADE_CLASS_TO_TYPE = {
    # Projectile classes (entities that fly through the air)
    "C_SmokeGrenadeProjectile": "smoke",
    "C_MolotovProjectile":      "molly",   # in-flight trajectory
    "C_HEGrenadeProjectile":    "he",
    "C_FlashbangProjectile":    "flash",   # C_Flashbang is inventory item — use projectile
    "C_DecoyProjectile":        "decoy",
    # Post-land effects
    "C_Inferno":                "molly",   # fire zone after landing
}
_GRENADE_CLASSES = set(_GRENADE_CLASS_TO_TYPE)

# hardcoded offsets that never come from schema
_CURTIME_OFF          = 0x30    # CGlobalVarsBase::m_curtime
_MAP_NAME_OFF         = 0x188   # CGlobalVarsBase::map name string
_IDENTITY_CLASS_OFF   = 0x08    # CEntityIdentity::m_pClassInfo
_IDENTITY_IDX_OFF     = 0x10    # CEntityIdentity::m_Idx
_CLASSINFO_NAME1_OFF  = 0xE0    # class_info -> intermediate ptr (updated for CS2 build 14153+)
_CLASSINFO_NAME2_OFF  = 0x08    # intermediate -> name string ptr
_SMOKE_DID_EFFECT_OFF = 0x11B8  # fallback: C_SmokeGrenadeProjectile::m_bDidSmokeEffect (may be stale)


class CS2Reader:
    def __init__(self, mem: Memory, offsets: dict):
        self.mem = mem
        self._g  = offsets.get("globals", {})
        self._f  = offsets.get("fields",  {})

        self.client_base      = 0
        self.entity_system    = 0
        self.gvars            = 0
        self.lpc_addr         = 0   # address of local player controller pointer
        self._bomb_own_idx    = 0   # persisted across frames
        self._last_local_team = 0   # last known valid team (2=T, 3=CT)

    def _off(self, cls: str, field: str, default: int = 0) -> int:
        return self._f.get(cls, {}).get(field, default)

    # ── setup ─────────────────────────────────────────────────────────────────
    def setup(self) -> bool:
        self.client_base = self.mem.get_module_base("client.dll")
        if not self.client_base:
            log.error("client.dll not loaded — is CS2 running?")
            return False

        dw_list  = self._g.get("dwEntityList", 0)
        dw_gvars = self._g.get("dwGlobalVars",  0)
        dw_lpc   = self._g.get("dwLocalPlayerController", 0)

        if not dw_list or not dw_gvars or not dw_lpc:
            log.error("critical global offsets missing from cs2-dumper cache — delete offsets_cache.json and retry")
            return False

        log.debug("dwEntityList=0x%X  dwGlobalVars=0x%X  dwLocalPlayerController=0x%X",
                  dw_list, dw_gvars, dw_lpc)

        raw_list = self.mem._read(self.client_base + dw_list, 8)
        self.entity_system = self.mem.ptr(self.client_base + dw_list)
        self.gvars         = self.mem.ptr(self.client_base + dw_gvars)
        self.lpc_addr      = self.client_base + dw_lpc

        if not self.entity_system:
            log.warning("entity system ptr is null (raw bytes @ dwEntityList: %s) — CS2 may be in main menu or offsets are stale",
                        raw_list.hex())
            return False

        log.info("client.dll    @ 0x%016X", self.client_base)
        log.info("entity system @ 0x%016X", self.entity_system)
        log.info("global vars   @ 0x%016X", self.gvars)
        return True

    # ── entity list ───────────────────────────────────────────────────────────
    def _entity_ptr(self, idx: int, chunk_cache: dict) -> int:
        chunk = idx >> 9
        if chunk not in chunk_cache:
            chunk_cache[chunk] = self.mem.ptr(self.entity_system + 8 * chunk + 16)
        entry_list = chunk_cache[chunk]
        if not entry_list:
            return 0
        return self.mem.ptr(entry_list + 112 * (idx & 0x1FF))

    def _entity_by_handle(self, handle: int, chunk_cache: dict) -> int:
        if handle == INVALID_EHANDLE:
            return 0
        return self._entity_ptr(handle & ENT_ENTRY_MASK, chunk_cache)

    def _class_name(self, entity_ptr: int) -> str:
        """Resolve the schema class name for an entity."""
        off_pent = self._off("CEntityInstance", "m_pEntity", 0x10)
        identity = self.mem.ptr(entity_ptr + off_pent)
        if not identity:
            return ""
        # Check validity via m_Idx
        m_idx = self.mem.u32(identity + _IDENTITY_IDX_OFF)
        if (m_idx & ENT_ENTRY_MASK) == ENT_ENTRY_MASK:
            return ""
        class_info = self.mem.ptr(identity + _IDENTITY_CLASS_OFF)
        if not class_info:
            return ""
        unk1 = self.mem.ptr(class_info + _CLASSINFO_NAME1_OFF)
        if not unk1:
            return ""
        unk2 = self.mem.ptr(unk1 + _CLASSINFO_NAME2_OFF)
        if not unk2:
            return ""
        # unk2 is an MSVC std::string object — size at +0x10, data at ptr(unk2) if >= 16
        sz = self.mem.u32(unk2 + 0x10)
        if sz == 0 or sz > 256:
            return ""
        if sz < 16:
            return self.mem.cstring(unk2)
        heap = self.mem.ptr(unk2)
        return self.mem.cstring(heap) if heap else ""

    # ── scene origin ──────────────────────────────────────────────────────────
    def _origin(self, entity_ptr: int) -> tuple[float, float, float]:
        off_node   = self._off("C_BaseEntity", "m_pGameSceneNode")
        off_origin = self._off("CGameSceneNode", "m_vecAbsOrigin")
        if not off_node or not off_origin:
            return 0.0, 0.0, 0.0
        node = self.mem.ptr(entity_ptr + off_node)
        if not node:
            return 0.0, 0.0, 0.0
        base = node + off_origin
        return self.mem.f32(base), self.mem.f32(base + 4), self.mem.f32(base + 8)

    # ── weapons ───────────────────────────────────────────────────────────────
    def _read_weapons(self, pawn_ptr: int, chunk_cache: dict) -> dict:
        weapons = {"m_primary": "", "m_secondary": "", "m_active": "",
                   "m_melee": [], "m_utilities": []}

        off_wsvc    = self._off("C_BasePlayerPawn",    "m_pWeaponServices")
        off_my_wpns = self._off("CPlayer_WeaponServices", "m_hMyWeapons")
        off_active  = self._off("CPlayer_WeaponServices", "m_hActiveWeapon")
        off_subid   = self._off("C_BaseEntity",           "m_nSubclassID")
        off_wtype   = self._off("CCSWeaponBaseVData",     "m_WeaponType")
        off_wname   = self._off("CCSWeaponBaseVData",     "m_szName")

        if not all([off_wsvc, off_my_wpns, off_subid, off_wtype, off_wname]):
            return weapons

        wsvc = self.mem.ptr(pawn_ptr + off_wsvc)
        if not wsvc:
            return weapons

        # CNetworkUtlVectorBase: m_size (u32 @ +0x00), m_elements (ptr @ +0x08)
        vec      = wsvc + off_my_wpns
        w_size   = self.mem.u32(vec)
        w_elems  = self.mem.ptr(vec + 0x08)

        if w_elems and 0 < w_size < 64:
            for i in range(w_size):
                w_handle = self.mem.i32(w_elems + i * 4)
                if w_handle == -1:
                    continue
                w_ptr = self._entity_by_handle(w_handle & ENT_ENTRY_MASK, chunk_cache)
                if not w_ptr:
                    continue
                wdata = self.mem.ptr(w_ptr + off_subid + 0x08)
                if not wdata:
                    continue
                w_type = self.mem.u32(wdata + off_wtype)
                wname  = self.mem.string_field(wdata + off_wname)
                if not wname:
                    continue
                if wname.startswith("weapon_"):
                    wname = wname[7:]
                if w_type in _PRIMARY_TYPES:
                    weapons["m_primary"] = wname
                elif w_type == _PISTOL_TYPE:
                    weapons["m_secondary"] = wname
                elif w_type in _MELEE_TYPES and wname not in weapons["m_melee"]:
                    weapons["m_melee"].append(wname)
                elif w_type == _GRENADE_TYPE and wname not in weapons["m_utilities"]:
                    weapons["m_utilities"].append(wname)

        # Active weapon
        if off_active:
            ah = self.mem.u32(wsvc + off_active)
            if ah != INVALID_EHANDLE:
                aw_ptr = self._entity_by_handle(ah, chunk_cache)
                if aw_ptr:
                    wdata = self.mem.ptr(aw_ptr + off_subid + 0x08)
                    if wdata:
                        aname = self.mem.string_field(wdata + off_wname)
                        if aname.startswith("weapon_"):
                            aname = aname[7:]
                        weapons["m_active"] = aname

        return weapons

    # ── main collect loop ─────────────────────────────────────────────────────
    def collect(self) -> dict | None:
        # Re-read entity_system every frame — CS2 can update this pointer
        # during map loads or round resets.  Caching it in setup() causes all
        # entity reads to silently return 0 if the pointer moves.
        dw_list = self._g.get("dwEntityList", 0)
        if dw_list:
            es = self.mem.ptr(self.client_base + dw_list)
            if es:
                self.entity_system = es
        if not self.entity_system:
            return None

        # Refresh global vars pointer for the same reason
        dw_gvars = self._g.get("dwGlobalVars", 0)
        if dw_gvars:
            gv = self.mem.ptr(self.client_base + dw_gvars)
            if gv:
                self.gvars = gv

        lpc = self.mem.ptr(self.lpc_addr)
        if not lpc:
            return None

        off_team = self._off("C_BaseEntity", "m_iTeamNum")
        local_team = self.mem.u32(lpc + off_team) if off_team else 0

        # Keep broadcasting with the last known team during brief transitions
        # (half-time swap, round restart) so the webapp doesn't freeze.
        if local_team in (2, 3):
            self._last_local_team = local_team
        elif hasattr(self, "_last_local_team") and self._last_local_team:
            local_team = self._last_local_team
        else:
            return None

        map_name = self._get_map_name()

        off_health   = self._off("C_BaseEntity",         "m_iHealth")
        off_team_    = self._off("C_BaseEntity",         "m_iTeamNum")
        off_owner    = self._off("C_BaseEntity",         "m_hOwnerEntity")
        off_hpawn    = self._off("CBasePlayerController","m_hPawn")
        off_steam    = self._off("CBasePlayerController","m_steamID")
        off_name     = self._off("CCSPlayerController",  "m_sSanitizedPlayerName")
        off_money_s  = self._off("CCSPlayerController",  "m_pInGameMoneyServices")
        off_color    = self._off("CCSPlayerController",  "m_iCompTeammateColor")
        off_armor    = self._off("C_CSPlayerPawn",       "m_ArmorValue")
        off_eye      = self._off("C_CSPlayerPawn",       "m_angEyeAngles")
        off_isvc     = self._off("C_BasePlayerPawn",     "m_pItemServices")
        off_defuser  = self._off("CCSPlayer_ItemServices","m_bHasDefuser")
        off_helmet   = self._off("CCSPlayer_ItemServices","m_bHasHelmet")
        off_money    = self._off("CCSPlayerController_InGameMoneyServices","m_iAccount")
        off_ticking  = self._off("C_PlantedC4",          "m_bBombTicking")
        off_blow     = self._off("C_PlantedC4",          "m_flC4Blow")
        off_defused  = self._off("C_PlantedC4",          "m_bBombDefused")
        off_defusing = self._off("C_PlantedC4",          "m_bBeingDefused")
        off_defuse_t = self._off("C_PlantedC4",          "m_flDefuseCountDown")
        off_subid    = self._off("C_BaseEntity",          "m_nSubclassID")
        off_wtype    = self._off("CCSWeaponBaseVData",    "m_WeaponType")
        off_wname    = self._off("CCSWeaponBaseVData",    "m_szName")

        curtime = self.mem.f32(self.gvars + _CURTIME_OFF) if self.gvars else 0.0

        players   = []
        bomb_data = {}
        grenades  = []
        dropped   = []
        bomb_own_idx = self._bomb_own_idx

        chunk_cache: dict[int, int] = {}

        for idx in range(1024):
            ent = self._entity_ptr(idx, chunk_cache)
            if not ent:
                continue

            cls = self._class_name(ent)
            if not cls:
                continue

            # ── player controller ─────────────────────────────────────────────
            if cls == "CCSPlayerController":
                team = self.mem.u32(ent + off_team_) if off_team_ else 0
                if team not in (2, 3):
                    continue

                h_pawn = self.mem.u32(ent + off_hpawn) if off_hpawn else INVALID_EHANDLE
                if h_pawn == INVALID_EHANDLE:
                    continue
                pawn = self._entity_by_handle(h_pawn, chunk_cache)
                if not pawn:
                    continue

                health  = self.mem.i32(pawn + off_health) if off_health else 0
                is_dead = health <= 0

                x, y, z = self._origin(pawn)
                eye_yaw  = self.mem.f32(pawn + off_eye + 4) if off_eye else 0.0
                steam_id = self.mem.u64(ent + off_steam) if off_steam else 0
                armor    = self.mem.i32(pawn + off_armor) if off_armor else 0

                pname = self.mem.string_field(ent + off_name) if off_name else ""

                color = 5
                if off_color:
                    c = self.mem.u32(ent + off_color)
                    color = c if c != 0xFFFFFFFF else 5

                money = 0
                if off_money_s and off_money:
                    ms = self.mem.ptr(ent + off_money_s)
                    if ms:
                        money = self.mem.i32(ms + off_money)

                has_helmet  = False
                has_defuser = False
                if off_isvc:
                    isvc = self.mem.ptr(pawn + off_isvc)
                    if isvc:
                        has_helmet  = self.mem.bool8(isvc + off_helmet)  if off_helmet  else False
                        has_defuser = self.mem.bool8(isvc + off_defuser) if off_defuser else False

                weapons  = self._read_weapons(pawn, chunk_cache)
                has_bomb = False
                if team == 2 and not is_dead and bomb_own_idx:
                    has_bomb = bomb_own_idx == ((h_pawn & ENT_ENTRY_MASK) & 0xFFFF)

                players.append({
                    "m_idx":        idx,
                    "m_name":       pname,
                    "m_color":      color,
                    "m_team":       team,
                    "m_health":     health,
                    "m_is_dead":    is_dead,
                    "m_model_name": "",
                    "m_steam_id":   str(steam_id),
                    "m_money":      money,
                    "m_armor":      armor,
                    "m_position":   {"x": x, "y": y, "z": z},
                    "m_eye_angle":  eye_yaw,
                    "m_has_helmet": has_helmet,
                    "m_has_defuser":has_defuser,
                    "m_weapons":    weapons,
                    "m_has_bomb":   has_bomb,
                })

            # ── carried c4 ───────────────────────────────────────────────────
            elif cls == "C_C4":
                if off_owner:
                    h_own = self.mem.u32(ent + off_owner)
                    self._bomb_own_idx = h_own & 0xFFFF
                    bomb_own_idx       = self._bomb_own_idx
                x, y, _ = self._origin(ent)
                if x or y:
                    bomb_data = {"x": x, "y": y}

            # ── planted c4 ───────────────────────────────────────────────────
            elif cls == "C_PlantedC4":
                if off_ticking and self.mem.bool8(ent + off_ticking):
                    blow_time = (self.mem.f32(ent + off_blow) - curtime) if off_blow else 0.0
                    if blow_time > 0:
                        x, y, _ = self._origin(ent)
                        bomb_data = {
                            "x":             x,
                            "y":             y,
                            "m_blow_time":   blow_time,
                            "m_is_defused":  self.mem.bool8(ent + off_defused)  if off_defused  else False,
                            "m_is_defusing": self.mem.bool8(ent + off_defusing) if off_defusing else False,
                            "m_defuse_time": (self.mem.f32(ent + off_defuse_t) - curtime) if off_defuse_t else 0.0,
                        }

            # ── grenades ─────────────────────────────────────────────────────
            elif cls in _GRENADE_CLASSES:
                deployed = False

                if cls == "C_SmokeGrenadeProjectile":
                    off_stb = self._off("C_SmokeGrenadeProjectile", "m_nSmokeEffectTickBegin")
                    if off_stb:
                        deployed = self.mem.u32(ent + off_stb) > 0
                    else:
                        deployed = self.mem.bool8(ent + _SMOKE_DID_EFFECT_OFF)
                    # Always show: small dot while in-flight, full circle when deployed

                elif cls == "C_Inferno":
                    off_post = self._off("C_Inferno", "m_bInPostEffectTime")
                    if off_post and self.mem.bool8(ent + off_post):
                        continue  # fire ended naturally or smoked out
                    deployed = True

                elif cls == "C_MolotovProjectile":
                    deployed = False  # show as in-flight dot only

                x, y, z = self._origin(ent)
                if x or y:
                    entry = {"x": x, "y": y, "z": z,
                             "type":     _GRENADE_CLASS_TO_TYPE[cls],
                             "deployed": deployed}

                    # For C_Inferno, attach individual fire positions for accurate shape
                    if cls == "C_Inferno":
                        off_fpos = self._off("C_Inferno", "m_firePositions")
                        off_fcnt = self._off("C_Inferno", "m_nFireCount")
                        if off_fpos and off_fcnt:
                            fire_count = min(self.mem.u32(ent + off_fcnt), 64)
                            if fire_count > 0:
                                raw = self.mem._read(ent + off_fpos, fire_count * 12)
                                fire_pts = []
                                for fi in range(fire_count):
                                    fx, fy = struct.unpack_from("<ff", raw, fi * 12)
                                    fire_pts.append({"x": fx, "y": fy})
                                entry["firePts"] = fire_pts

                    grenades.append(entry)

            # ── dropped weapons ───────────────────────────────────────────────
            elif off_subid and off_wtype and off_wname and off_owner:
                owner = self.mem.u32(ent + off_owner)
                if owner == INVALID_EHANDLE:
                    wdata = self.mem.ptr(ent + off_subid + 0x08)
                    if wdata:
                        wtype = self.mem.u32(wdata + off_wtype)
                        if wtype in {*_PRIMARY_TYPES, _PISTOL_TYPE, 8, _GRENADE_TYPE}:  # 8=zeus
                            wname = self.mem.string_field(wdata + off_wname)
                            if wname and wname.startswith("weapon_"):
                                x, y, _ = self._origin(ent)
                                if x or y:
                                    dropped.append({"x": x, "y": y, "name": wname[7:]})

        # View/projection matrix for world-to-screen ESP projection
        view_matrix = []
        dw_vm = self._g.get("dwViewMatrix", 0)
        if dw_vm:
            raw = self.mem._read(self.client_base + dw_vm, 64)  # 16 × float32
            view_matrix = list(struct.unpack_from("<16f", raw))

        return {
            "m_local_team":   local_team,
            "m_players":      players,
            "m_bomb":         bomb_data,
            "m_grenades":     grenades,
            "m_dropped":      dropped,
            "m_map":          map_name,
            "m_view_matrix":  view_matrix,
        }

    def _get_map_name(self) -> str:
        if not self.gvars:
            return "invalid"
        char_ptr = self.mem.ptr(self.gvars + _MAP_NAME_OFF)
        name = self.mem.cstring(char_ptr) if char_ptr else ""
        if not name or "<empty>" in name or len(name) < 3:
            return "invalid"
        # Strip path prefix (e.g. "maps/de_dust2" → "de_dust2")
        if "/" in name:
            name = name.rsplit("/", 1)[-1]
        # Strip file extension (e.g. "de_dust2.vpk" → "de_dust2")
        if "." in name:
            name = name.rsplit(".", 1)[0]
        return name


# ── config ───────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    default = {"m_use_localhost": True, "m_local_ip": "localhost", "m_public_ip": ""}
    CONFIG_FILE.write_text(json.dumps(default, indent=2))
    return default


# ── connected browser clients ─────────────────────────────────────────────────
_clients: set = set()


async def _ws_handler(websocket):
    _clients.add(websocket)
    log.info("browser connected  (%d total)", len(_clients))
    try:
        await websocket.wait_closed()
    finally:
        _clients.discard(websocket)
        log.info("browser disconnected (%d total)", len(_clients))


async def _broadcast(payload: str):
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(payload)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


def _static_path() -> str | None:
    if getattr(sys, "frozen", False):
        p = Path(sys._MEIPASS) / "webapp_dist"
    else:
        p = Path(__file__).parent.parent / "webapp" / "dist"
    if p.exists():
        return str(p)
    log.warning("static dir not found at %s — HTTP server disabled (run npm run build)", p)
    return None


def _maps_cache_path() -> Path:
    """Writable directory where auto-extracted map data is stored."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "maps_cache"
    return Path(__file__).parent.parent / "webapp" / "public" / "data"


# ── map extractor ─────────────────────────────────────────────────────────────
class MapExtractor:
    """Reads CS2 overview files and extracts map data on demand."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cs2_dir   = self._find_cs2()
        self._seen: set[str] = set()
        if self.cs2_dir:
            log.info("map extractor: CS2 found at %s", self.cs2_dir)
        else:
            log.warning("map extractor: CS2 install not found — auto-extraction disabled")

    def _find_cs2(self) -> Path | None:
        candidates = []
        # 1. Steam registry (most reliable)
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (r"SOFTWARE\Valve\Steam", r"SOFTWARE\WOW6432Node\Valve\Steam"):
                    try:
                        key = winreg.OpenKey(hive, sub)
                        steam = Path(winreg.QueryValueEx(key, "InstallPath")[0])
                        candidates.append(steam / "steamapps/common/Counter-Strike Global Offensive")
                    except Exception:
                        pass
        except Exception:
            pass
        # 2. Common default locations
        for drive in ("C", "D", "E"):
            candidates += [
                Path(f"{drive}:/Program Files (x86)/Steam/steamapps/common/Counter-Strike Global Offensive"),
                Path(f"{drive}:/Program Files/Steam/steamapps/common/Counter-Strike Global Offensive"),
                Path(f"{drive}:/Steam/steamapps/common/Counter-Strike Global Offensive"),
            ]
        for p in candidates:
            if (p / "game" / "csgo").exists():
                return p
        return None

    def _parse_overview(self, txt: Path) -> dict | None:
        """Extract pos_x, pos_y, scale from a CS2 KeyValues overview .txt file."""
        import re
        try:
            content = txt.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        px = re.search(r'"pos_x"\s+"([^"]+)"', content)
        py = re.search(r'"pos_y"\s+"([^"]+)"', content)
        sc = re.search(r'"scale"\s+"([^"]+)"', content)
        if not (px and py and sc):
            return None
        try:
            return {"x": float(px.group(1)), "y": float(py.group(1)), "scale": float(sc.group(1))}
        except ValueError:
            return None

    def ensure(self, map_name: str) -> bool:
        """
        Extract map data from CS2 if not already in cache.
        Returns True if data is available (pre-existing or just extracted).
        """
        if map_name in self._seen or map_name == "invalid":
            return map_name in self._seen

        out = self.cache_dir / map_name
        if (out / "data.json").exists() and (out / "radar.png").exists():
            self._seen.add(map_name)
            return True

        if not self.cs2_dir:
            return False

        ov_dir  = self.cs2_dir / "game" / "csgo" / "resource" / "overviews"
        txt_src = ov_dir / f"{map_name}.txt"
        png_src = ov_dir / f"{map_name}_radar.png"

        if not txt_src.exists():
            log.warning("map extractor: no overview txt for %s at %s", map_name, txt_src)
            return False
        if not png_src.exists():
            log.warning("map extractor: no radar png for %s at %s", map_name, png_src)
            return False

        data = self._parse_overview(txt_src)
        if not data:
            log.warning("map extractor: failed to parse overview for %s", map_name)
            return False

        import shutil
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "data.json").write_text(json.dumps(data))
            shutil.copy(png_src, out / "radar.png")
            shutil.copy(png_src, out / "background.png")   # no blur — acceptable fallback
            (out / "callouts.json").write_text(json.dumps({"map": map_name, "callouts": []}))
        except Exception as exc:
            log.error("map extractor: write failed for %s: %s", map_name, exc)
            return False

        log.info("map extractor: extracted %s  (x=%.0f y=%.0f scale=%.2f)",
                 map_name, data["x"], data["y"], data["scale"])
        self._seen.add(map_name)
        return True


def _start_http(static_dir: str, maps_cache: Path):
    """
    Serve the webapp with a dual-directory handler:
      /data/<map>/* → maps_cache first, then static_dir fallback
      everything else → static_dir
    """
    import posixpath, urllib.parse, mimetypes

    _static = static_dir
    _maps   = maps_cache

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def log_error(self, *_): pass

        def _resolve(self, url_path: str) -> Path | None:
            p = urllib.parse.unquote(url_path).split("?")[0]
            p = posixpath.normpath(p).lstrip("/")
            parts = p.split("/")

            # /data/<map>/... → check maps_cache first
            if len(parts) >= 2 and parts[0] == "data":
                candidate = _maps / Path(*parts[1:])
                if candidate.exists() and candidate.is_file():
                    return candidate

            # fallback to static dir
            candidate = Path(_static) / Path(*parts) if parts else Path(_static)
            if candidate.is_file():
                return candidate
            # try index.html for SPA routes
            index = Path(_static) / "index.html"
            return index if index.exists() else None

        def do_GET(self):
            path = self._resolve(self.path)
            if path is None or not path.exists():
                self.send_error(404)
                return
            mime, _ = mimetypes.guess_type(str(path))
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.HTTPServer(("0.0.0.0", HTTP_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("HTTP  -> http://0.0.0.0:%d  (maps_cache=%s)", HTTP_PORT, _maps)


def _ensure_firewall_rules():
    """
    Ensure Windows Firewall allows inbound traffic on both ports.
    Uses program-based rules (most reliable) + port-based rules as backup.
    Force-deletes then re-adds so locale/state issues never cause a stale rule.
    """
    import subprocess

    exe = sys.executable  # path to the running exe (or python.exe in dev)

    def _netsh(*args):
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", *args],
            capture_output=True, text=True, encoding="utf-8", errors="ignore"
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    # 1. Program-based rule — allows all ports used by this exe
    prog_rule = "CS2Radar-Program"
    _netsh("delete", "rule", f"name={prog_rule}")  # remove stale copy if any
    ok, out = _netsh(
        "add", "rule", f"name={prog_rule}",
        "dir=in", "action=allow", "protocol=TCP",
        f"program={exe}", "enable=yes",
    )
    if ok:
        log.info("firewall: program rule added for %s", exe)
    else:
        log.warning("firewall: program rule failed: %s", out)

    # 2. Port-based rules as fallback
    for rule_name, port in [("CS2Radar-WS", WS_PORT), ("CS2Radar-HTTP", HTTP_PORT)]:
        _netsh("delete", "rule", f"name={rule_name}")
        ok, out = _netsh(
            "add", "rule", f"name={rule_name}",
            "dir=in", "action=allow", "protocol=TCP",
            f"localport={port}", "enable=yes",
        )
        if ok:
            log.info("firewall: port rule added  %s -> %d", rule_name, port)
        else:
            log.warning("firewall: port rule failed %s: %s", rule_name, out)


# ── main async loop ───────────────────────────────────────────────────────────
async def _run_async():
    load_config()
    _ensure_firewall_rules()
    offsets = load_offsets()

    mem    = Memory()
    reader: CS2Reader | None = None
    _last_waiting_log = 0.0
    loop = asyncio.get_event_loop()

    # host=None → bind all interfaces (IPv4 + IPv6) so WebView2's ::1 also works
    async with websockets.serve(_ws_handler, None, WS_PORT):
        log.info("WS    -> ws://localhost:%d/cs2_webradar", WS_PORT)

        static_dir = _static_path()
        maps_cache = _maps_cache_path()
        extractor  = MapExtractor(maps_cache)
        if static_dir:
            try:
                _start_http(static_dir, maps_cache)
            except OSError as e:
                log.warning("HTTP server could not start on port %d (%s) — Vite dev server already running there", HTTP_PORT, e)
            webbrowser.open(f"http://localhost:{HTTP_PORT}")

        _last_map = None

        _setup_failures = 0
        _did_local_scan  = False

        while True:
            # ── ensure CS2 is open ────────────────────────────────────────────
            if not mem.handle:
                pid = await loop.run_in_executor(None, lambda: mem.find_pid("cs2.exe"))
                if not pid:
                    log.info("waiting for cs2.exe to start...")
                    await asyncio.sleep(3)
                    continue
                if not mem.open(pid):
                    log.error("OpenProcess failed — run as administrator")
                    await asyncio.sleep(3)
                    continue
                log.info("found cs2.exe  pid=%d", pid)
                reader = None
                _setup_failures = 0

            # ── detect stale handle (CS2 restarted without triggering OSError) ─
            # After several consecutive setup failures, verify the process is
            # still alive. ReadProcessMemory on a dead handle returns zeros
            # silently, which looks identical to "entity system not ready".
            if reader is None and _setup_failures > 0 and _setup_failures % 10 == 0:
                live_pid = await loop.run_in_executor(None, lambda: mem.find_pid("cs2.exe"))
                if live_pid and live_pid != mem.pid:
                    log.warning("CS2 restarted (old pid=%d new pid=%d) — reopening handle",
                                mem.pid, live_pid)
                    mem.close()
                    continue   # re-enter loop to reopen handle

            # ── ensure reader is initialised ──────────────────────────────────
            if reader is None:
                r = CS2Reader(mem, offsets)
                ok = await loop.run_in_executor(None, r.setup)
                if not ok:
                    _setup_failures += 1
                    # After ~5s of null entity-system, scan client.dll for updated offsets
                    if not _did_local_scan and _setup_failures >= 5:
                        log.warning("offsets may be stale — scanning client.dll for updated values...")
                        patched = await loop.run_in_executor(None, lambda: _scan_globals_from_dll(offsets))
                        _did_local_scan = True
                        if patched:
                            log.info("offset scan complete — retrying with new values")
                    now = time.time()
                    if now - _last_waiting_log >= 5:
                        log.info("waiting for CS2 to load into a game...")
                        _last_waiting_log = now
                    await asyncio.sleep(1)
                    continue
                _setup_failures = 0
                reader = r
                log.info("reader ready — watching entity list at 10 Hz")

            # ── collect + broadcast ───────────────────────────────────────────
            try:
                data = await loop.run_in_executor(None, reader.collect)
                if data is None:
                    now = time.time()
                    if now - _last_waiting_log >= 5:
                        log.info("in CS2 but not in an active match (team=spectator/none)")
                        _last_waiting_log = now
                else:
                    map_name = data.get("m_map", "invalid")
                    if map_name != _last_map and map_name != "invalid":
                        _last_map = map_name
                        await loop.run_in_executor(None, extractor.ensure, map_name)
                    await _broadcast(json.dumps(data))
            except OSError as exc:
                log.warning("CS2 process lost (%s) — detaching", exc)
                mem.close()
                reader = None
            except Exception as exc:
                log.error("unexpected error in collect/send: %s", exc, exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


def run(overlay: bool = False, esp: bool = False):
    mode = "esp" if esp else ("minimap" if overlay else "browser")
    log.info("mode: %s", mode)

    if overlay or esp:
        # Use the built dist (port 8765) when available; otherwise fall back to
        # the Vite dev server (port 5173) so development runs without a build step.
        base_url = (f"http://localhost:{HTTP_PORT}"
                    if _static_path() is not None
                    else "http://localhost:5173")
        log.info("overlay will load from %s", base_url)

        t = threading.Thread(
            target=lambda: asyncio.run(_run_async()),
            daemon=True, name="radar-backend"
        )
        t.start()
        time.sleep(1.5)

        import overlay as ov
        if esp:
            # Full-screen transparent click-through — CS2 must be Fullscreen Windowed
            ov.start_esp(f"{base_url}?mode=esp")
        else:
            # Small draggable minimap window
            ov.start(f"{base_url}?mode=minimap")

        t.join()
    else:
        asyncio.run(_run_async())


def _pick_mode() -> tuple[bool, bool]:
    """
    Interactive mode selector shown at startup when no CLI flag is passed.
    Returns (overlay, esp).
    """
    print("\n" + "=" * 50)
    print("  CS2 Radar — Select Mode")
    print("=" * 50)
    print("  1  Normal  — browser radar (open in any browser)")
    print("  2  Overlay — small draggable minimap on screen")
    print("  3  ESP     — full-screen player boxes through walls")
    print("=" * 50)

    while True:
        try:
            choice = input("  Enter 1 / 2 / 3: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"

        if choice == "1":
            print("  -> Normal mode\n")
            return False, False
        elif choice == "2":
            print("  -> Minimap overlay  (drag the bar to reposition)\n")
            return True, False
        elif choice == "3":
            print("  -> ESP overlay  (CS2 must be in Fullscreen Windowed)\n")
            return False, True
        else:
            print("  Please enter 1, 2, or 3.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="CS2 Radar")
    ap.add_argument("--normal",  action="store_true", help="Browser radar mode (default)")
    ap.add_argument("--overlay", action="store_true", help="Small draggable minimap overlay")
    ap.add_argument("--esp",     action="store_true", help="Full-screen ESP overlay")
    args = ap.parse_args()

    if args.esp:
        _overlay, _esp = False, True
    elif args.overlay:
        _overlay, _esp = True, False
    elif args.normal:
        _overlay, _esp = False, False
    else:
        # No flag passed — show interactive menu
        _overlay, _esp = _pick_mode()

    run(overlay=_overlay, esp=_esp)
