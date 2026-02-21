#include <windows.h>
#include <wrl.h>
#include <wil/com.h>
#include "WebView2.h"
#include <winhttp.h>
#include <string>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "winhttp.lib")

using namespace Microsoft::WRL;

// ── Config ────────────────────────────────────────────────────
#define RADAR_URL       L"http://localhost:5173"
#define OVERLAY_W       300
#define OVERLAY_H       300
#define HOTKEY_TOGGLE   VK_F9   // F9 = show/hide
#define HOTKEY_MOVE     VK_F8   // F8 = toggle draggable
#define POLL_INTERVAL   2000    // ms between Vite readiness checks

static HWND               g_hwnd       = nullptr;
static bool               g_dragging   = false;
static POINT              g_dragStart  = {};
static bool               g_visible    = true;
static HANDLE             g_viteProcess = nullptr;

wil::com_ptr<ICoreWebView2Controller> g_controller;
wil::com_ptr<ICoreWebView2>           g_webview;

// ── Forward declarations ─────────────────────────────────────
LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);
void InitWebView(HWND hwnd);
bool IsViteReady();
void LaunchStartBat();
bool IsWebView2RuntimeInstalled();

// ── Check if WebView2 runtime is installed ───────────────────
bool IsWebView2RuntimeInstalled()
{
    LPWSTR version = nullptr;
    HRESULT hr = GetAvailableCoreWebView2BrowserVersionString(nullptr, &version);
    if (SUCCEEDED(hr) && version != nullptr)
    {
        CoTaskMemFree(version);
        return true;
    }
    return false;
}

// ── Poll localhost:5173 to check if Vite is ready ────────────
bool IsViteReady()
{
    HINTERNET hSession = WinHttpOpen(L"CS2RadarOverlay/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return false;

    HINTERNET hConnect = WinHttpConnect(hSession, L"localhost",
        5173, 0);
    if (!hConnect)
    {
        WinHttpCloseHandle(hSession);
        return false;
    }

    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"GET", L"/",
        nullptr, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest)
    {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    BOOL result = WinHttpSendRequest(hRequest,
        WINHTTP_NO_ADDITIONAL_HEADERS, 0,
        WINHTTP_NO_REQUEST_DATA, 0, 0, 0);

    bool ready = false;
    if (result)
    {
        result = WinHttpReceiveResponse(hRequest, nullptr);
        if (result)
            ready = true;
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return ready;
}

// ── Launch start.bat to start Vite dev server ────────────────
void LaunchStartBat()
{
    // Get the directory of the current executable
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);

    // Navigate up from overlay/ to the project root
    std::wstring exeDir(exePath);
    size_t lastSlash = exeDir.rfind(L'\\');
    if (lastSlash != std::wstring::npos)
        exeDir = exeDir.substr(0, lastSlash);

    // Go up one more directory (from overlay/Release/ or overlay/ to project root)
    lastSlash = exeDir.rfind(L'\\');
    if (lastSlash != std::wstring::npos)
        exeDir = exeDir.substr(0, lastSlash);

    // If we're in a Release/Debug subfolder, go up one more
    std::wstring dirName = exeDir.substr(exeDir.rfind(L'\\') + 1);
    if (dirName == L"overlay" || dirName == L"Release" || dirName == L"Debug")
    {
        lastSlash = exeDir.rfind(L'\\');
        if (lastSlash != std::wstring::npos)
            exeDir = exeDir.substr(0, lastSlash);
    }

    std::wstring webappDir = exeDir + L"\\webapp";
    std::wstring cmdLine = L"cmd /c npm run dev";

    STARTUPINFOW si = { sizeof(si) };
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_MINIMIZE;

    PROCESS_INFORMATION pi = {};

    if (CreateProcessW(nullptr,
        const_cast<LPWSTR>(cmdLine.c_str()),
        nullptr, nullptr, FALSE,
        CREATE_NEW_CONSOLE,
        nullptr,
        webappDir.c_str(),
        &si, &pi))
    {
        g_viteProcess = pi.hProcess;
        CloseHandle(pi.hThread);
    }
}

// ── Window procedure ─────────────────────────────────────────
LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg)
    {
    case WM_HOTKEY:
        if (wp == 1) // F9 toggle visibility
        {
            g_visible = !g_visible;
            ShowWindow(hwnd, g_visible ? SW_SHOW : SW_HIDE);
            if (g_visible)
            {
                SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
            }
        }
        else if (wp == 2) // F8 toggle drag mode
        {
            g_dragging = !g_dragging;

            // When drag mode is active, remove WS_EX_TRANSPARENT so we can receive clicks
            LONG_PTR exStyle = GetWindowLongPtr(hwnd, GWL_EXSTYLE);
            if (g_dragging)
                exStyle &= ~WS_EX_TRANSPARENT;
            else
                exStyle |= WS_EX_TRANSPARENT;

            SetWindowLongPtr(hwnd, GWL_EXSTYLE, exStyle);

            // Make window semi-opaque when draggable to give visual feedback
            SetLayeredWindowAttributes(hwnd, 0,
                g_dragging ? 220 : 255,
                LWA_ALPHA);
        }
        break;

    case WM_LBUTTONDOWN:
        if (g_dragging)
        {
            SetCapture(hwnd);
            GetCursorPos(&g_dragStart);
            RECT r;
            GetWindowRect(hwnd, &r);
            g_dragStart.x -= r.left;
            g_dragStart.y -= r.top;
        }
        break;

    case WM_MOUSEMOVE:
        if (g_dragging && (wp & MK_LBUTTON))
        {
            POINT p;
            GetCursorPos(&p);
            SetWindowPos(hwnd, HWND_TOPMOST,
                p.x - g_dragStart.x,
                p.y - g_dragStart.y,
                0, 0, SWP_NOSIZE | SWP_NOACTIVATE);
        }
        break;

    case WM_LBUTTONUP:
        ReleaseCapture();
        break;

    case WM_SIZE:
        if (g_controller)
        {
            RECT bounds;
            GetClientRect(hwnd, &bounds);
            g_controller->put_Bounds(bounds);
        }
        break;

    case WM_DESTROY:
        // Terminate Vite process if we started it
        if (g_viteProcess)
        {
            TerminateProcess(g_viteProcess, 0);
            CloseHandle(g_viteProcess);
        }
        PostQuitMessage(0);
        break;
    }
    return DefWindowProc(hwnd, msg, wp, lp);
}

