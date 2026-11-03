/*
 * Strlkup.dll proxy for Star Trek: Armada - runtime fixes for windowed play.
 *
 * The proxy forwards the exports of the original Strlkup.dll (renamed to
 * Strlkup_orig.dll; linker pragmas below keep the original ordinals) and patches
 * three imports of Armada.exe when it loads:
 *
 *   SetSystemCursor  Armada shows its mouse cursors by replacing the system-wide
 *                    arrow cursor (SetSystemCursor(hcur, OCR_NORMAL)). In a window
 *                    that changes the arrow of the whole desktop, and after a crash
 *                    or a forced exit it stays until the next logon. The replacement
 *                    sets the cursor as the class cursor of the game's own windows.
 *   RegisterClassA   The game window ("Armada") ends the process on WM_CLOSE instead of
 *                    running on without a window (title bar X, Alt+F4).
 *   LoadLibraryA     Once the GOG DirectX wrapper (ddraw.dll) is loaded, its
 *                    session-wide shared memory name is replaced in memory by a name
 *                    unique to this process (isolate_ddraw_mapping), so other games
 *                    that use the same wrapper cannot crash it.
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

static HMODULE WINAPI local_LoadLibraryA(LPCSTR name)
{
    HMODULE h = LoadLibraryA(name);
    EnterCriticalSection(&g_lock);
    isolate_ddraw_mapping();
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

static LRESULT CALLBACK game_wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_CLOSE) {
        TerminateProcess(GetCurrentProcess(), 0);
        return 0;
    }
    return CallWindowProcA(g_game_wndproc, hwnd, msg, wp, lp);
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
    char path[MAX_PATH + 32];
    void *f;
    if (!f_open || !f_close || !f_printf)
        return;
    wsprintfA(path, "%s\\step_%06u.txt", g_dump_dir, step);
    if ((f = f_open(path, "w")) == NULL)
        return;
    f_printf(f, "step %u synced_rng %08lx table_index %lu\n", step,
             *(DWORD *)0x67dc98, *(DWORD *)0x67dc9c);
    f_printf(f, "docking_angle_draws %ld %ld %ld\n", g_dock_count[0], g_dock_count[1], g_dock_count[2]);
    ((dump_fn)0x46f190)(f);
    ((dump_fn)0x50bb20)(f);
    ((dump_fn)0x4edde0)(f);
    f_close(f);
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

static void __stdcall hooked_step(int ms)
{
    g_step(ms);
    g_steps++;
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
    g_exit_after = env_uint("ARMADA_TEST_EXIT_AFTER");
    if (GetEnvironmentVariableA("ARMADA_TEST_DUMP_DIR", dir, sizeof(dir)) > 0)
        lstrcpynA(g_dump_dir, dir, sizeof(g_dump_dir));
    if (env_uint("ARMADA_TEST_MULTI") == 1)
        patch_import(exe, "USER32.dll", "FindWindowA", (void *)local_FindWindowA);
    install_dock_counters();
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
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_lock);
        patch_import(exe, "USER32.dll", "SetSystemCursor", (void *)local_SetSystemCursor);
        patch_import(exe, "KERNEL32.dll", "LoadLibraryA", (void *)local_LoadLibraryA);
        patch_import(exe, "USER32.dll", "RegisterClassA", (void *)local_RegisterClassA);
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
__declspec(dllexport) const char ArmadaCursorFix[] = "ArmadaCursorFix 1.2 (cursor, ddraw mapping isolation, light lifetime, window close)";
