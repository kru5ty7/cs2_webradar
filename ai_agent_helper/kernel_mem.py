"""
kernel_mem.py — Python client for the CS2Radar kernel driver.

Replaces the ctypes ReadProcessMemory calls in main.py with DeviceIoControl
calls to our kernel driver.  The kernel driver then uses MmCopyVirtualMemory
(Ring 0) to read CS2 memory without needing a process handle.

HOW WINDOWS I/O WORKS (simplified)
────────────────────────────────────
User-mode (Ring 3)             Kernel-mode (Ring 0)
─────────────────              ────────────────────
CreateFile("\\.\CS2Radar")  →  DriverEntry created this device
DeviceIoControl(handle, …)  →  DispatchControl() in driver.c
  sends READ_REQUEST struct  →  driver calls MmCopyVirtualMemory
  receives filled Buffer     ←  driver writes bytes into Buffer

METHOD_BUFFERED (set in the IOCTL macro) means Windows handles the copy
automatically — we don't need to pin memory or deal with MDLs.

USAGE
─────
    mem = KernelMemory(cs2_pid)
    four_bytes = mem._read(address, 4)
    as_int     = struct.unpack_from('<i', four_bytes)[0]

    # Drop-in replacement for the Memory class in main.py:
    #   old: self.mem = Memory(cs2_pid)
    #   new: self.mem = KernelMemory(cs2_pid)
"""

import ctypes
import ctypes.wintypes as wt
import struct
import logging

log = logging.getLogger("radar")

# ── Constants from the Windows SDK ────────────────────────────────────────────
# These mirror the #defines in <winioctl.h> and <winbase.h>

GENERIC_READ    = 0x80000000  # open for reading
GENERIC_WRITE   = 0x40000000  # open for writing (needed for DeviceIoControl)
OPEN_EXISTING   = 3           # fail if device doesn't exist
INVALID_HANDLE  = wt.HANDLE(-1).value  # CreateFile returns this on failure

# IOCTL code — must exactly match the CTL_CODE() in shared.h:
#   FILE_DEVICE_UNKNOWN = 0x22
#   Function = 0x800
#   METHOD_BUFFERED = 0
#   FILE_ANY_ACCESS = 0
#
# CTL_CODE formula:
#   ((DeviceType) << 16) | ((Access) << 14) | ((Function) << 2) | (Method)
#   = (0x22 << 16) | (0 << 14) | (0x800 << 2) | 0
#   = 0x00220000 | 0x00002000
#   = 0x00222000
IOCTL_READ_PROCESS_MEMORY = 0x00222000

MAX_READ_BUFFER = 8192  # must match shared.h

# ── Kernel32 function bindings ────────────────────────────────────────────────
# ctypes lets us call Windows DLL functions directly from Python.
# We annotate argtypes/restype so ctypes knows how to marshal the arguments.

_k32 = ctypes.windll.kernel32  # load kernel32.dll (already in every process)

# CreateFileW — opens a file or device by name
# Returns a HANDLE (opaque integer) or INVALID_HANDLE_VALUE on failure
_k32.CreateFileW.restype  = wt.HANDLE
_k32.CreateFileW.argtypes = [
    wt.LPCWSTR,   # lpFileName          — e.g. r"\\.\CS2Radar"
    wt.DWORD,     # dwDesiredAccess     — GENERIC_READ | GENERIC_WRITE
    wt.DWORD,     # dwShareMode         — 0 = exclusive
    ctypes.c_void_p,  # lpSecurityAttributes — NULL
    wt.DWORD,     # dwCreationDisposition — OPEN_EXISTING
    wt.DWORD,     # dwFlagsAndAttributes  — 0
    wt.HANDLE,    # hTemplateFile         — NULL
]

# DeviceIoControl — sends an IOCTL to a driver and gets output back
# Returns non-zero on success
_k32.DeviceIoControl.restype  = wt.BOOL
_k32.DeviceIoControl.argtypes = [
    wt.HANDLE,         # hDevice       — from CreateFileW
    wt.DWORD,          # dwIoControlCode — our IOCTL_READ_PROCESS_MEMORY
    ctypes.c_void_p,   # lpInBuffer    — pointer to our READ_REQUEST
    wt.DWORD,          # nInBufferSize — sizeof(READ_REQUEST)
    ctypes.c_void_p,   # lpOutBuffer   — same buffer (METHOD_BUFFERED reuses it)
    wt.DWORD,          # nOutBufferSize
    ctypes.POINTER(wt.DWORD),  # lpBytesReturned — how many bytes driver wrote
    ctypes.c_void_p,   # lpOverlapped  — NULL (synchronous)
]

# CloseHandle — releases the kernel object reference
_k32.CloseHandle.restype  = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]

# GetLastError — Windows error code when a call fails
_k32.GetLastError.restype  = wt.DWORD
_k32.GetLastError.argtypes = []


