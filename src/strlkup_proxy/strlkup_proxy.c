/*
 * Strlkup.dll proxy for Star Trek: Armada - runtime fixes for windowed play.
 *
 * The proxy forwards the exports of the original Strlkup.dll (renamed to
 * Strlkup_orig.dll; linker pragmas below keep the original ordinals) and patches
 * selected imports of Armada.exe when it loads:
 *
 *   SetSystemCursor  Armada shows its mouse cursors by replacing the system-wide
 *                    arrow cursor (SetSystemCursor(hcur, OCR_NORMAL)). In a window
 *                    that changes the arrow of the whole desktop, and after a crash
 *                    or a forced exit it stays until the next logon. The replacement
 *                    sets the cursor as the class cursor of the game's own windows.
 *   SetCursorPos     The game moves the mouse only while its window is in the foreground.
 *   RegisterClassA   The game window ("Armada") ends the process on WM_CLOSE instead of
 *                    running on without a window (title bar X, Alt+F4).
 *   LoadLibraryA     Once the GOG DirectX wrapper (ddraw.dll) is loaded, its
 *                    session-wide shared memory name is replaced in memory by a name
 *                    unique to this process (isolate_ddraw_mapping), so other games
 *                    that use the same wrapper cannot crash it, and its SetCursorPos
 *                    and ClipCursor imports get the same foreground guard
 *                    (guard_ddraw_mouse). Wrapper focus calls cannot reactivate a
 *                    background game and bypass the mouse guard.
 *                    The known GOG wrapper also skips its render-target clear
 *                    when GetRenderTarget fails or returns no Surface.
 *   CreateMutexA    The two cursor-rendering Mutexes belong to this process;
 *                    other instances must not share or abandon their ownership.
 *
 * For the GOG 1.2 Armada.exe (checked by code signature) it also redirects the
 * ST3D light destructors so that a destroyed light leaves the render engine's
 * active light list (install_light_fix, see below).
 *
 * It does not change the simulation; the cursor and wrapper fixes work with any
 * Armada.exe build that imports these functions.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <intrin.h>
#ifdef ARMADA_TESTHOOKS
#include <mmdeviceapi.h>
#include <audiopolicy.h>
static void install_test_d3d_trace(HMODULE wrapper);
#endif

#ifndef OCR_NORMAL
#define OCR_NORMAL 32512
#endif

#pragma comment(linker, "/EXPORT:StrLookupCreate=Strlkup_orig.StrLookupCreate,@1")
#pragma comment(linker, "/EXPORT:StrLookupDestroy=Strlkup_orig.StrLookupDestroy,@2")
#pragma comment(linker, "/EXPORT:StrLookupFind=Strlkup_orig.StrLookupFind,@3")
#pragma comment(linker, "/EXPORT:StrLookupFormat=Strlkup_orig.StrLookupFormat,@4")
#pragma comment(linker, "/EXPORT:StrLookup_Global_Object=Strlkup_orig.StrLookup_Global_Object,@5,DATA")

static HCURSOR g_cursor;
static CRITICAL_SECTION g_lock;
static HANDLE g_graphics_offscreen_mutex, g_graphics_onscreen_mutex;
static void *g_cursor_second_wait_return;

/* These Mutexes synchronize the game's own drawing Threads. Their original
   fixed names also join unrelated Armada/Storm3D instances in the same Windows
   Session. A failed second acquire or an abandoned Mutex can then stall every
   instance. Keep intra-process sharing, with no cross-process graphics state. */
static HANDLE WINAPI local_CreateMutexA(LPSECURITY_ATTRIBUTES attributes, BOOL owner, LPCSTR name)
{
    char scoped[96];
    HANDLE mutex;
    BOOL offscreen = name && lstrcmpA(name, "m_mutex_draw_cursor_offscreen") == 0;
    BOOL onscreen = name && lstrcmpA(name, "m_mutex_draw_cursor_onscreen") == 0;
    if (offscreen || onscreen) {
        wsprintfA(scoped, "%s.armada.%lu", name, GetCurrentProcessId());
        name = scoped;
    }
    mutex = CreateMutexA(attributes, owner, name);
    if (mutex) {
        if (offscreen) g_graphics_offscreen_mutex = mutex;
        if (onscreen) g_graphics_onscreen_mutex = mutex;
    }
    return mutex;
}

static DWORD complete_graphics_wait(HANDLE waited, DWORD result, BOOL second_acquire)
{
    DWORD error;
    BOOL known = waited && (waited == g_graphics_offscreen_mutex || waited == g_graphics_onscreen_mutex);
    if (!known || result == WAIT_OBJECT_0)
        return result;
    error = GetLastError();
    if (result == WAIT_ABANDONED)
        ReleaseMutex(waited);
    if (second_acquire && waited == g_graphics_onscreen_mutex && g_graphics_offscreen_mutex)
        ReleaseMutex(g_graphics_offscreen_mutex);
    SetLastError(error);
    return result;
}

static DWORD WINAPI local_WaitForSingleObject(HANDLE waited, DWORD milliseconds)
{
    void *caller = _ReturnAddress();
    DWORD result = WaitForSingleObject(waited, milliseconds);
    return complete_graphics_wait(waited, result,
                                  g_cursor_second_wait_return && caller == g_cursor_second_wait_return);
}

static BOOL CALLBACK set_class_cursor(HWND hwnd, LPARAM lparam)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid == GetCurrentProcessId())
        SetClassLongPtrA(hwnd, GCLP_HCURSOR, (LONG_PTR)lparam);
    return TRUE;
}

static BOOL WINAPI local_SetSystemCursor(HCURSOR hcur, DWORD id)
{
    HCURSOR old;
    POINT pt;
    HWND under;
    DWORD pid = 0;

    if (id != OCR_NORMAL) {
        /* SetSystemCursor takes ownership of hcur; keep that contract. */
        if (hcur)
            DestroyCursor(hcur);
        return TRUE;
    }
    EnterCriticalSection(&g_lock);
    old = g_cursor;
    g_cursor = hcur;
    /* class cursor of every top-level window of this process (game window, shell
       dialogs, wrapper window); DefWindowProc then shows it on WM_SETCURSOR */
    EnumWindows(set_class_cursor, (LPARAM)hcur);
    if (GetCursorPos(&pt) && (under = WindowFromPoint(pt)) != NULL) {
        GetWindowThreadProcessId(under, &pid);
        if (pid == GetCurrentProcessId())
            SetCursor(hcur);
    }
    if (old && old != hcur)
        DestroyCursor(old);
    LeaveCriticalSection(&g_lock);
    return TRUE;
}

/* Replace one import of the main executable. Returns TRUE when patched. */
static BOOL patch_import(HMODULE module, const char *dll, const char *name, void *replacement)
{
    BYTE *base = (BYTE *)module;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *imp;
    BOOL done = FALSE;

    if (!dir.VirtualAddress)
        return FALSE;
    for (imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); imp->Name; imp++) {
        IMAGE_THUNK_DATA *names, *iat;
        if (lstrcmpiA((const char *)(base + imp->Name), dll) != 0)
            continue;
        names = (IMAGE_THUNK_DATA *)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        iat = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; names++, iat++) {
            IMAGE_IMPORT_BY_NAME *ibn;
            DWORD prot;
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
                continue;
            ibn = (IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData);
            if (lstrcmpA((const char *)ibn->Name, name) != 0)
                continue;
            if (VirtualProtect(&iat->u1.Function, sizeof(iat->u1.Function), PAGE_READWRITE, &prot)) {
                iat->u1.Function = (ULONG_PTR)replacement;
                VirtualProtect(&iat->u1.Function, sizeof(iat->u1.Function), prot, &prot);
                done = TRUE;
            }
        }
    }
    return done;
}

static void install_graphics_wait_fix(HMODULE exe)
{
    static const BYTE expected[] = {
        0x8b,0x0d,0xa0,0x4a,0x6d,0x00,0x8b,0x3d,0x64,0x7b,0x6d,0x00,
        0x68,0xe8,0x03,0x00,0x00,0x8b,0x91,0xa4,0x00,0x00,0x00,0x52,
        0xff,0xd7,0x85,0xc0,0x74,0x0c,0x5f,0x5e,0xb8,0x01,0x00,0x00,
        0x00,0x5b,0x8b,0xe5,0x5d,0xc3,0xa1,0xa0,0x4a,0x6d,0x00,0x68,
        0xe8,0x03,0x00,0x00,0x8b,0x88,0xa8,0x00,0x00,0x00,0x51,0xff,
        0xd7,0x85,0xc0,0x74,0x0c,0x5f,0x5e,0xb8,0x01,0x00,0x00,0x00,
        0x5b,0x8b,0xe5,0x5d,0xc3
    };
    const BYTE *site = (const BYTE *)0x583325;
    MEMORY_BASIC_INFORMATION region;
    SIZE_T offset, i;
    if (VirtualQuery(site, &region, sizeof(region)) != sizeof(region) ||
        region.State != MEM_COMMIT || region.Type != MEM_IMAGE || region.AllocationBase != exe ||
        (region.Protect & (PAGE_GUARD | PAGE_NOACCESS)) ||
        !(region.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                            PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)))
        return;
    offset = (SIZE_T)site - (SIZE_T)region.BaseAddress;
    if (offset > region.RegionSize || sizeof(expected) > region.RegionSize - offset)
        return;
    for (i = 0; i < sizeof(expected); i++)
        if (site[i] != expected[i])
            return;
    if (patch_import(exe, "KERNEL32.dll", "WaitForSingleObject", (void *)local_WaitForSingleObject))
        g_cursor_second_wait_return = (void *)0x583362;
}

/*
 * GOG DirectX wrapper (ddraw.dll): it shares its D3D9 device pointer through a named
 * file mapping. The name ("dxfilemap", or "armada1fm" after armada_fix.py) is the
 * same in every process of the Windows session, so a second process that uses the
 * wrapper (another GOG game, or a second Armada instance) makes this process read
 * a foreign pointer and crash in ddraw.dll+0x4160f. Once the wrapper is loaded, its
 * mapping name is replaced in memory with a name unique to this process.
 */
static BOOL g_ddraw_done;

