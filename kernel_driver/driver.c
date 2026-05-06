/*
 * driver.c — CS2 Radar kernel-mode memory reader
 *
 * HOW IT FITS TOGETHER
 * ────────────────────
 * Normal Windows programs run in "Ring 3" (user-mode).  They can only read
 * another process's memory by asking the OS via ReadProcessMemory(), which
 * requires a valid process handle.  CS2's Trusted Mode blocks that handle.
 *
 * This driver runs in "Ring 0" (kernel-mode) — the same privilege level as
 * Windows itself.  At Ring 0 we can call MmCopyVirtualMemory() directly,
 * which copies memory between any two processes without needing a handle
 * that anti-cheat could block.
 *
 * DATA FLOW
 * ─────────
 *   Python app
 *     └─ DeviceIoControl("\\\\.\\CS2Radar", IOCTL_READ_PROCESS_MEMORY, request)
 *           └─ Windows IRP machinery
 *                 └─ DispatchControl()  ← this file
 *                       └─ MmCopyVirtualMemory(cs2_process → our_process)
 *                             └─ bytes returned in request.Buffer
 *
 * BUILD (Visual Studio + WDK)
 * ───────────────────────────
 * 1. New Project → "Kernel Mode Driver, Empty (KMDF)"
 * 2. Add driver.c and shared.h to the project
 * 3. Project Properties → Driver Settings → Target OS: Windows 10+
 * 4. Build → produces driver.sys
 *
 * LOADING (test machine / VM — requires test-signing mode)
 * ────────────────────────────────────────────────────────
 *   bcdedit /set testsigning on   (run once, then reboot)
 *   sc create CS2Radar type= kernel binPath= "C:\path\to\driver.sys"
 *   sc start  CS2Radar
 *   sc stop   CS2Radar            (when done)
 *   sc delete CS2Radar
 */

#include <ntddk.h>   // core kernel headers: NTSTATUS, PEPROCESS, IoCreateDevice…
#include <wdm.h>     // IRP, IO_STACK_LOCATION, IoCompleteRequest…
#include "shared.h"  // READ_REQUEST, IOCTL_READ_PROCESS_MEMORY

// ── MmCopyVirtualMemory declaration ──────────────────────────────────────────
//
// This function IS exported by ntoskrnl.exe but is NOT in the public WDK
// headers (Microsoft kept it undocumented on purpose).  We declare it here
// so the linker can find it at load time.  At runtime Windows resolves it
// from ntoskrnl.exe's export table — the same mechanism as a normal DLL.
//
// What it does: copies `BufferSize` bytes from SourceAddress (inside
// SourceProcess's virtual address space) into TargetAddress (inside
// TargetProcess's virtual address space).  Because we're in kernel-mode
// we can name any process — no handle, no permission check.
NTKERNELAPI NTSTATUS MmCopyVirtualMemory(
    PEPROCESS  SourceProcess,   // process we're reading FROM (CS2)
    PVOID      SourceAddress,   // address inside that process
    PEPROCESS  TargetProcess,   // process we're reading INTO (our driver)
    PVOID      TargetAddress,   // where to put the bytes
    SIZE_T     BufferSize,      // how many bytes
    KPROCESSOR_MODE PreviousMode, // KernelMode — skip user-mode safety checks
    PSIZE_T    ReturnSize       // OUT: how many bytes were actually copied
);

// ── Device / symlink names ────────────────────────────────────────────────────
//
// Kernel objects live in the NT namespace (\Device\…).
// User-mode processes use the Win32 namespace (\\.\…) which maps via symlinks.
//
//   NT path    \Device\CS2Radar       ← the actual device object
//   Win32 path \\.\CS2Radar           ← what Python opens with CreateFile
//   Symlink    \DosDevices\CS2Radar   ← bridges the two namespaces
#define DEVICE_NAME  L"\\Device\\CS2Radar"
#define SYMLINK_NAME L"\\DosDevices\\CS2Radar"

// Forward declarations (defined below, referenced in DriverEntry)
DRIVER_UNLOAD     DriverUnload;
DRIVER_DISPATCH   DispatchCreateClose;
DRIVER_DISPATCH   DispatchControl;