# ── Struct mirror of READ_REQUEST from shared.h ───────────────────────────────
# ctypes.Structure lays out fields in C-compatible order with no hidden padding
# (as long as we don't mix types that need different alignments unexpectedly).
# The layout MUST match the C struct byte-for-byte.
class _ReadRequest(ctypes.Structure):
    _fields_ = [
        # IN fields — Python fills these before calling DeviceIoControl
        ("ProcessId", ctypes.c_uint64),          # PID of CS2
        ("Address",   ctypes.c_uint64),           # virtual address to read
        ("Size",      ctypes.c_uint64),            # bytes to read
        # OUT fields — driver fills these and Windows copies back to Python
        ("Status",    ctypes.c_uint64),            # NTSTATUS (0 = success)
        ("Buffer",    ctypes.c_uint8 * MAX_READ_BUFFER),  # the copied bytes
    ]


class KernelMemory:
    """
    Drop-in replacement for the Memory class in main.py.

    Instead of ReadProcessMemory (blocked by Trusted Mode), every _read()
    call goes through our kernel driver via DeviceIoControl.

    Parameters
    ----------
    pid : int
        Process ID of cs2.exe (same value main.py already finds via
        EnumProcesses / tasklist).
    """

    def __init__(self, pid: int):
        self._pid = pid

        # Open a handle to our driver's device.
        # This is identical to opening a file — the kernel routes it to
        # our DispatchCreateClose() function.
        self._handle = _k32.CreateFileW(
            r"\\.\CS2Radar",          # Win32 name → \DosDevices\CS2Radar symlink → \Device\CS2Radar
            GENERIC_READ | GENERIC_WRITE,
            0,                        # no sharing — only one opener at a time
            None,                     # default security
            OPEN_EXISTING,            # must already exist (driver must be running)
            0,                        # no special flags
            None,                     # no template
        )

        if self._handle == INVALID_HANDLE:
            err = _k32.GetLastError()
            raise RuntimeError(
                f"Cannot open \\.\CS2Radar (error {err}).  "
                f"Is the driver loaded?  Run: sc start CS2Radar"
            )

        log.info("KernelMemory: driver handle opened (PID %d)", pid)

    def _read(self, address: int, size: int) -> bytes:
        """
        Read `size` bytes from CS2's virtual address space at `address`.

        Returns
        -------
        bytes
            The raw bytes at that address, or b'\\x00' * size on failure.
        """
        if size > MAX_READ_BUFFER:
            raise ValueError(f"Requested {size} bytes > MAX_READ_BUFFER {MAX_READ_BUFFER}")

        # Build the request struct in Python-managed memory.
        # ctypes allocates it on the Python heap — no manual malloc needed.
        req = _ReadRequest()
        req.ProcessId = self._pid
        req.Address   = address
        req.Size       = size

        bytes_returned = wt.DWORD(0)
        req_size = ctypes.sizeof(_ReadRequest)

        # Send the request to the driver.
        # METHOD_BUFFERED means Windows:
        #   1. Copies req → kernel buffer  (input)
        #   2. Calls DispatchControl()
        #   3. Copies kernel buffer → req  (output, same memory in this case)
        ok = _k32.DeviceIoControl(
            self._handle,
            IOCTL_READ_PROCESS_MEMORY,
            ctypes.byref(req),    # input buffer
            req_size,
            ctypes.byref(req),    # output buffer (same struct — driver writes back into it)
            req_size,
            ctypes.byref(bytes_returned),
            None,                 # synchronous (no OVERLAPPED)
        )

        if not ok:
            err = _k32.GetLastError()
            log.debug("DeviceIoControl error %d reading 0x%X", err, address)
            return b"\x00" * size

        # req.Status is the NTSTATUS from MmCopyVirtualMemory
        # 0x00000000 = STATUS_SUCCESS
        if req.Status != 0:
            log.debug("Driver NTSTATUS 0x%X reading 0x%X", req.Status, address)
            return b"\x00" * size

        # Extract exactly `size` bytes from the buffer
        return bytes(req.Buffer[:size])

    def close(self):
        """Release the driver handle.  Call when the radar loop exits."""
        if self._handle and self._handle != INVALID_HANDLE:
            _k32.CloseHandle(self._handle)
            self._handle = None
            log.info("KernelMemory: handle closed")

    def __del__(self):
        self.close()


# ── How to wire this into main.py ─────────────────────────────────────────────
#
# In main.py, find the line that creates the Memory object, e.g.:
#
#   self.mem = Memory(pid)          # current — uses ReadProcessMemory
#
# Replace with:
#
#   from kernel_mem import KernelMemory
#   self.mem = KernelMemory(pid)    # new — uses kernel driver
#
# The _read(address, size) interface is identical, so nothing else changes.
#
# To fall back gracefully if the driver isn't loaded:
#
#   try:
#       from kernel_mem import KernelMemory
#       self.mem = KernelMemory(pid)
#       log.info("Using kernel-mode memory reader")
#   except RuntimeError as e:
#       log.warning("Kernel driver unavailable (%s), falling back to ReadProcessMemory", e)
#       self.mem = Memory(pid)