static BOOL same(const BYTE *a, const char *b, SIZE_T n)
{
    SIZE_T i;
    for (i = 0; i < n; i++)
        if (a[i] != (BYTE)b[i])
            return FALSE;
    return TRUE;
}

static BOOL replace_once(BYTE *start, SIZE_T len, const char *old_name, const char *new_name, SIZE_T n)
{
    BYTE *hit = NULL, *p;
    DWORD prot;
    SIZE_T i;
    for (p = start; p + n <= start + len; p++) {
        if (same(p, old_name, n)) {
            if (hit)
                return FALSE;           /* more than one occurrence: leave it alone */
            hit = p;
        }
    }
    if (!hit || !VirtualProtect(hit, n, PAGE_READWRITE, &prot))
        return FALSE;
    for (i = 0; i < n; i++)          /* volatile: keep the compiler from emitting a CRT memcpy */
        ((volatile BYTE *)hit)[i] = (BYTE)new_name[i];
    VirtualProtect(hit, n, prot, &prot);
    return TRUE;
}

static void isolate_ddraw_mapping(void)
{
    HMODULE dd;
    BYTE *base;
    IMAGE_NT_HEADERS *nt;
    IMAGE_SECTION_HEADER *sec;
    char unique[16];
    WORD i;

    if (g_ddraw_done || (dd = GetModuleHandleA("ddraw.dll")) == NULL)
        return;
    g_ddraw_done = TRUE;
    base = (BYTE *)dd;
    nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if (nt->FileHeader.Machine != IMAGE_FILE_MACHINE_I386)
        return;
    wsprintfA(unique, "dxm%06lX", GetCurrentProcessId() & 0xFFFFFF);   /* 9 characters + NUL */
    sec = IMAGE_FIRST_SECTION(nt);
    for (i = 0; i < nt->FileHeader.NumberOfSections; i++, sec++) {
        BYTE *s = base + sec->VirtualAddress;
        SIZE_T len = sec->Misc.VirtualSize;
        if (sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)
            continue;
        if (replace_once(s, len, "dxfilemap", unique, 10) || replace_once(s, len, "armada1fm", unique, 10))
            return;
    }
}

static void guard_ddraw_mouse(void);

static HMODULE WINAPI local_LoadLibraryA(LPCSTR name)
{
    HMODULE h = LoadLibraryA(name);
    EnterCriticalSection(&g_lock);
    isolate_ddraw_mapping();
    guard_ddraw_mouse();
    LeaveCriticalSection(&g_lock);
    return h;
}

/*
 * Window close: the game window procedure (0x442d10 in the GOG 1.2 build) does not handle
 * WM_CLOSE, so DefWindowProc destroys the window and the game keeps running without a
 * window ("Storm3D Error: Invalid window handle" in the log) until it is killed. In
 * fullscreen only Alt+F4 led there; in a window the title bar's X does. The class
 * "Armada" now gets a wrapper procedure that ends the process on WM_CLOSE. In a
 * multiplayer game the other players see this player leave, as after a disconnect.
 */
static WNDPROC g_game_wndproc;
static void release_clip(void);
#ifdef ARMADA_TESTHOOKS
static BOOL g_virtual_input;
static BOOL test_input_event(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);
static LRESULT test_network_event(LPARAM lp);
#endif

static LRESULT CALLBACK game_wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
#ifdef ARMADA_TESTHOOKS
    if (msg == WM_COPYDATA)
        return test_network_event(lp);
    if (test_input_event(hwnd, msg, wp, lp))
        return 0;
    if (g_virtual_input && msg == WM_ACTIVATE && LOWORD(wp) == WA_INACTIVE)
        return 0;  /* logical device stays active; OS focus stays with the user */
#endif
    if (msg == WM_CLOSE) {
        TerminateProcess(GetCurrentProcess(), 0);
        return 0;
    }
    if ((msg == WM_ACTIVATE && LOWORD(wp) == WA_INACTIVE) || (msg == WM_ACTIVATEAPP && !wp))
        release_clip();
    return CallWindowProcA(g_game_wndproc, hwnd, msg, wp, lp);
}

/*
 * Mouse: the game and the GOG DirectX wrapper both move or confine the mouse.
 *  - In a match the game reads the mouse relatively. While its "active" flag (set from
 *    WM_ACTIVATE) is on and the cursor is inside the client area, every input poll puts
 *    the cursor back to the window centre with SetCursorPos (0x477541). The wrapper hooks
 *    that import to scale the coordinates and then calls SetCursorPos itself.
 *  - The wrapper emulates exclusive fullscreen: when the game sets its display mode, and
 *    on several window events, it confines the cursor to the game's client area with
 *    ClipCursor. The clip is global. A game window in the background (a second instance,
 *    or a game started while the user works elsewhere) held the user's mouse in it.
 * The replacements below sit in the imports of Armada.exe and of ddraw.dll. They move or
 * confine the cursor only while a window of this process is the foreground window, and
 * release a clip of this process when the game window is deactivated. The test build
 * never moves, confines or activates anything (test instances run in the background).
 * The real functions are called through pointers from GetProcAddress, because the wrapper
 * may also hook the imports of this DLL.
 */
typedef BOOL (WINAPI *setcursorpos_fn)(int, int);
typedef BOOL (WINAPI *clipcursor_fn)(const RECT *);
typedef BOOL (WINAPI *foreground_fn)(HWND);
typedef HWND (WINAPI *focus_fn)(HWND);
static setcursorpos_fn g_real_SetCursorPos;
static clipcursor_fn g_real_ClipCursor;
static foreground_fn g_real_SetForegroundWindow;
static focus_fn g_real_SetFocus;
static volatile LONG g_clipped;
static BOOL g_ddraw_mouse_done;

static BOOL game_in_front(void)
{
    DWORD pid = 0;
    HWND fg = GetForegroundWindow();
    if (fg)
        GetWindowThreadProcessId(fg, &pid);
    return pid == GetCurrentProcessId();
}

static BOOL WINAPI local_SetCursorPos(int x, int y)
{
#ifdef ARMADA_TESTHOOKS
    (void)x; (void)y;
    return TRUE;
#else
    if (!game_in_front())
        return TRUE;
    return g_real_SetCursorPos(x, y);
#endif
}

static BOOL WINAPI local_ClipCursor(const RECT *r)
{
#ifdef ARMADA_TESTHOOKS
    (void)r;
    return TRUE;
#else
    if (!r) {
        /* release only a clip of this process; a clip of another program stays */
        if (InterlockedExchange(&g_clipped, 0))
            return g_real_ClipCursor(NULL);
        return TRUE;
    }
    if (!game_in_front())
        return TRUE;
    InterlockedExchange(&g_clipped, 1);
    return g_real_ClipCursor(r);
#endif
}

static void release_clip(void)
{
    if (InterlockedExchange(&g_clipped, 0))
        g_real_ClipCursor(NULL);
}

/* A wrapper display change must not reactivate a background game and thereby
   make the foreground-only cursor guard permit movement/confinement again. */
static BOOL WINAPI local_SetForegroundWindow(HWND hwnd)
{
#ifdef ARMADA_TESTHOOKS
    (void)hwnd;
    return TRUE;
#else
    if (!game_in_front())
        return TRUE;
    return g_real_SetForegroundWindow(hwnd);
#endif
}

static HWND WINAPI local_SetFocus(HWND hwnd)
{
#ifdef ARMADA_TESTHOOKS
    (void)hwnd;
    return NULL;
#else
    if (!game_in_front())
        return NULL;
    return g_real_SetFocus(hwnd);
#endif
}

#ifdef ARMADA_TESTHOOKS
/*
 * Test instances stay in the background: they never activate a window or take the
 * focus, so the user's keyboard and mouse stay with the user's programs. Windows are
 * shown without activation and without changing the Z order. The test bed drives the
 * games with posted messages, which need no focus. Real calls go through pointers from
 * GetProcAddress (the wrapper may hook the imports of this DLL).
 */
