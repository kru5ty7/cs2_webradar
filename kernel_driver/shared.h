/*
 * shared.h — structures and constants shared between the kernel driver
 *            and the usermode Python client (via ctypes).
 *
 * Both sides must agree on the exact layout of READ_REQUEST and the
 * IOCTL code, otherwise DeviceIoControl will pass garbage.
 */

#pragma once
#include <ntdef.h>  // ULONG64, BYTE, etc.

// ── Buffer size ───────────────────────────────────────────────────────────────
// Largest single read we support.  Main.py's biggest read is 64 bytes
// (the 4×4 view matrix).  8 KB gives plenty of headroom for future use.
#define MAX_READ_BUFFER 8192

// ── The request struct ────────────────────────────────────────────────────────
// Python fills in ProcessId / Address / Size before calling DeviceIoControl.
// The driver fills in Status and Buffer before returning.
//
// __declspec(align(8)) ensures the compiler won't add unexpected padding,
// which would break the Python ctypes mirror struct.
typedef struct _READ_REQUEST {
    ULONG64 ProcessId;          // IN:  PID of CS2 (tasklist | findstr cs2)
    ULONG64 Address;            // IN:  virtual address to read inside CS2
    ULONG64 Size;               // IN:  how many bytes to copy (≤ MAX_READ_BUFFER)
    ULONG64 Status;             // OUT: NTSTATUS code (0 = STATUS_SUCCESS)
    BYTE    Buffer[MAX_READ_BUFFER]; // OUT: the copied bytes
} READ_REQUEST, *PREAD_REQUEST;

// ── IOCTL code ────────────────────────────────────────────────────────────────
// CTL_CODE macro packs four fields into a single 32-bit control code:
//   DeviceType  – FILE_DEVICE_UNKNOWN (0x22) for custom drivers
//   Function    – our custom opcode; 0x800+ is the user-defined range
//   Method      – METHOD_BUFFERED: Windows copies input/output through a
//                 kernel buffer so we don't have to touch user pointers
//   Access      – FILE_ANY_ACCESS: any process can call this IOCTL
#define IOCTL_READ_PROCESS_MEMORY \
    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)
