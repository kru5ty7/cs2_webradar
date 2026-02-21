#include <windows.h>
#include <wrl.h>
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
#define HOTKEY_OPACITY_DN VK_F6  // F6 = decrease opacity
#define HOTKEY_OPACITY_UP VK_F7  // F7 = increase opacity
#define HOTKEY_MOVE      VK_F8   // F8 = toggle draggable
#define HOTKEY_TOGGLE    VK_F9   // F9 = show/hide
#define HOTKEY_EXIT      VK_F10  // F10 = exit overlay
#define POLL_INTERVAL    2000    // ms between Vite readiness checks
#define TOPMOST_INTERVAL 500    // ms between topmost re-assertions
#define TOPMOST_TIMER_ID 101
#define OPACITY_STEP     0.10f   // 10% per keypress
#define OPACITY_MIN      0.20f   // minimum 20%
#define OPACITY_MAX      1.00f   // maximum 100%

static HWND               g_hwnd       = nullptr;
static bool               g_dragging   = false;
static POINT              g_dragStart  = {};
static bool               g_visible    = true;
static HANDLE             g_viteProcess = nullptr;
static float              g_opacity    = 1.0f;  // current overlay opacity

ComPtr<ICoreWebView2Controller> g_controller;
ComPtr<ICoreWebView2>           g_webview;

// ── Forward declarations ─────────────────────────────────────
LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);
void InitWebView(HWND hwnd);
bool IsViteReady();
void LaunchStartBat();
bool IsWebView2RuntimeInstalled();
void ApplyOpacity();
void ToggleDragMode();

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

// ── Apply opacity to the WebView2 page content ───────────────
void ApplyOpacity()
{
    if (!g_webview.Get()) return;

    wchar_t script[128];
    swprintf_s(script, L"document.documentElement.style.opacity = '%0.2f';", g_opacity);
    g_webview->ExecuteScript(script, nullptr);
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
            ToggleDragMode();
        }
        else if (wp == 3) // F6 decrease opacity
        {
            g_opacity -= OPACITY_STEP;
            if (g_opacity < OPACITY_MIN) g_opacity = OPACITY_MIN;
            ApplyOpacity();
        }
        else if (wp == 4) // F7 increase opacity
        {
            g_opacity += OPACITY_STEP;
            if (g_opacity > OPACITY_MAX) g_opacity = OPACITY_MAX;
            ApplyOpacity();
        }
        else if (wp == 5) // F10 exit
        {
            DestroyWindow(hwnd);
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
        if (g_controller.Get())
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

    case WM_NCHITTEST:
        // Click-through: return HTTRANSPARENT when not in drag mode
        // This is needed because WS_EX_TRANSPARENT alone doesn't provide
        // click-through with WS_EX_NOREDIRECTIONBITMAP
        if (!g_dragging)
            return HTTRANSPARENT;
        return DefWindowProc(hwnd, msg, wp, lp);
    }
    return DefWindowProc(hwnd, msg, wp, lp);
}

// ── Toggle drag/reposition mode ──────────────────────────────
void ToggleDragMode()
{
    g_dragging = !g_dragging;

    LONG_PTR exStyle = GetWindowLongPtr(g_hwnd, GWL_EXSTYLE);
    LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
    if (g_dragging)
    {
        exStyle &= ~WS_EX_TRANSPARENT;
        style |= WS_THICKFRAME;
    }
    else
    {
        exStyle |= WS_EX_TRANSPARENT;
        style &= ~WS_THICKFRAME;
    }
    SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, exStyle);
    SetWindowLongPtr(g_hwnd, GWL_STYLE, style);

    // Enable/disable WebView2 child windows for click-through
    HWND child = GetWindow(g_hwnd, GW_CHILD);
    while (child)
    {
        EnableWindow(child, g_dragging ? TRUE : FALSE);
        child = GetWindow(child, GW_HWNDNEXT);
    }

    SetWindowPos(g_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED);
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
            ComPtr<ICoreWebView2Controller2> ctrl2;
            if (SUCCEEDED(g_controller.As(&ctrl2)) && ctrl2)
            {
                COREWEBVIEW2_COLOR col = { 0, 0, 0, 0 }; // fully transparent
                ctrl2->put_DefaultBackgroundColor(col);
            }

            // ── Disable browser chrome / context menus ───────
            ComPtr<ICoreWebView2Settings> settings;
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

            // ── Listen for messages from the webapp ──────────
            EventRegistrationToken token;
            g_webview->add_WebMessageReceived(
                Callback<ICoreWebView2WebMessageReceivedEventHandler>(
                    [](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
                LPWSTR msg = nullptr;
                args->TryGetWebMessageAsString(&msg);
                if (msg)
                {
                    if (wcscmp(msg, L"toggle-drag") == 0)
                    {
                        ToggleDragMode();
                    }
                    CoTaskMemFree(msg);
                }
                return S_OK;
            }).Get(), &token);

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

// ── Topmost re-assertion timer ────────────────────────────────
// Games (including CS2 in borderless windowed) can demote HWND_TOPMOST.
// This timer periodically re-asserts the overlay's z-order, similar to
// how Discord Overlay and GeForce Experience maintain their position.
// NOTE: This does NOT work with true exclusive fullscreen — CS2 must
//       be set to "Fullscreen Windowed" in video settings.
void CALLBACK TopmostTimerProc(HWND hwnd, UINT, UINT_PTR, DWORD)
{
    if (g_visible)
    {
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOSENDCHANGING);
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

    // Create transparent, topmost, click-through window — no taskbar entry
    // WS_EX_NOREDIRECTIONBITMAP lets WebView2's DirectComposition render 
    // properly (WS_EX_LAYERED breaks WebView2 dynamic content)
    g_hwnd = CreateWindowExW(
        WS_EX_TOPMOST              |  // always on top
        WS_EX_NOREDIRECTIONBITMAP  |  // proper DirectComposition transparency
        WS_EX_TRANSPARENT          |  // click-through by default
        WS_EX_TOOLWINDOW           |  // no taskbar button
        WS_EX_NOACTIVATE,             // never steals focus from CS2
        L"CS2RadarOverlay",
        L"CS2 Radar",
        WS_POPUP,                      // no border, no title bar
        20, 100,                       // initial position: top-left, moved down
        OVERLAY_W, OVERLAY_H,
        nullptr, nullptr, hInst, nullptr);

    // Assert topmost position
    SetWindowPos(g_hwnd, HWND_TOPMOST, 20, 100,
        OVERLAY_W, OVERLAY_H,
        SWP_SHOWWINDOW | SWP_NOACTIVATE);

    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);

    // Register global hotkeys (work even when CS2 has focus)
    RegisterHotKey(g_hwnd, 1, 0, HOTKEY_TOGGLE);    // F9
    RegisterHotKey(g_hwnd, 2, 0, HOTKEY_MOVE);      // F8
    RegisterHotKey(g_hwnd, 3, 0, HOTKEY_OPACITY_DN); // F6
    RegisterHotKey(g_hwnd, 4, 0, HOTKEY_OPACITY_UP); // F7
    RegisterHotKey(g_hwnd, 5, 0, HOTKEY_EXIT);       // F10

    // Periodically re-assert topmost so we stay above the game window
    SetTimer(g_hwnd, TOPMOST_TIMER_ID, TOPMOST_INTERVAL, TopmostTimerProc);

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
    UnregisterHotKey(g_hwnd, 3);
    UnregisterHotKey(g_hwnd, 4);
    UnregisterHotKey(g_hwnd, 5);

    CoUninitialize();
    return 0;
}