typedef BOOL (WINAPI *showwindow_fn)(HWND, int);
typedef BOOL (WINAPI *setwindowpos_fn)(HWND, HWND, int, int, int, int, UINT);
typedef HWND (WINAPI *createwindowexa_fn)(DWORD, LPCSTR, LPCSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
typedef HWND (WINAPI *createwindowexw_fn)(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
static showwindow_fn g_real_ShowWindow;
static setwindowpos_fn g_real_SetWindowPos;
static createwindowexa_fn g_real_CreateWindowExA;
static createwindowexw_fn g_real_CreateWindowExW;

static int no_activate(int cmd)
{
    switch (cmd) {
    case SW_SHOWNORMAL: case SW_SHOWMAXIMIZED: case SW_RESTORE: case SW_SHOWDEFAULT:
        return SW_SHOWNOACTIVATE;
    case SW_SHOW:
        return SW_SHOWNA;
    case SW_SHOWMINIMIZED:
        return SW_SHOWMINNOACTIVE;
    }
    return cmd;
}

static BOOL WINAPI local_ShowWindow(HWND hwnd, int cmd)
{
    return g_real_ShowWindow(hwnd, no_activate(cmd));
}

static BOOL WINAPI local_SetWindowPos(HWND hwnd, HWND after, int x, int y, int cx, int cy, UINT flags)
{
    if (flags & SWP_SHOWWINDOW)
        flags |= SWP_NOACTIVATE;
    return g_real_SetWindowPos(hwnd, after, x, y, cx, cy, flags | SWP_NOACTIVATE | SWP_NOZORDER);
}

/* a visible top-level window is created hidden and then shown without activation */
static HWND WINAPI local_CreateWindowExA(DWORD ex, LPCSTR cls, LPCSTR title, DWORD style, int x, int y,
                                         int w, int h, HWND parent, HMENU menu, HINSTANCE inst, LPVOID param)
{
    BOOL show = (style & WS_VISIBLE) && !(style & WS_CHILD);
    HWND r = g_real_CreateWindowExA(ex, cls, title, show ? style & ~WS_VISIBLE : style, x, y, w, h,
                                    parent, menu, inst, param);
    if (r && show)
        g_real_ShowWindow(r, SW_SHOWNOACTIVATE);
    return r;
}

static HWND WINAPI local_CreateWindowExW(DWORD ex, LPCWSTR cls, LPCWSTR title, DWORD style, int x, int y,
                                         int w, int h, HWND parent, HMENU menu, HINSTANCE inst, LPVOID param)
{
    BOOL show = (style & WS_VISIBLE) && !(style & WS_CHILD);
    HWND r = g_real_CreateWindowExW(ex, cls, title, show ? style & ~WS_VISIBLE : style, x, y, w, h,
                                    parent, menu, inst, param);
    if (r && show)
        g_real_ShowWindow(r, SW_SHOWNOACTIVATE);
    return r;
}

static void stay_in_background(HMODULE m)
{
    HMODULE user32 = GetModuleHandleA("user32.dll");
    g_real_ShowWindow = (showwindow_fn)GetProcAddress(user32, "ShowWindow");
    g_real_SetWindowPos = (setwindowpos_fn)GetProcAddress(user32, "SetWindowPos");
    g_real_CreateWindowExA = (createwindowexa_fn)GetProcAddress(user32, "CreateWindowExA");
    g_real_CreateWindowExW = (createwindowexw_fn)GetProcAddress(user32, "CreateWindowExW");
    patch_import(m, "USER32.dll", "ShowWindow", (void *)local_ShowWindow);
    patch_import(m, "USER32.dll", "SetWindowPos", (void *)local_SetWindowPos);
    patch_import(m, "USER32.dll", "SetForegroundWindow", (void *)local_SetForegroundWindow);
    patch_import(m, "USER32.dll", "SetFocus", (void *)local_SetFocus);
    patch_import(m, "USER32.dll", "CreateWindowExA", (void *)local_CreateWindowExA);
    patch_import(m, "USER32.dll", "CreateWindowExW", (void *)local_CreateWindowExW);
}
#endif

/* GOG DirectX 1-7 wrapper 1.1.0.3494, Surface color fill. GetRenderTarget's
   HRESULT was ignored and an uninitialized local was passed to Release. Four
   real late-game crash dumps reached 0x398c1/0x398c3, or the resulting invalid
   virtual call. Windows recorded display-off before the crashes (Direct3D 9 loses
   the device; GetRenderTarget then fails): all six clients of a test match crashed
   eight seconds later. Keep the successful wrapper path and its reference counts;
   skip only the optional GPU clear on failure, then retain the CPU fill.

   The same block exists five times (one color-fill routine per surface slot,
   0x898..0x8a8 of the surface context). Each site gets its own thunk. The thunk
   copies this/index/output for the original stdcall; its return address is the
   site + 5 (the sixth replaced byte is a NOP). On failure it adds the distance to
   the wrapper's own "no GPU clear" target, the destination of the "test ah,0x10;
   jne" right before the block, which install verifies byte for byte. No absolute
   code address is embedded, so ASLR and the allocation address do not affect the
   branch. */
#define RT_SITES      5
#define RT_THUNK_SIZE 64
static const struct { DWORD site, skip; } g_render_target_sites[RT_SITES] = {
    { 0x27bab, 0x27c6c }, { 0x2e3de, 0x2e49f }, { 0x3104e, 0x3110f },
    { 0x33d1e, 0x33ddf }, { 0x398b6, 0x39915 }
};
static HMODULE g_render_target_module;
static BYTE *g_render_target_thunk;

/* the wrapper's own skip branch: "test ah,0x10; jne skip" just before the block */
static BOOL render_target_skip_ok(const BYTE *base, DWORD site, DWORD skip)
{
    const BYTE *block = base + site - 0xa;
    if (block[-2] == 0x75 && block[-5] == 0xf6 && block[-4] == 0xc4 && block[-3] == 0x10)
        return (DWORD)(block - base) + (DWORD)(LONG)(signed char)block[-1] == skip;
    if (block[-6] == 0x0f && block[-5] == 0x85 && block[-9] == 0xf6 && block[-8] == 0xc4 &&
        block[-7] == 0x10)
        return (DWORD)(block - base) + (DWORD)*(const LONG *)(block - 4) == skip;
    return FALSE;
}

static BOOL install_ddraw_render_target_fix(HMODULE module)
{
    static const BYTE expected[] = {
        0x8b,0x11,0x8d,0x44,0x24,0x48,0x50,0x6a,0x00,0x51,
        0xff,0x92,0x98,0x00,0x00,0x00,0x8b,0x44,0x24,0x48,
        0x50,0x8b,0x08,0xff,0x51,0x08
    };
    static const BYTE tail[] = {
        0x8b,0x94,0x24,0xe0,0x01,0x00,0x00,0x8b,0x5c,0x24,0x28,
        0x8b,0x74,0x24,0x34
    };
    static const BYTE thunk[] = {
        0x8b,0x44,0x24,0x0c,                 /* mov eax,[esp+12] */
        0xc7,0x00,0x00,0x00,0x00,0x00,       /* initialize *output */
        0xff,0x74,0x24,0x0c,                 /* push output */
        0xff,0x74,0x24,0x0c,                 /* push index */
        0xff,0x74,0x24,0x0c,                 /* push this */
        0xff,0x92,0x98,0x00,0x00,0x00,       /* original GetRenderTarget */
        0x85,0xc0,0x78,0x09,                 /* test HRESULT; js skip */
        0x8b,0x4c,0x24,0x0c,0x83,0x39,0x00, /* test *output */
        0x75,0x07,                           /* non-NULL: normal return */
        0x81,0x04,0x24,0,0,0,0,              /* skip optional GPU clear (+44) */
        0xc2,0x0c,0x00                      /* ret 12 */
    };
    BYTE *base = (BYTE *)module, *code;
    IMAGE_NT_HEADERS *nt;
    DWORD previous, ignored;
    SIZE_T i, k;
    BOOL installed = TRUE;
    if (!module || ((IMAGE_DOS_HEADER *)base)->e_magic != IMAGE_DOS_SIGNATURE)
        return FALSE;
    nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->FileHeader.Machine != IMAGE_FILE_MACHINE_I386 ||
        nt->FileHeader.TimeDateStamp != 0x61dd5c00 ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC ||
        nt->OptionalHeader.SizeOfImage != 0x561000 ||
        !same(base + 0x39915, (const char *)tail, sizeof(tail)))
        return FALSE;
    if (module == g_render_target_module && g_render_target_thunk) {
        for (k = 0; k < RT_SITES; k++) {
            BYTE *site = base + g_render_target_sites[k].site;
            installed = installed && site[0] == 0xe8 && site[5] == 0x90 &&
                (BYTE *)((DWORD)(ULONG_PTR)(site + 5) + *(DWORD *)(site + 1)) ==
                    g_render_target_thunk + k * RT_THUNK_SIZE;
        }
        if (installed)
            return TRUE;
    }
    /* all sites must match before any of them is changed */
    for (k = 0; k < RT_SITES; k++)
        if (!same(base + g_render_target_sites[k].site - 0xa, (const char *)expected, sizeof(expected)) ||
            !render_target_skip_ok(base, g_render_target_sites[k].site, g_render_target_sites[k].skip))
            return FALSE;
    code = (BYTE *)VirtualAlloc(NULL, RT_SITES * RT_THUNK_SIZE, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!code)
        return FALSE;
    for (k = 0; k < RT_SITES; k++) {
        BYTE *t = code + k * RT_THUNK_SIZE;
        for (i = 0; i < sizeof(thunk); i++)
            t[i] = thunk[i];
        *(DWORD *)(t + 44) = g_render_target_sites[k].skip - (g_render_target_sites[k].site + 5);
    }
    if (!VirtualProtect(code, RT_SITES * RT_THUNK_SIZE, PAGE_EXECUTE_READ, &previous)) {
        VirtualFree(code, 0, MEM_RELEASE);
        return FALSE;
    }
    FlushInstructionCache(GetCurrentProcess(), code, RT_SITES * RT_THUNK_SIZE);
    for (k = 0; k < RT_SITES; k++) {
        BYTE *site = base + g_render_target_sites[k].site;
        if (!VirtualProtect(site, 6, PAGE_EXECUTE_READWRITE, &previous))
            continue;
        site[0] = 0xe8;
        *(DWORD *)(site + 1) = (DWORD)(ULONG_PTR)(code + k * RT_THUNK_SIZE) - (DWORD)(ULONG_PTR)(site + 5);
        site[5] = 0x90;
        VirtualProtect(site, 6, previous, &ignored);
        FlushInstructionCache(GetCurrentProcess(), site, 6);
    }
    g_render_target_module = module;
    g_render_target_thunk = code;
    return TRUE;
}

/* Surface Lock cannot reuse the optional color-fill skip. Its failed readback
   must restore dirty state and release this call's CS acquisition before returning
   SurfaceLost. Private cleanup is entered by a redirected RETURN at bodySP. */
#define DEPTH_SITES 2
#define DEPTH_STRIDE 128
static const struct {
    DWORD site, procedure, tail, frame, context_arg, flags_arg, mask, dirty;
    BYTE output;
} g_depth_sites[DEPTH_SITES] = {
    {0x2b736,0x2ae30,0x2bfd2,0x22c,0x240,0x24c,0xa0,0x898,0x4c},
    {0x36d3f,0x36510,0x375e7,0x230,0x244,0x250,0xa4,0x88c,0x54}
};
static HMODULE g_depth_module;
static BYTE *g_depth_code;

static BOOL install_ddraw_depth_readback_fix(HMODULE module)
{
    static const BYTE prefix[] = {
        0x8d,0x4c,0x24,0x4c,0x51,0x56,0x8b,0x10,0x50,
        0xff,0x92,0x98,0,0,0,0x8b,0x44,0x24,0x4c,0x50,0x8b,0x10,0xff,0x52,0x08
    };
    static const BYTE tails[DEPTH_SITES][50] = {
        {0x8b,0x84,0x24,0xa0,0,0,0,0x8b,0x94,0x24,0x4c,0x02,0,0,0x5f,0x3b,0xc6,
         0x89,0x9d,0x8c,0x08,0,0,0x89,0x95,0x90,0x08,0,0,0x5e,0x5d,0x5b,0x75,0x05,
         0xe8,0x66,0x50,0xfd,0xff,0x33,0xc0,0x81,0xc4,0x2c,0x02,0,0,0xc2,0x14,0},
        {0x8b,0x84,0x24,0xa4,0,0,0,0x8b,0x8c,0x24,0x50,0x02,0,0,0x89,0x9d,0x80,
         0x08,0,0,0x5f,0x3b,0xc6,0x89,0x8d,0x84,0x08,0,0,0x5e,0x5d,0x5b,0x75,0x05,
         0xe8,0x51,0x9a,0xfc,0xff,0x33,0xc0,0x81,0xc4,0x30,0x02,0,0,0xc2,0x14,0}
    };
    static const BYTE thunk[] = {
        0x8b,0x44,0x24,0x0c,0xc7,0,0,0,0,0,
        0xff,0x74,0x24,0x0c,0xff,0x74,0x24,0x0c,0xff,0x74,0x24,0x0c,
        0xff,0x92,0x98,0,0,0,0x85,0xc0,0x78,0x09,
        0x8b,0x4c,0x24,0x0c,0x83,0x39,0,0x75,0x07,
        0x81,0x04,0x24,0,0,0,0,0xc2,0x0c,0
    };
    static const BYTE cleanup[] = {
        0x8b,0x84,0x24,0,0,0,0,         /* mov eax,[esp+context_arg] */
        0xc7,0x80,0,0,0,0,1,0,0,0,     /* restore [context+dirty]=1 */
        0x83,0xbc,0x24,0,0,0,0,0,       /* cmp [esp+cached skip-CS-mask],0 */
        0x75,0x05,0xe8,0,0,0,0,         /* nonzero skips LeaveCriticalSection */
        0x5f,0x5e,0x5d,0x5b,           /* restore original nonvolatile registers */
        0xb8,0xc2,0x01,0x76,0x88,       /* DDERR_SURFACELOST, after the Leave call */
        0x81,0xc4,0,0,0,0,0xc2,0x14,0 /* discard original frame; ret 20 */
    };
    BYTE *base=(BYTE *)module,*code;
    IMAGE_NT_HEADERS *nt;
    DWORD protections[DEPTH_SITES],old_code,ignored;
    SIZE_T k,i;
    BOOL installed=TRUE;
    if(!module || ((IMAGE_DOS_HEADER *)base)->e_magic!=IMAGE_DOS_SIGNATURE) return FALSE;
    nt=(IMAGE_NT_HEADERS *)(base+((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if(nt->Signature!=IMAGE_NT_SIGNATURE || nt->FileHeader.Machine!=IMAGE_FILE_MACHINE_I386 ||
       nt->FileHeader.TimeDateStamp!=0x61dd5c00 ||
       nt->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR32_MAGIC ||
       nt->OptionalHeader.SizeOfImage!=0x561000) return FALSE;
    if(module==g_depth_module && g_depth_code) {
        for(k=0;k<DEPTH_SITES;k++) {
            BYTE *site=base+g_depth_sites[k].site;
            installed=installed && site[0]==0xe8 && site[5]==0x90 &&
                (BYTE *)((DWORD)(ULONG_PTR)(site+5)+*(DWORD *)(site+1))==g_depth_code+k*DEPTH_STRIDE;
        }
        if(installed) return TRUE;
    }
    for(k=0;k<DEPTH_SITES;k++) {
        BYTE *p=base+g_depth_sites[k].procedure,*cache=p+0x2a;
        if(p[0]!=0x81 || p[1]!=0xec || *(DWORD *)(p+2)!=g_depth_sites[k].frame ||
           p[6]!=0x66 || p[7]!=0xa1 || *(DWORD *)(p+8)!=(DWORD)(ULONG_PTR)(base+0x176734) ||
           !same(p+12,"\x53\x55\x56\x57",4) ||
           !same(cache,"\x8b\x84\x24",3) || *(DWORD *)(cache+3)!=g_depth_sites[k].flags_arg ||
           !same(cache+7,"\x25\x00\x00\x00\x10\x89\x84\x24",8) ||
           *(DWORD *)(cache+15)!=g_depth_sites[k].mask ||
           !same(base+g_depth_sites[k].tail,(const char *)tails[k],sizeof(tails[k]))) return FALSE;
        for(i=0;i<sizeof(prefix);i++) {
            BYTE expected=(i==3 || i==18) ? g_depth_sites[k].output : prefix[i];
            if(base[g_depth_sites[k].site-9+i]!=expected) return FALSE;
        }
    }
    /* Check the exact Leave helper and its CS argument, including ASLR. */
    if(base[0x41b60]!=0x68 || *(DWORD *)(base+0x41b61)!=(DWORD)(ULONG_PTR)(base+0x176da0) ||
       !same(base+0x41b65,"\xff\x15",2) ||
       *(DWORD *)(base+0x41b67)!=(DWORD)(ULONG_PTR)(base+0x54e780) || base[0x41b6b]!=0xc3) return FALSE;
    code=(BYTE *)VirtualAlloc(NULL,DEPTH_SITES*DEPTH_STRIDE,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!code) return FALSE;
    for(k=0;k<DEPTH_SITES;k++) {
        BYTE *t=code+k*DEPTH_STRIDE,*end=t+64;
        for(i=0;i<sizeof(thunk);i++) t[i]=thunk[i];
        for(i=0;i<sizeof(cleanup);i++) end[i]=cleanup[i];
        *(DWORD *)(t+44)=(DWORD)(ULONG_PTR)end-(DWORD)(ULONG_PTR)(base+g_depth_sites[k].site+5);
        *(DWORD *)(end+3)=g_depth_sites[k].context_arg;
        *(DWORD *)(end+9)=g_depth_sites[k].dirty;
        *(DWORD *)(end+20)=g_depth_sites[k].mask;
        *(DWORD *)(end+28)=(DWORD)(ULONG_PTR)(base+0x41b60)-(DWORD)(ULONG_PTR)(end+32);
        *(DWORD *)(end+43)=g_depth_sites[k].frame;
    }
    if(!VirtualProtect(code,DEPTH_SITES*DEPTH_STRIDE,PAGE_EXECUTE_READ,&old_code)) {
        VirtualFree(code,0,MEM_RELEASE);return FALSE;
    }
    FlushInstructionCache(GetCurrentProcess(),code,DEPTH_SITES*DEPTH_STRIDE);
    /* Acquire both write permissions before changing either call-site. */
    for(k=0;k<DEPTH_SITES;k++) {
        if(!VirtualProtect(base+g_depth_sites[k].site,6,PAGE_EXECUTE_READWRITE,&protections[k])) {
            while(k) {--k;VirtualProtect(base+g_depth_sites[k].site,6,protections[k],&ignored);}
            VirtualFree(code,0,MEM_RELEASE);return FALSE;
        }
    }
    for(k=0;k<DEPTH_SITES;k++) {
        BYTE *site=base+g_depth_sites[k].site;
        site[0]=0xe8;
        *(DWORD *)(site+1)=(DWORD)(ULONG_PTR)(code+k*DEPTH_STRIDE)-(DWORD)(ULONG_PTR)(site+5);
        site[5]=0x90;
        VirtualProtect(site,6,protections[k],&ignored);
        FlushInstructionCache(GetCurrentProcess(),site,6);
    }
    g_depth_module=module;g_depth_code=code;
    return TRUE;
}

/* Once ddraw.dll is loaded: replace its mouse imports (it calls them for itself and from
   its hooks of the game's imports). */
static void guard_ddraw_mouse(void)
{
    HMODULE dd;
    if (g_ddraw_mouse_done || (dd = GetModuleHandleA("ddraw.dll")) == NULL)
        return;
    g_ddraw_mouse_done = TRUE;
    install_ddraw_render_target_fix(dd);
    install_ddraw_depth_readback_fix(dd);
    patch_import(dd, "USER32.dll", "SetCursorPos", (void *)local_SetCursorPos);
    patch_import(dd, "USER32.dll", "ClipCursor", (void *)local_ClipCursor);
    patch_import(dd, "USER32.dll", "SetForegroundWindow", (void *)local_SetForegroundWindow);
    patch_import(dd, "USER32.dll", "SetFocus", (void *)local_SetFocus);
#ifdef ARMADA_TESTHOOKS
    stay_in_background(dd);
    install_test_d3d_trace(dd);
#endif
}

static ATOM WINAPI local_RegisterClassA(const WNDCLASSA *wc)
{
    if (wc && wc->lpszClassName && HIWORD((DWORD_PTR)wc->lpszClassName) &&
        lstrcmpiA(wc->lpszClassName, "Armada") == 0 && wc->lpfnWndProc && !g_game_wndproc) {
        WNDCLASSA copy = *wc;
        g_game_wndproc = wc->lpfnWndProc;
        copy.lpfnWndProc = game_wndproc;
        return RegisterClassA(&copy);
    }
    return RegisterClassA(wc);
}

/*
 * Light lifetime fix (GOG 1.2 Armada.exe, checked by code signature).
 *
 * The render engine (ST3D, global at 0x6d4aa0) keeps the lights of the current scene
 * render in a list at engine+0x70 (AddLight 0x58b380, cleared by 0x58b440). Each
 * record starts with a raw ST3D_Light pointer. The mesh lighting code (e.g. 0x5a4410)
 * calls virtual methods of these lights. If a light is destroyed while its record is
 * still in the list, the next mesh render calls a method of the destroyed object and
 * the game dies with "pure virtual function call" (seen in a 2-player LAN match).
 *
 * All four ST3D light destructors end with "mov [ecx], ST3D_Light vtable;
 * jmp ST3D_Node::~ST3D_Node (0x5958b0)". The jmp is redirected to light_dtor_tail,
 * which first removes every record of this light from the active list.
 */
#define ENGINE_PTR        ((char **)0x6d4aa0)
#define NODE_DTOR         0x5958b0
#define OPERATOR_DELETE   0x5bb63c

static const DWORD g_light_dtor_jmps[] = { 0x58e766, 0x58e7a6, 0x58e806, 0x58e846 };
static DWORD g_main_thread;
static volatile LONG g_purged;

typedef void (__cdecl *delete_fn)(void *);

static void __stdcall purge_light(void *light);
#ifdef ARMADA_TESTHOOKS
static void log_line(const char *fmt, ...);
static void log_stack(const char *what, DWORD ebp);
#endif

static void __stdcall purge_light(void *light)
{
    char *eng = *ENGINE_PTR;
    int *head, *node;
    /* The engine may already be gone while lights are destroyed at shutdown: check every
       pointer before it is read. */
    if (!eng || !light || IsBadReadPtr(eng + 0x70, 8))
        return;
    head = *(int **)(eng + 0x70);
    if (!head || IsBadReadPtr(head, 12))
        return;
    node = (int *)head[0];
    while (node && node != head && !IsBadReadPtr(node, 12)) {
        int *next = (int *)node[0];
        int *rec = (int *)node[2];
        if (rec && !IsBadReadPtr(rec, 4) && (void *)rec[0] == light) {
            *(int *)node[1] = node[0];                 /* prev->next = next */
            ((int *)node[0])[1] = node[1];             /* next->prev = prev */
            ((delete_fn)OPERATOR_DELETE)(node);
            (*(int *)(eng + 0x74))--;
            ((delete_fn)OPERATOR_DELETE)(rec);
            InterlockedIncrement(&g_purged);
#ifdef ARMADA_TESTHOOKS
            {
                DWORD ebp_;
                __asm mov ebp_, ebp
                log_line("light %p destroyed while active (thread %lu, main %lu), record purged",
                         light, GetCurrentThreadId(), g_main_thread);
                log_stack("  destroy stack", ebp_);
            }
#endif
        }
        node = next;
    }
}

static __declspec(naked) void light_dtor_tail(void)
{
    __asm {
        pushad
        push ecx
        call purge_light
        popad
        push NODE_DTOR              /* continue in ST3D_Node::~ST3D_Node, registers unchanged */
        ret
    }
}

static void install_light_fix(void)
{
    static const BYTE stub[6] = { 0xc7, 0x01, 0xa8, 0x40, 0x5d, 0x00 };   /* mov [ecx], 0x5d40a8 */
    int i, k;
    for (i = 0; i < 4; i++) {
        BYTE *jmp = (BYTE *)g_light_dtor_jmps[i];
        if (IsBadReadPtr(jmp - 6, 11) || jmp[0] != 0xE9)
            return;
        for (k = 0; k < 6; k++)
            if (jmp[k - 6] != stub[k])
                return;
        if ((DWORD)(jmp + 5 + *(int *)(jmp + 1)) != NODE_DTOR && (DWORD)(jmp + 5 + *(int *)(jmp + 1)) != (DWORD)light_dtor_tail)
            return;                                     /* not the GOG 1.2 code */
    }
    for (i = 0; i < 4; i++) {
        BYTE *jmp = (BYTE *)g_light_dtor_jmps[i];
        DWORD prot;
        if (VirtualProtect(jmp, 5, PAGE_EXECUTE_READWRITE, &prot)) {
            *(int *)(jmp + 1) = (int)((BYTE *)light_dtor_tail - (jmp + 5));
            VirtualProtect(jmp, 5, prot, &prot);
        }
    }
    FlushInstructionCache(GetCurrentProcess(), NULL, 0);
}

#ifdef ARMADA_TESTHOOKS
/*
 * Test build only (build.cmd test): determinism test bed for the GOG 1.2 Armada.exe.
 * Environment variables:
 *   ARMADA_TEST_DUMP_EVERY  write a state dump after every N simulation steps
 *   ARMADA_TEST_DUMP_DIR    folder for the dumps (default Logs)
 *   ARMADA_TEST_EXIT_AFTER  terminate the process after N simulation steps
 *   ARMADA_TEST_MULTI       1: allow a second instance (FindWindowA("Armada") returns NULL)
 *   ARMADA_TEST_INPUT       1: enable per-client virtual input and normal network-queue commands
 *   ARMADA_TEST_NATIVE_MODE_INIT 1: initialize GOG rendering for native-window matches
 *   ARMADA_TEST_INJECT_STEP/_ORDER/_REPEAT  give every ship an order (CommandAllShips) at that
 *                           simulation step and then every _REPEAT steps
 *   ARMADA_TEST_NO_LIGHTFIX 1: leave the light destructors unpatched
 * The dump uses the game's own sync dump writers (objects 0x46f190, weapons 0x50bb20,
 * ordnance 0x4edde0) and the generator states; it consumes no random numbers.
 */
typedef void (__stdcall *step_fn)(int ms);
typedef void *(__cdecl *fopen_fn)(const char *, const char *);
typedef int (__cdecl *fclose_fn)(void *);
typedef int (__cdecl *fprintf_fn)(void *, const char *, ...);
typedef void (__cdecl *dump_fn)(void *);

static step_fn g_step;
static unsigned g_steps, g_dump_every, g_exit_after;
static char g_dump_dir[MAX_PATH] = "Logs";

/* Counters for the docking approach-angle draws (finding 1): the three call sites get a
   stub "inc [counter]; jmp <original target>", so the dumps show whether the path ran. */
static const DWORD g_dock_sites[3] = { 0x42a540, 0x42b76e, 0x430296 };
static volatile LONG g_dock_count[3];
static volatile LONG g_o8_count;      /* order 8 handler: target gone, patched return taken */

static void install_dock_counters(void)
{
    BYTE *stubs = (BYTE *)VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    int i;
    if (!stubs)
        return;
    for (i = 0; i < 3; i++) {
        BYTE *site = (BYTE *)g_dock_sites[i], *st = stubs + 16 * i;
        DWORD target, prot;
        if (site[0] != 0xE8)
            return;
        target = (DWORD)(site + 5 + *(int *)(site + 1));
        if (target != 0x5018c0 && target != 0x5014d0)
            return;
        st[0] = 0xFF;                                   /* inc dword ptr [counter] */
        st[1] = 0x05;
        *(DWORD *)(st + 2) = (DWORD)&g_dock_count[i];
        st[6] = 0xE9;                                   /* jmp target */
        *(int *)(st + 7) = (int)(target - (DWORD)(st + 11));
        if (VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &prot)) {
            *(int *)(site + 1) = (int)((DWORD)st - (DWORD)(site + 5));
            VirtualProtect(site, 5, prot, &prot);
        }
    }
}

/* Patched exe only: "jmp 0x42b034" at 0x42afe7 goes through the padding at 0x42b037
   (inc [g_o8_count]; jmp 0x42b034), so the dumps show how often the fix was needed. */
static void install_o8_counter(void)
{
    BYTE *site = (BYTE *)0x42afe7, *cave = (BYTE *)0x42b037;
    DWORD prot;
    int i;
    if (site[0] != 0xEB || site[1] != 0x4B || cave[-3] != 0x5F || cave[-2] != 0x5E || cave[-1] != 0xC3)
        return;
    for (i = 0; i < 9; i++)
        if (cave[i] != 0x90)
            return;
    if (!VirtualProtect(site, 0x60, PAGE_EXECUTE_READWRITE, &prot))
        return;
    cave[0] = 0xFF;                                     /* inc dword ptr [g_o8_count] */
    cave[1] = 0x05;
    *(DWORD *)(cave + 2) = (DWORD)&g_o8_count;
    cave[6] = 0xEB;                                     /* jmp 0x42b034 */
    cave[7] = 0xF5;
    site[1] = 0x4E;                                     /* jmp 0x42b037 */
    VirtualProtect(site, 0x60, prot, &prot);
}

static unsigned env_uint(const char *name)
{
    char buf[32];
    unsigned v = 0;
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf)), i;
    for (i = 0; i < n && i < sizeof(buf) && buf[i] >= '0' && buf[i] <= '9'; i++)
        v = v * 10 + (unsigned)(buf[i] - '0');
    return v;
}

/* Optional local input device for real gameplay tests. Only the device Poll and
   modifier queries are virtual; the original UI and multiplayer command queue run.
   Private messages are outside the ranges drained by the game's mouse/key handlers.
   A sequence is acknowledged only when a device Poll consumes it. */
#define INPUT_ENABLE (WM_APP + 0x410)
#define INPUT_MOVE   (WM_APP + 0x411)
#define INPUT_BUTTON (WM_APP + 0x412)
#define INPUT_KEY    (WM_APP + 0x413)
#define INPUT_CAPTURE (WM_APP + 0x414)
typedef int (__cdecl *mousepoll_fn)(int *, int *, DWORD *);
static mousepoll_fn g_original_mousepoll;
static int g_virtual_x, g_virtual_y;
static DWORD g_virtual_buttons, g_virtual_seq, g_virtual_ack;
static volatile BYTE g_virtual_keys[256];
static BOOL g_input_available;
static DWORD g_capture_seq;

typedef HRESULT (WINAPI *dsound_create_fn)(const GUID *, void **, void *);
static dsound_create_fn g_DirectSoundCreate;

/* Create/mute this process's Windows mixer session before DirectSound creates
   its first stream. This runs outside DllMain, on the actual audio-init call. */
static HRESULT mute_test_audio(void)
{
    static const GUID device_class = {0xbcde0395,0xe52f,0x467c,{0x8e,0x3d,0xc4,0x57,0x92,0x91,0x69,0x2e}};
    static const GUID enumerator_iid = {0xa95664d2,0x9614,0x4f35,{0xa7,0x46,0xde,0x8d,0xb6,0x36,0x17,0xe6}};
    static const GUID manager_iid = {0xbfa971f1,0x4d5e,0x40bb,{0x93,0x5e,0x96,0x70,0x39,0xbf,0xbe,0xe4}};
    IMMDeviceEnumerator *enumerator = NULL;
    IMMDevice *device = NULL;
    IAudioSessionManager *manager = NULL;
    ISimpleAudioVolume *volume = NULL;
    HRESULT init = CoInitializeEx(NULL, COINIT_MULTITHREADED), hr;
    hr = CoCreateInstance(&device_class, NULL, CLSCTX_INPROC_SERVER,
                          &enumerator_iid, (void **)&enumerator);
    if (SUCCEEDED(hr)) hr = enumerator->lpVtbl->GetDefaultAudioEndpoint(enumerator, eRender, eMultimedia, &device);
    if (SUCCEEDED(hr)) hr = device->lpVtbl->Activate(device, &manager_iid,
                                                    CLSCTX_INPROC_SERVER, NULL, (void **)&manager);
    if (SUCCEEDED(hr)) hr = manager->lpVtbl->GetSimpleAudioVolume(manager, NULL, FALSE, &volume);
    if (SUCCEEDED(hr)) hr = volume->lpVtbl->SetMute(volume, TRUE, NULL);
    if (volume) volume->lpVtbl->Release(volume);
    if (manager) manager->lpVtbl->Release(manager);
    if (device) device->lpVtbl->Release(device);
    if (enumerator) enumerator->lpVtbl->Release(enumerator);
    if (SUCCEEDED(init)) CoUninitialize();
    log_line("Windows mixer mute before DirectSoundCreate: %08lx", hr);
    return hr;
}

static HRESULT WINAPI test_DirectSoundCreate(const GUID *guid, void **sound, void *outer)
{
    HRESULT hr = mute_test_audio();
    if (FAILED(hr)) return hr;  /* do not start audible test streams */
    return g_DirectSoundCreate(guid, sound, outer);
}

/* Opt-in startup diagnosis: retain CreateDevice's original HRESULT. */
typedef HRESULT (WINAPI *test_createdevice_fn)(void *, UINT, DWORD, HWND, DWORD, DWORD *, void **);
static void *g_test_d3d_resume[4];

static HRESULT WINAPI test_trace_createdevice(void *object, UINT adapter, DWORD type,
    HWND focus, DWORD flags, DWORD *parameters, void **output)
{
    DWORD owner = 0, thread = GetWindowThreadProcessId(focus, &owner);
    RECT rect = {0};
    HRESULT hr;
    test_createdevice_fn original = (test_createdevice_fn)(*(void ***)object)[16];
    GetClientRect(focus, &rect);
    hr = original(object, adapter, type, focus, flags, parameters, output);
    log_line("D3D_INIT_TRACE CreateDevice hr=%08lx adapter=%u type=%lu flags=%08lx hwnd=%08lx owner=%lu window_thread=%lu caller_thread=%lu client=%ld,%ld windowed=%lu output=%08lx",
        hr, adapter, type, flags, (DWORD)focus, owner, thread, GetCurrentThreadId(),
        rect.right, rect.bottom, parameters ? parameters[8] : 0,
        output ? (DWORD)*output : 0);
    return hr;
}

static __declspec(naked) void test_trace_create0(void)
{
    __asm { push esi }
    __asm { push ebx }
    __asm { push eax }
    __asm { call test_trace_createdevice }
    __asm { jmp dword ptr [g_test_d3d_resume] }
}
static __declspec(naked) void test_trace_create1(void)
{
    __asm { push esi }
    __asm { push ebx }
    __asm { push eax }
    __asm { call test_trace_createdevice }
    __asm { jmp dword ptr [g_test_d3d_resume + 4] }
}
static __declspec(naked) void test_trace_create2(void)
{
    __asm { push esi }
    __asm { push ebx }
    __asm { push eax }
    __asm { call test_trace_createdevice }
    __asm { jmp dword ptr [g_test_d3d_resume + 8] }
}
static __declspec(naked) void test_trace_create3(void)
{
    __asm { push esi }
    __asm { push ebx }
    __asm { push eax }
    __asm { call test_trace_createdevice }
    __asm { jmp dword ptr [g_test_d3d_resume + 12] }
}

static void install_test_d3d_trace(HMODULE wrapper)
{
    /* Leave every CMP intact: earlier branches enter the final CMP directly. */
    static const DWORD offsets[4] = {0x1e87e, 0x1e8e5, 0x1e948, 0x1e9b2};
    static const BYTE expected[4][6] = {
        {0x56,0x53,0x50,0xff,0x52,0x40},
        {0x56,0x53,0x50,0xff,0x51,0x40},
        {0x56,0x53,0x50,0xff,0x51,0x40},
        {0x56,0x53,0x50,0xff,0x51,0x40}};
    void *relays[4] = {(void *)test_trace_create0,(void *)test_trace_create1,(void *)test_trace_create2,(void *)test_trace_create3};
    BYTE *base = (BYTE *)wrapper;
    IMAGE_NT_HEADERS *headers;
    unsigned i, j;
    DWORD previous, ignored;
    if (env_uint("ARMADA_TEST_D3D_INIT_TRACE") != 1) return;
    headers = (IMAGE_NT_HEADERS *)(base+((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if (headers->FileHeader.Machine != IMAGE_FILE_MACHINE_I386 ||
        headers->FileHeader.TimeDateStamp != 0x61dd5c00 ||
        headers->OptionalHeader.SizeOfImage != 0x561000) return;
    for (i=0; i<4; i++)
        for (j=0; j<6; j++)
            if (base[offsets[i]+j] != expected[i][j]) return;
    for (i=0; i<4; i++) {
        unsigned size = 6;
        BYTE *site = base+offsets[i];
        if (!VirtualProtect(site,size,PAGE_EXECUTE_READWRITE,&previous)) return;
        g_test_d3d_resume[i] = site+size;
        site[0]=0xe9;
        *(int *)(site+1) = (int)((BYTE *)relays[i]-(site+5));
        for (j=5;j<size;j++) ((volatile BYTE *)site)[j]=0x90;
        VirtualProtect(site,size,previous,&ignored);
        FlushInstructionCache(GetCurrentProcess(),site,size);
    }
}

/* Native -window calls RestoreDisplayMode, which destroys GOG's D3D9 facade.
   Initialize it on the menu -> game transition, before the new game surfaces.
   The initial desktop-mode bootstrap must retain the original behavior: creating
   a GPU device there breaks the subsequent Bink/menu transition. */
static HRESULT __fastcall test_native_mode(char *device, void *unused)
{
    typedef HRESULT (WINAPI *restore_fn)(void *);
    typedef HRESULT (WINAPI *setmode_fn)(void *, DWORD, DWORD, DWORD, DWORD, DWORD);
    void *draw = *(void **)(device + 0xd4);
    DWORD *mode = *(DWORD **)(device + 0x3c);
    char *engine = *(char **)0x6d4aa0;
    HMODULE wrapper = GetModuleHandleA("ddraw.dll");
    char ini[MAX_PATH], presentation[24];
    int i, width, height;
    HRESULT hr;
    WORD control;
    DWORD length;
    IMAGE_NT_HEADERS *headers;
    static BOOL saw_menu;
    (void)unused;
    if (engine && *(DWORD *)(engine + 0x124) == 3) saw_menu = TRUE;
    if (!wrapper || !engine || !saw_menu || *(DWORD *)(engine + 0x124) != 2)
        goto original_restore;
    headers = (IMAGE_NT_HEADERS *)((BYTE *)wrapper + ((IMAGE_DOS_HEADER *)wrapper)->e_lfanew);
    if (headers->FileHeader.TimeDateStamp != 0x61dd5c00 || headers->OptionalHeader.SizeOfImage != 0x561000)
        goto original_restore; /* GOG DirectX 1-7 wrapper 1.1.0.3494 only */
    length = GetModuleFileNameA(NULL, ini, sizeof(ini));
    if (!length || length >= MAX_PATH - 12) goto original_restore;
    for (i = lstrlenA(ini) - 1; i >= 0 && ini[i] != '\\'; i--) {}
    lstrcpyA(ini + i + 1, "dxcfg.ini");
    GetPrivateProfileStringA("dxcfg", "presentation", "", presentation, sizeof(presentation), ini);
    if (lstrcmpiA(presentation, "windowed") != 0) goto original_restore;
    __asm fnstcw control
    __asm {
        mov eax, device
        fld dword ptr [eax + 0xcc]
        fistp width
        fld dword ptr [eax + 0xd0]
        fistp height
    }
    if (width < 1 || height < 1 || width > 8192 || height > 8192) goto original_restore;
    hr = ((setmode_fn)(*(void ***)draw)[21])(draw, width, height, mode[2], 0, 0);
    __asm fldcw control
    log_line("native window renderer %d x %d x %lu hr=%08lx D3D9=%08lx windowed=%lu",
        width, height, mode[2], hr, *(DWORD *)((BYTE *)wrapper + 0x460724),
        *(DWORD *)((BYTE *)wrapper + 0x468478));
    if (SUCCEEDED(hr) && (!*(DWORD *)((BYTE *)wrapper + 0x460724) ||
        *(DWORD *)((BYTE *)wrapper + 0x468478) != 1)) return E_FAIL;
    return hr;
original_restore:
    ((restore_fn)(*(void ***)draw)[19])(draw);
    return S_OK; /* the original native branch ignores RestoreDisplayMode's status */
}

static void install_test_window_renderer(void)
{
    static const BYTE expected[12] = {0x8b,0x83,0xd4,0,0,0,0x50,0x8b,0x08,0xff,0x51,0x4c};
    BYTE *site = (BYTE *)0x5816f4;
    DWORD protect;
    int i;
    if (env_uint("ARMADA_TEST_NATIVE_MODE_INIT") != 1) return;
    for (i = 0; i < 12; i++) if (site[i] != expected[i]) return;
    if (!VirtualProtect(site, 12, PAGE_EXECUTE_READWRITE, &protect)) return;
    for (i = 0; i < 12; i++) site[i] = 0x90;
    site[0] = 0x8b; site[1] = 0xcb; /* mov ecx,ebx: native renderer */
    site[2] = 0xe8;
    *(int *)(site + 3) = (int)((BYTE *)test_native_mode - (site + 7));
    site[7] = 0x85; site[8] = 0xc0; /* test eax,eax */
    site[9] = 0x75; site[10] = 0x98; /* jnz 0x581697: original SetDisplayMode error path */
    VirtualProtect(site, 12, protect, &protect);
    FlushInstructionCache(GetCurrentProcess(), site, 12);
}

static void install_test_mute(void)
{
    DWORD prot;
    dsound_create_fn *slot = (dsound_create_fn *)0x6d7a54;
    g_DirectSoundCreate = (dsound_create_fn)GetProcAddress(GetModuleHandleA("dsound.dll"), "DirectSoundCreate");
    /* GOG 1.2 imports DSOUND ordinal 1, without an import name. */
    if (g_DirectSoundCreate && *slot == g_DirectSoundCreate &&
        VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &prot)) {
        *slot = test_DirectSoundCreate;
        VirtualProtect(slot, sizeof(*slot), prot, &prot);
    }
}

typedef struct {
    DWORD seq, action, actor, target;
    char name[8];
    float position[3];
} test_command;

/* Submit one player's command to that client's original output queue. The game
   distributes and validates it normally. This never invokes simulation orders
   directly and never submits the command on the other peer. */
static LRESULT test_network_event(LPARAM lp)
{
    typedef void *(__cdecl *lookup_fn)(DWORD);
    COPYDATASTRUCT *copy = (COPYDATASTRUCT *)lp;
    test_command *command;
    char *actor, *target = NULL, *build = NULL;
    void *vector, **item, **end;
    char name[9];
    unsigned team;
    DWORD function, order;
    float *position;
    static DWORD last_sequence;
    if (!g_input_available || !copy || copy->dwData != 0x41524d44 ||
        copy->cbData != sizeof(test_command) || !copy->lpData)
        return 2;
    command = (test_command *)copy->lpData;
    if (last_sequence == command->seq) return 1;
    if (!g_steps || !*(void **)0x6787c4)
        return 0; /* retry in the normal command-collection message pump */
    actor = (char *)((lookup_fn)0x46cf50)(command->actor);
    team = ((unsigned (__cdecl *)(void))0x46d060)();
    if (!actor || !(*(DWORD *)(actor + 0xbc) & 4) || *(unsigned *)(actor + 0x194) != team)
        return 2;
    if (command->action == 1 || command->action == 3) {
        int i;
        for (i = 0; i < 8; i++) name[i] = command->name[i];
        name[8] = 0;
        vector = *(void **)0x63a00c;
        if (!vector) return 2;
        item = *(void ***)((char *)vector + 4);
        end = *(void ***)((char *)vector + 8);
        for (; item < end; item++) {
            if (lstrcmpiA(*(const char **)((char *)*item + 0x8c), name) == 0) {
                build = (char *)*item;
                break;
            }
        }
        if (!build) return 2; /* only classes already loaded by this game */
        function = command->action == 1 ? 0x470d20 : 0x470da0;
        order = 28;
        position = command->position;
        if (command->action == 3) {
            __asm { push position }
        }
        __asm {
            push build
            push order
            mov ecx, actor
            call function
        }
    } else if (command->action == 2) {
        target = (char *)((lookup_fn)0x46cf50)(command->target);
        if (!target || *(unsigned *)(target + 0x194) == team) return 2;
        function = 0x470bf0;
        order = 5;
        __asm {
            push target
            push order
            mov ecx, actor
            call function
        }
    } else return 2;
    last_sequence = command->seq;
    log_line("network command %lu action %lu actor %08lx target %08lx team %u at step %u",
             command->seq, command->action, command->actor, command->target, team, g_steps);
    return 1;
}

/* Native DirectX7 screenshot API. This requires an initialized renderer; the
   wrapper's readback can have inverted row order. Actual window presentation is
   checked separately from this diagnostic image. */
static void capture_game_frame(DWORD seq)
{
    typedef void *(__cdecl *image_alloc_fn)(unsigned);
    char *engine = *(char **)0x6d4aa0, *device;
    void *image;
    int width, height;
    const char *name = "test frame";
    char path[MAX_PATH + 40];
    if (!engine || !(device = *(char **)(engine + 0xe4)) || *(DWORD *)device != 0x5d3d8c) {
        log_line("capture %lu: native DirectX7 device unavailable", seq);
        return;
    }
    __asm {
        mov eax, device
        fld dword ptr [eax + 0xcc]
        fistp width
        fld dword ptr [eax + 0xd0]
        fistp height
    }
    image = ((image_alloc_fn)0x5bb998)(0x50);
    if (!image) return;
    __asm {
        push 0
        push 1
        push height
        push width
        push name
        push 0
        mov ecx, image
        mov eax, 0x59e4e0
        call eax
        mov image, eax
        push 0
        push image
        mov ecx, device
        mov eax, [ecx]
        call dword ptr [eax + 0x14]
    }
    wsprintfA(path, "%s\\frame_%lu.bmp", g_dump_dir, seq);
    __asm {
        lea eax, path
        push eax
        mov ecx, image
        mov eax, 0x59f530
        call eax
        mov ecx, image
        mov eax, [ecx]
        push 1
        call dword ptr [eax]
    }
    log_line("capture %lu: native %d x %d at step %u local team %u", seq, width, height,
             g_steps, ((unsigned (__cdecl *)(void))0x46d060)());
}

/* Capture the completed back buffer immediately before its normal presentation.
   A simulation-step callback may run after the buffer has already been cleared. */
static void capture_pending_frame(void)
{
    DWORD seq = g_capture_seq;
    if (seq) {
        g_capture_seq = 0;
        capture_game_frame(seq);
    }
}

static __declspec(naked) void test_present(void)
{
    __asm {
        pushfd
        pushad
        call capture_pending_frame
        popad
        popfd
        mov eax, 0x581fb0
        jmp eax
    }
}

static SHORT WINAPI test_GetKeyState(int key)
{
    return key >= 0 && key < 256 && g_virtual_keys[key] ? (SHORT)-28672 : 0;
}

static int __cdecl test_mousepoll(int *state, int *out, DWORD *buttons)
{
    int i;
    if (!g_virtual_input)
        return g_original_mousepoll(state, out, buttons);
    state[0] = g_virtual_x; state[1] = 0;
    state[2] = g_virtual_y; state[3] = 0;
    for (i = 0; i < 4; i++)
        out[i] = state[i];
    if (buttons)
        *buttons = g_virtual_buttons;
    if (g_virtual_seq != g_virtual_ack) {
        g_virtual_ack = g_virtual_seq;
        log_line("input ack %lu step %u axes %d %d buttons %lu", g_virtual_ack, g_steps,
                 g_virtual_x, g_virtual_y, g_virtual_buttons);
    }
    return 0;
}

static BOOL test_input_event(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    UINT vk, scan;
    LPARAM flags;
    int i;
    if (msg < INPUT_ENABLE || msg > INPUT_CAPTURE)
        return FALSE;
    if (!g_input_available)
        return TRUE;
    if (msg == INPUT_CAPTURE) {
        g_capture_seq = (DWORD)wp;
        return TRUE;
    }
    if (msg == INPUT_ENABLE) {
        g_virtual_input = wp != 0;
        g_virtual_buttons = 0;
        for (i = 0; i < 256; i++)
            g_virtual_keys[i] = 0;
        /* WA_ACTIVE with lParam=0 only sets the game's logical input flags. The
           original branch calls engine Activate(true,false), with no OS focus. */
        CallWindowProcA(g_game_wndproc, hwnd, WM_ACTIVATE,
                        g_virtual_input ? WA_ACTIVE : WA_INACTIVE, 0);
        log_line("virtual input %s", g_virtual_input ? "enabled" : "disabled");
        return TRUE;
    }
    if (!g_virtual_input)
        return TRUE;
    g_virtual_seq = (DWORD)wp;
    if (msg == INPUT_MOVE) {
        g_virtual_x = (int)(short)LOWORD(lp) * 131072 / 640 - 65536;
        g_virtual_y = (int)(short)HIWORD(lp) * 131072 / 480 - 65536;
    } else if (msg == INPUT_BUTTON) {
        /* Stock WM_LBUTTONDOWN sets 1, WM_MBUTTONDOWN 2, WM_RBUTTONDOWN 4. */
        if (lp == 1) g_virtual_buttons |= 1;
        if (lp == 2) g_virtual_buttons &= ~1u;
        if (lp == 3) g_virtual_buttons |= 4;
        if (lp == 4) g_virtual_buttons &= ~4u;
    } else if (msg == INPUT_KEY) {
        vk = LOWORD(lp);
        if (vk < 256) {
            g_virtual_keys[vk] = HIWORD(lp) ? 0 : 1;
            scan = MapVirtualKeyA(vk, MAPVK_VK_TO_VSC);
            flags = 1 | (scan << 16);
            if (HIWORD(lp))
                flags |= (LPARAM)0xc0000000;
            CallWindowProcA(g_game_wndproc, hwnd, HIWORD(lp) ? WM_KEYUP : WM_KEYDOWN, vk, flags);
        }
    }
    return TRUE;
}

static void install_virtual_input(HMODULE exe)
{
    DWORD prot;
    mousepoll_fn *slot = (mousepoll_fn *)0x60834c;
    if (env_uint("ARMADA_TEST_INPUT") != 1)
        return;
    if (*slot != (mousepoll_fn)0x477430 || !VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &prot))
        return;
    g_original_mousepoll = *slot;
    *slot = test_mousepoll;
    VirtualProtect(slot, sizeof(*slot), prot, &prot);
    slot = (mousepoll_fn *)(0x5d3d8c + 0x4c);
    if (*(DWORD *)slot == 0x581fb0 && VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &prot)) {
        *(DWORD *)slot = (DWORD)test_present;
        VirtualProtect(slot, sizeof(*slot), prot, &prot);
    }
    patch_import(exe, "USER32.dll", "GetKeyState", (void *)test_GetKeyState);
    patch_import(exe, "USER32.dll", "GetAsyncKeyState", (void *)test_GetKeyState);
    g_input_available = TRUE;
}

static void dump_state(unsigned step)
{
    HMODULE crt = GetModuleHandleA("msvcrt.dll");
    fopen_fn f_open = (fopen_fn)GetProcAddress(crt, "fopen");
    fclose_fn f_close = (fclose_fn)GetProcAddress(crt, "fclose");
    fprintf_fn f_printf = (fprintf_fn)GetProcAddress(crt, "fprintf");
    char path[MAX_PATH + 32], pending[MAX_PATH + 40];
    void *f;
    if (!f_open || !f_close || !f_printf)
        return;
    wsprintfA(path, "%s\\step_%06u.txt", g_dump_dir, step);
    wsprintfA(pending, "%s.tmp", path);
    if ((f = f_open(pending, "w")) == NULL)
        return;
    f_printf(f, "step %u synced_rng %08lx table_index %lu\n", step,
             *(DWORD *)0x67dc98, *(DWORD *)0x67dc9c);
    /* Original simulation milliseconds, without changing the x87 state. */
    f_printf(f, "simulation_seconds %lu.%03lu tick %lu\n", *(DWORD *)0x67dcb8 / 1000,
             *(DWORD *)0x67dcb8 % 1000, *(DWORD *)0x67dcb0);
    f_printf(f, "docking_angle_draws %ld %ld %ld order8_lost_target %ld local_rng %08lx\n", g_dock_count[0],
             g_dock_count[1], g_dock_count[2], g_o8_count, *(DWORD *)0x67dca4);
    ((dump_fn)0x46f190)(f);
    ((dump_fn)0x50bb20)(f);
    ((dump_fn)0x4edde0)(f);
    f_printf(f, "END step %u\n", step);
    if (f_close(f) == 0)
        MoveFileExA(pending, path, MOVEFILE_REPLACE_EXISTING);
}

static void log_line(const char *fmt, ...)
{
    char path[MAX_PATH + 16], buf[600];
    va_list ap;
    HANDLE h;
    DWORD n;
    va_start(ap, fmt);
    n = (DWORD)wvsprintfA(buf, fmt, ap);
    va_end(ap);
    buf[n++] = '\r';
    buf[n++] = '\n';
    wsprintfA(path, "%s\\diag.txt", g_dump_dir);
    h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS, 0, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        WriteFile(h, buf, n, &n, NULL);
        CloseHandle(h);
    }
}

