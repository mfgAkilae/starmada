/*
 * Strlkup.dll proxy for Star Trek: Armada - runtime fixes for windowed play.
 *
 * The proxy forwards the exports of the original Strlkup.dll (renamed to
 * Strlkup_orig.dll; linker pragmas below keep the original ordinals) and patches
 * four imports of Armada.exe when it loads:
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

static LRESULT CALLBACK game_wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
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

/* Once ddraw.dll is loaded: replace its mouse imports (it calls them for itself and from
   its hooks of the game's imports). */
static void guard_ddraw_mouse(void)
{
    HMODULE dd;
    if (g_ddraw_mouse_done || (dd = GetModuleHandleA("ddraw.dll")) == NULL)
        return;
    g_ddraw_mouse_done = TRUE;
    patch_import(dd, "USER32.dll", "SetCursorPos", (void *)local_SetCursorPos);
    patch_import(dd, "USER32.dll", "ClipCursor", (void *)local_ClipCursor);
    patch_import(dd, "USER32.dll", "SetForegroundWindow", (void *)local_SetForegroundWindow);
    patch_import(dd, "USER32.dll", "SetFocus", (void *)local_SetFocus);
#ifdef ARMADA_TESTHOOKS
    stay_in_background(dd);
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
__declspec(dllexport) const char ArmadaCursorFix[] = "ArmadaCursorFix 1.2.0 (cursor, ddraw mapping isolation, light lifetime, window close, mouse and focus guards)";