// ─────────────────────────────────────────────────────────────────────────────
// DriverEntry — the kernel equivalent of main()
//
// Called once by Windows when the driver is loaded (sc start).
// Must:  1. register dispatch routines
//        2. create the device object
//        3. create the symbolic link so usermode can open it
// ─────────────────────────────────────────────────────────────────────────────
NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNREFERENCED_PARAMETER(RegistryPath);  // we don't use registry settings here

    DbgPrint("[CS2Radar] DriverEntry called\n");  // visible in DebugView (Sysinternals)

    NTSTATUS       status;
    PDEVICE_OBJECT deviceObject = NULL;
    UNICODE_STRING deviceName, symlinkName;

    // Convert the wide-char string literals to UNICODE_STRING structs,
    // which is what all NT kernel APIs expect.
    RtlInitUnicodeString(&deviceName,  DEVICE_NAME);
    RtlInitUnicodeString(&symlinkName, SYMLINK_NAME);

    // ── Register dispatch routines ──────────────────────────────────────────
    // Windows routes every I/O request (open, close, ioctl, read, …) to the
    // driver through the MajorFunction table.  We only need three slots:
    //   IRP_MJ_CREATE        — Python calls CreateFile("\\\\.\\CS2Radar")
    //   IRP_MJ_CLOSE         — Python calls CloseHandle()
    //   IRP_MJ_DEVICE_CONTROL— Python calls DeviceIoControl()
    DriverObject->DriverUnload                          = DriverUnload;
    DriverObject->MajorFunction[IRP_MJ_CREATE]          = DispatchCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLOSE]           = DispatchCreateClose;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL]  = DispatchControl;

    // ── Create the device object ────────────────────────────────────────────
    // IoCreateDevice allocates a DEVICE_OBJECT in kernel memory and registers
    // it in the NT namespace at \Device\CS2Radar.
    //
    // FILE_DEVICE_UNKNOWN — generic type for custom (non-hardware) drivers
    // 0                   — no extra device extension bytes needed
    // FALSE               — not an "exclusive" device (multiple opens allowed)
    status = IoCreateDevice(
        DriverObject,
        0,
        &deviceName,
        FILE_DEVICE_UNKNOWN,
        FILE_DEVICE_SECURE_OPEN,
        FALSE,
        &deviceObject
    );
    if (!NT_SUCCESS(status)) {
        DbgPrint("[CS2Radar] IoCreateDevice failed: 0x%X\n", status);
        return status;
    }

    // METHOD_BUFFERED (set in the IOCTL macro) means Windows allocates a
    // kernel buffer, copies usermode input into it, and copies the output
    // back after we complete the IRP.  This flag tells the I/O manager we
    // want that buffering behaviour.
    deviceObject->Flags |= DO_BUFFERED_IO;
    deviceObject->Flags &= ~DO_DEVICE_INITIALIZING;  // mark device as ready

    // ── Create the symbolic link ────────────────────────────────────────────
    // Without this, Python's CreateFile("\\\\.\\CS2Radar") would fail with
    // "file not found" because Win32 only sees \DosDevices\, not \Device\.
    status = IoCreateSymbolicLink(&symlinkName, &deviceName);
    if (!NT_SUCCESS(status)) {
        DbgPrint("[CS2Radar] IoCreateSymbolicLink failed: 0x%X\n", status);
        IoDeleteDevice(deviceObject);
        return status;
    }

    DbgPrint("[CS2Radar] Driver loaded — \\Device\\CS2Radar ready\n");
    return STATUS_SUCCESS;
}

// ─────────────────────────────────────────────────────────────────────────────
// DriverUnload — cleanup when sc stop is called
//
// Must undo everything DriverEntry created, in reverse order.
// Forgetting to delete the symlink or device causes a memory leak that
// persists until next reboot.
// ─────────────────────────────────────────────────────────────────────────────
VOID DriverUnload(PDRIVER_OBJECT DriverObject)
{
    UNICODE_STRING symlinkName;
    RtlInitUnicodeString(&symlinkName, SYMLINK_NAME);

    // Remove the Win32 → NT symlink first, then the device object itself
    IoDeleteSymbolicLink(&symlinkName);
    IoDeleteDevice(DriverObject->DeviceObject);

    DbgPrint("[CS2Radar] Driver unloaded\n");
}

// ─────────────────────────────────────────────────────────────────────────────
// DispatchCreateClose — handles IRP_MJ_CREATE and IRP_MJ_CLOSE
//
// Python's CreateFile() generates a CREATE IRP; CloseHandle() generates
// a CLOSE IRP.  We don't need to do anything special — just complete them
// with success so Python can get a valid handle.
// ─────────────────────────────────────────────────────────────────────────────
NTSTATUS DispatchCreateClose(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);

    // Every IRP must be completed — tell Windows we handled it successfully
    Irp->IoStatus.Status      = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);  // IO_NO_INCREMENT: no priority boost
    return STATUS_SUCCESS;
}