static void log_stack(const char *what, DWORD ebp)
{
    char line[400];
    int len = wsprintfA(line, "%s step %u:", what, g_steps), i;
    for (i = 0; i < 16 && ebp && !IsBadReadPtr((void *)ebp, 8); i++) {
        DWORD ret = ((DWORD *)ebp)[1];
        len += wsprintfA(line + len, " %08lx", ret);
        if (len > 360)
            break;
        ebp = ((DWORD *)ebp)[0];
    }
    log_line("%s", line);
}

/*
 * Test instances never become the active window: a thread-local CBT hook refuses every
 * activation of a window of the game thread and logs who asked for it (return addresses
 * on the stack that follow a call instruction, as module+offset).
 */
static HHOOK g_cbt;

static BOOL after_call(const BYTE *r)
{
    if (IsBadReadPtr(r - 6, 6))
        return FALSE;
    return r[-5] == 0xE8 || (r[-6] == 0xFF && (r[-5] == 0x15 || (r[-5] & 0xF8) == 0x90)) ||
           (r[-2] == 0xFF && (r[-1] & 0xF8) == 0xD0) || (r[-3] == 0xFF && (r[-2] & 0xF8) == 0x50);
}

static void log_callers(const char *what)
{
    char line[560], name[MAX_PATH];
    DWORD *sp = (DWORD *)&what, *top = (DWORD *)__readfsdword(4);
    int len = wsprintfA(line, "%s:", what), found = 0;
    for (; sp < top && found < 14 && len < 480; sp++) {
        HMODULE m;
        const BYTE *r = (const BYTE *)*sp;
        if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                (LPCSTR)r, &m) || !after_call(r))
            continue;
        if (!GetModuleFileNameA(m, name, sizeof(name)))
            continue;
        len += wsprintfA(line + len, " %s+%lx", lstrlenA(name) > 0 ? name + lstrlenA(name) - (lstrlenA(name) > 12 ? 12 : lstrlenA(name)) : "?",
                         (DWORD)(r - (const BYTE *)m));
        found++;
    }
    log_line("%s", line);
}

