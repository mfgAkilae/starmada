/*
 * Strlkup.dll proxy for Star Trek: Armada - runtime fixes for windowed play.
 *
 * The proxy forwards the exports of the original Strlkup.dll (renamed to
 * Strlkup_orig.dll; linker pragmas below keep the original ordinals) and patches
 * two imports of Armada.exe when it loads:
 *
 *   SetSystemCursor  Armada shows its mouse cursors by replacing the system-wide
 *                    arrow cursor (SetSystemCursor(hcur, OCR_NORMAL)). In a window
 *                    that changes the arrow of the whole desktop, and after a crash
 *                    or a forced exit it stays until the next logon. The replacement
 *                    sets the cursor as the class cursor of the game's own windows.
 *   LoadLibraryA     Once the GOG DirectX wrapper (ddraw.dll) is loaded, its
 *                    session-wide shared memory name is replaced in memory by a name
 *                    unique to this process (isolate_ddraw_mapping), so other games
 *                    that use the same wrapper cannot crash it.
 *
 * It does not touch game logic and works with any Armada.exe build that imports
 * these functions.
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

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        HMODULE exe = GetModuleHandleA(NULL);
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_lock);
        patch_import(exe, "USER32.dll", "SetSystemCursor", (void *)local_SetSystemCursor);
        patch_import(exe, "KERNEL32.dll", "LoadLibraryA", (void *)local_LoadLibraryA);
    }
    return TRUE;
}

/* Marker export so the installer can recognise this proxy. */
__declspec(dllexport) const char ArmadaCursorFix[] = "ArmadaCursorFix 1.1 (cursor, ddraw mapping isolation)";