// ─────────────────────────────────────────────────────────────────────────────
// DispatchControl — handles IRP_MJ_DEVICE_CONTROL (the main work)
//
// This fires when Python calls DeviceIoControl().
// With METHOD_BUFFERED the I/O manager has already:
//   • copied Python's input struct → Irp->AssociatedIrp.SystemBuffer
//   • allocated output space in the same buffer
// We just cast that buffer to READ_REQUEST and fill in the output fields.
// ─────────────────────────────────────────────────────────────────────────────
NTSTATUS DispatchControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);

    // IoGetCurrentIrpStackLocation gives us the per-driver parameters for
    // this IRP, including which IOCTL code was called and buffer sizes.
    PIO_STACK_LOCATION stack  = IoGetCurrentIrpStackLocation(Irp);
    ULONG ioControlCode       = stack->Parameters.DeviceIoControl.IoControlCode;
    ULONG inputBufferLength   = stack->Parameters.DeviceIoControl.InputBufferLength;

    NTSTATUS status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;

    // ── Validate IOCTL code ─────────────────────────────────────────────────
    if (ioControlCode != IOCTL_READ_PROCESS_MEMORY) {
        // Someone called us with an unknown IOCTL — reject it
        status = STATUS_INVALID_DEVICE_REQUEST;
        goto Complete;
    }

    // ── Validate input size ─────────────────────────────────────────────────
    if (inputBufferLength < sizeof(READ_REQUEST)) {
        // Buffer is too small to hold a valid READ_REQUEST — reject
        status = STATUS_BUFFER_TOO_SMALL;
        goto Complete;
    }

    // ── Get the request struct ──────────────────────────────────────────────
    // With METHOD_BUFFERED, SystemBuffer is a kernel-mode copy of what Python
    // passed as lpInBuffer.  Safe to access directly — no need for ProbeFor*.
    PREAD_REQUEST req = (PREAD_REQUEST)Irp->AssociatedIrp.SystemBuffer;

    // ── Validate requested read size ────────────────────────────────────────
    if (req->Size == 0 || req->Size > MAX_READ_BUFFER) {
        status = STATUS_INVALID_PARAMETER;
        goto Complete;
    }

    // ── Look up the CS2 process ─────────────────────────────────────────────
    // PsLookupProcessByProcessId converts a numeric PID into a PEPROCESS
    // pointer — the kernel's internal representation of a process.
    //
    // This increments the reference count on the EPROCESS structure.
    // We MUST call ObDereferenceObject() when done, or the process object
    // leaks even after CS2 exits.
    PEPROCESS targetProcess = NULL;
    status = PsLookupProcessByProcessId((HANDLE)req->ProcessId, &targetProcess);
    if (!NT_SUCCESS(status)) {
        DbgPrint("[CS2Radar] PsLookupProcessByProcessId(%llu) failed: 0x%X\n",
                 req->ProcessId, status);
        req->Status = (ULONG64)status;
        Irp->IoStatus.Information = sizeof(READ_REQUEST);
        goto Complete;
    }

    // ── Copy the memory ─────────────────────────────────────────────────────
    // MmCopyVirtualMemory reads from CS2's virtual address space and writes
    // into our kernel buffer.  Because we're already in kernel-mode we use
    // KernelMode — this skips the user-mode address range check that would
    // reject kernel addresses when called from Ring 3.
    SIZE_T bytesCopied = 0;
    status = MmCopyVirtualMemory(
        targetProcess,          // source: CS2 process
        (PVOID)req->Address,    // source address in CS2's VA space
        PsGetCurrentProcess(),  // destination: our driver's process context
        (PVOID)req->Buffer,     // destination: the output buffer in our struct
        (SIZE_T)req->Size,      // how many bytes
        KernelMode,             // skip usermode range validation
        &bytesCopied            // actual bytes copied (may be less on page fault)
    );

    // Release our reference on the EPROCESS — must match PsLookupProcessByProcessId
    ObDereferenceObject(targetProcess);

    if (!NT_SUCCESS(status)) {
        DbgPrint("[CS2Radar] MmCopyVirtualMemory failed: 0x%X\n", status);
    }

    // Write the NTSTATUS back so Python can distinguish success from errors
    req->Status = (ULONG64)status;

    // Tell the I/O manager how many bytes to copy back to Python's output buffer
    Irp->IoStatus.Information = sizeof(READ_REQUEST);

Complete:
    Irp->IoStatus.Status = status;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}