static LRESULT CALLBACK cbt_proc(int code, WPARAM wp, LPARAM lp)
{
    if (code == HCBT_ACTIVATE) {
        char cls[64], what[128];
        cls[0] = 0;
        GetClassNameA((HWND)wp, cls, sizeof(cls));
        wsprintfA(what, "activation refused (window %08lx class %s)", (DWORD)wp, cls);
        log_callers(what);
        return 1;
    }
    return CallNextHookEx(g_cbt, code, wp, lp);
}

typedef void (__cdecl *purecall_fn)(void);
static purecall_fn g_purecall;

static void __cdecl local_purecall(void)
{
    DWORD ebp_;
    __asm mov ebp_, ebp
    log_line("PURE VIRTUAL CALL (thread %lu, main %lu), lights purged so far: %ld",
             GetCurrentThreadId(), g_main_thread, g_purged);
    log_stack("  call stack", ebp_);
    if (g_purecall)
        g_purecall();
}

/* ARMADA_TEST_INJECT_STEP / ARMADA_TEST_INJECT_ORDER: after that simulation step, give every
   ship the order through the mission API CommandAllShips (0x436cb0, exported
   ?CommandAllShips@@YAXW4AiCommand@@HPBD_N2@Z), on every node at the same step, as a mission
   script would. Order 23 sends ships to the nearest shipyard (CraftProcess slot 23). */