// ── WebView2 init ─────────────────────────────────────────────
void InitWebView(HWND hwnd)
{
    CreateCoreWebView2EnvironmentWithOptions(
        nullptr, nullptr, nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [hwnd](HRESULT, ICoreWebView2Environment* env) -> HRESULT {

        env->CreateCoreWebView2Controller(hwnd,
            Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                [hwnd](HRESULT, ICoreWebView2Controller* ctrl) -> HRESULT {

            g_controller = ctrl;
            g_controller->get_CoreWebView2(&g_webview);

            // ── Make background transparent ──────────────────
            auto ctrl2 = g_controller.try_query<ICoreWebView2Controller2>();
            if (ctrl2)
            {
                COREWEBVIEW2_COLOR col = { 0, 0, 0, 0 }; // fully transparent
                ctrl2->put_DefaultBackgroundColor(col);
            }

            // ── Disable browser chrome / context menus ───────
            wil::com_ptr<ICoreWebView2Settings> settings;
            g_webview->get_Settings(&settings);
            settings->put_AreDefaultContextMenusEnabled(FALSE);
            settings->put_AreDevToolsEnabled(FALSE);
            settings->put_IsStatusBarEnabled(FALSE);

            // ── Size the webview to fill the window ──────────
            RECT bounds;
            GetClientRect(hwnd, &bounds);
            g_controller->put_Bounds(bounds);
            g_controller->put_IsVisible(TRUE);

            // ── Navigate to the radar URL ────────────────────
            g_webview->Navigate(RADAR_URL);

            return S_OK;
        }).Get());
        return S_OK;
    }).Get());
}

// ── Vite readiness polling (runs on a timer) ─────────────────
void CALLBACK VitePollTimerProc(HWND hwnd, UINT, UINT_PTR timerId, DWORD)
{
    if (IsViteReady())
    {
        KillTimer(hwnd, timerId);
        InitWebView(hwnd);
    }
}

// ── WinMain ───────────────────────────────────────────────────
int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int)
{
    // Check for WebView2 runtime
    if (!IsWebView2RuntimeInstalled())
    {
        MessageBoxW(nullptr,
            L"Microsoft WebView2 Runtime is required but not installed.\n\n"
            L"Please download and install it from:\n"
            L"https://developer.microsoft.com/microsoft-edge/webview2",
            L"CS2 Radar Overlay - Missing Dependency",
            MB_OK | MB_ICONERROR);
        return 1;
    }

    // Initialize COM
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    // Register window class
    WNDCLASSEXW wc = { sizeof(wc) };
    wc.lpfnWndProc  = WndProc;
    wc.hInstance     = hInst;
    wc.lpszClassName = L"CS2RadarOverlay";
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    RegisterClassExW(&wc);

    // Create layered, transparent, topmost window — no taskbar entry
    g_hwnd = CreateWindowExW(
        WS_EX_TOPMOST     |    // always on top
        WS_EX_LAYERED     |    // enables per-pixel alpha
        WS_EX_TRANSPARENT |    // click-through by default
        WS_EX_TOOLWINDOW  |    // no taskbar button
        WS_EX_NOACTIVATE,      // never steals focus from CS2
        L"CS2RadarOverlay",
        L"CS2 Radar",
        WS_POPUP,               // no border, no title bar
        20, 20,                  // initial position: top-left
        OVERLAY_W, OVERLAY_H,
        nullptr, nullptr, hInst, nullptr);

    // Set full opacity (WebView2 handles its own transparency)
    SetLayeredWindowAttributes(g_hwnd, 0, 255, LWA_ALPHA);

    // Assert topmost position
    SetWindowPos(g_hwnd, HWND_TOPMOST, 20, 20,
        OVERLAY_W, OVERLAY_H,
        SWP_SHOWWINDOW | SWP_NOACTIVATE);

    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);

    // Register global hotkeys (work even when CS2 has focus)
    RegisterHotKey(g_hwnd, 1, 0, HOTKEY_TOGGLE); // F9
    RegisterHotKey(g_hwnd, 2, 0, HOTKEY_MOVE);   // F8

    // Launch start.bat (Vite dev server)
    LaunchStartBat();

    // If Vite is already running, init WebView immediately;
    // otherwise poll every 2 seconds until it's ready
    if (IsViteReady())
    {
        InitWebView(g_hwnd);
    }
    else
    {
        SetTimer(g_hwnd, 100, POLL_INTERVAL, VitePollTimerProc);
    }

    // Message loop
    MSG msg;
    while (GetMessage(&msg, nullptr, 0, 0))
    {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    UnregisterHotKey(g_hwnd, 1);
    UnregisterHotKey(g_hwnd, 2);

    CoUninitialize();
    return 0;
}