typedef void (__cdecl *cmdall_fn)(int order, int player, const char *cls, int armed_only, int skip_flag);
static unsigned g_inject_step, g_inject_order, g_inject_repeat;

static void __stdcall hooked_step(int ms)
{
    g_step(ms);
    g_steps++;
    if (g_inject_step && g_steps >= g_inject_step &&
        (g_steps == g_inject_step || (g_inject_repeat && (g_steps - g_inject_step) % g_inject_repeat == 0))) {
        ((cmdall_fn)0x436cb0)((int)g_inject_order, -1, NULL, 0, 0);
        log_line("step %u: CommandAllShips(%u) injected", g_steps, g_inject_order);
    }
    if (g_dump_every && g_steps % g_dump_every == 0)
        dump_state(g_steps);
    if (g_exit_after && g_steps >= g_exit_after)
        TerminateProcess(GetCurrentProcess(), 0);
}

static HWND WINAPI local_FindWindowA(LPCSTR cls, LPCSTR title)
{
    if (cls && lstrcmpiA(cls, "Armada") == 0)
        return NULL;
    return FindWindowA(cls, title);
}

static void install_test_hooks(HMODULE exe)
{
    static const BYTE prolog[5] = { 0x55, 0x8b, 0xec, 0x51, 0x57 };   /* 0x43f880 */
    BYTE *target = (BYTE *)0x43f880, *t;
    DWORD prot;
    char dir[MAX_PATH];
    int i;

    g_dump_every = env_uint("ARMADA_TEST_DUMP_EVERY");
    g_inject_step = env_uint("ARMADA_TEST_INJECT_STEP");
    g_inject_order = env_uint("ARMADA_TEST_INJECT_ORDER");
    g_inject_repeat = env_uint("ARMADA_TEST_INJECT_REPEAT");
    g_exit_after = env_uint("ARMADA_TEST_EXIT_AFTER");
    if (GetEnvironmentVariableA("ARMADA_TEST_DUMP_DIR", dir, sizeof(dir)) > 0)
        lstrcpynA(g_dump_dir, dir, sizeof(g_dump_dir));
    if (env_uint("ARMADA_TEST_MULTI") == 1)
        patch_import(exe, "USER32.dll", "FindWindowA", (void *)local_FindWindowA);
    stay_in_background(exe);
    install_test_mute();
    install_test_window_renderer();
    install_virtual_input(exe);
    g_cbt = SetWindowsHookExA(WH_CBT, cbt_proc, NULL, GetCurrentThreadId());
    install_dock_counters();
    install_o8_counter();
    g_purecall = (purecall_fn)GetProcAddress(GetModuleHandleA("msvcrt.dll"), "_purecall");
    patch_import(exe, "MSVCRT.dll", "_purecall", (void *)local_purecall);
    for (i = 0; i < 5; i++)
        if (target[i] != prolog[i])
            return;                     /* not the GOG 1.2 build */
    t = (BYTE *)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t)
        return;
    for (i = 0; i < 5; i++)
        t[i] = prolog[i];
    t[5] = 0xE9;
    *(DWORD *)(t + 6) = (DWORD)((target + 5) - (t + 10));
    g_step = (step_fn)t;
    if (VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &prot)) {
        target[0] = 0xE9;
        *(DWORD *)(target + 1) = (DWORD)((BYTE *)hooked_step - (target + 5));
        VirtualProtect(target, 5, prot, &prot);
        FlushInstructionCache(GetCurrentProcess(), target, 5);
    }
}
#endif

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        HMODULE exe = GetModuleHandleA(NULL);
        HMODULE user32 = GetModuleHandleA("user32.dll");
        DisableThreadLibraryCalls(inst);
        g_real_SetCursorPos = (setcursorpos_fn)GetProcAddress(user32, "SetCursorPos");
        g_real_ClipCursor = (clipcursor_fn)GetProcAddress(user32, "ClipCursor");
        g_real_SetForegroundWindow = (foreground_fn)GetProcAddress(user32, "SetForegroundWindow");
        g_real_SetFocus = (focus_fn)GetProcAddress(user32, "SetFocus");
        InitializeCriticalSection(&g_lock);
        patch_import(exe, "USER32.dll", "SetSystemCursor", (void *)local_SetSystemCursor);
        patch_import(exe, "KERNEL32.dll", "LoadLibraryA", (void *)local_LoadLibraryA);
        patch_import(exe, "KERNEL32.dll", "CreateMutexA", (void *)local_CreateMutexA);
        install_graphics_wait_fix(exe);
        patch_import(exe, "USER32.dll", "RegisterClassA", (void *)local_RegisterClassA);
        patch_import(exe, "USER32.dll", "SetCursorPos", (void *)local_SetCursorPos);
        g_main_thread = GetCurrentThreadId();
#ifdef ARMADA_TESTHOOKS
        install_test_hooks(exe);
        if (env_uint("ARMADA_TEST_NO_LIGHTFIX") != 1)
#endif
        install_light_fix();
    }
    return TRUE;
}

/* Marker export so the installer can recognise this proxy. */
__declspec(dllexport) const char ArmadaCursorFix[] = "ArmadaCursorFix 1.3.1 (cursor, ddraw mapping and graphics Mutex isolation, light lifetime, window close, mouse and focus guards, lost-device color-fill and depth-readback guards)";
