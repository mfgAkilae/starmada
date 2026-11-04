/* Execute the two original GOG depth-readback prefixes with a controlled D3D9
   interface. The failure path returns through the complete original Lock frame.
   Success stops immediately after the original Release; it does not exercise GPU
   readback. No GPU, window, screen mode, focus or desktop input is used. */
#define main archived_color_test_main
#include "test_ddraw_render_target.c"
#undef main

#define DEPTH_SITES 2
#define INTERNAL_SKIP_CS 0x10000000
#define DEPTH_FAILURE ((HRESULT)0x887601c2)
#define PREFIX_SUCCESS 0x005f0110

static const struct { DWORD site, dirty, lock_active, lock_flags; } depth_sites[DEPTH_SITES] = {
    { 0x2b736, 0x898, 0x88c, 0x890 }, { 0x36d3f, 0x88c, 0x880, 0x884 }
};
static void *depth_entry;
static DWORD depth_flags, depth_return, depth_continuations;
static BYTE depth_context_before[sizeof(surface_context)], depth_desc[124];
static RECT depth_rect;
static CRITICAL_SECTION *depth_cs;
static unsigned depth_cases;

/* Original prolog order and offsets are part of the failure-return ABI. The
   fragment must receive a JMP: an extra return address would corrupt its frame. */
static __declspec(naked) void depth_frame_a(void)
{
    __asm {
        sub esp, 0x22c
        push ebx
        push ebp
        push esi
        push edi
        mov eax, [esp + 0x24c]
        and eax, INTERNAL_SKIP_CS
        mov [esp + 0xa0], eax
        mov eax, initial_output
        mov [esp + 0x4c], eax
        xor esi, esi
        jmp entry
    }
}

static __declspec(naked) void depth_frame_b(void)
{
    __asm {
        sub esp, 0x230
        push ebx
        push ebp
        push esi
        push edi
        mov eax, [esp + 0x250]
        and eax, INTERNAL_SKIP_CS
        mov [esp + 0xa4], eax
        mov eax, initial_output
        mov [esp + 0x54], eax
        xor esi, esi
        jmp entry
    }
}

/* Test-only exits after the original Release, before any GPU continuation. */
static __declspec(naked) void depth_success_a(void)
{
    __asm {
        inc depth_continuations
        pop edi
        pop esi
        pop ebp
        pop ebx
        mov eax, PREFIX_SUCCESS
        add esp, 0x22c
        ret 20
    }
}

static __declspec(naked) void depth_success_b(void)
{
    __asm {
        inc depth_continuations
        pop edi
        pop esi
        pop ebp
        pop ebx
        mov eax, PREFIX_SUCCESS
        add esp, 0x230
        ret 20
    }
}

static __declspec(naked) void call_depth_lock(void)
{
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        mov before_sp, esp
        mov ebp, 0x0badbeef
        mov ebx, 0x12345678
        mov esi, 0x00c0ffee
        mov edi, 0x76543210
        push 0x11223344
        push depth_flags
        lea eax, depth_desc
        push eax
        lea eax, depth_rect
        push eax
        lea eax, surface_context
        push eax
        call depth_entry
        mov depth_return, eax
        mov after_sp, esp
        mov after_bp, ebp
        mov after_bx, ebx
        mov after_si, esi
        mov after_di, edi
        mov esp, before_sp
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}

static BOOL depth_abi_ok(void)
{
    return !observed_exception && arguments_ok && before_sp == after_sp &&
           after_bp == 0x0badbeef && after_bx == 0x12345678 &&
           after_si == 0x00c0ffee && after_di == 0x76543210;
}

static BOOL context_ok(unsigned k, BOOL failed)
{
    BYTE expected[sizeof(surface_context)];
    memcpy(expected, depth_context_before, sizeof(expected));
    if (failed)
        *(DWORD *)(expected + depth_sites[k].dirty) = 1;
    return memcmp(surface_context, expected, sizeof(expected)) == 0;
}

static BOOL cs_depth_ok(unsigned depth)
{
    return depth_cs->RecursionCount == (LONG)depth &&
           depth_cs->OwningThread == (depth ? (HANDLE)(ULONG_PTR)GetCurrentThreadId() : NULL);
}

static void reset_cs(void)
{
    while (depth_cs->RecursionCount > 0 &&
           depth_cs->OwningThread == (HANDLE)(ULONG_PTR)GetCurrentThreadId())
        LeaveCriticalSection(depth_cs);
}

static BOOL exercise_depth(unsigned k, HRESULT hr, BOOL output, DWORD stale,
                           BOOL skip_cs, unsigned preexisting, BOOL guarded)
{
    unsigned i, acquired = preexisting + (skip_cs ? 0 : 1);
    BOOL ok;
    reset_cs();
    for (i = 0; i < acquired; i++)
        EnterCriticalSection(depth_cs);
    memset(surface_context, 0xa5, sizeof(surface_context));
    *(DWORD *)(surface_context + depth_sites[k].dirty) = 0;
    *(DWORD *)(surface_context + depth_sites[k].lock_active) = 0;
    *(DWORD *)(surface_context + depth_sites[k].lock_flags) = 0x2468ace0;
    memcpy(depth_context_before, surface_context, sizeof(surface_context));
    memset(depth_desc, 0x5a, sizeof(depth_desc));
    depth_flags = 0x00000801 | (skip_cs ? INTERNAL_SKIP_CS : 0);
    entry = base + depth_sites[k].site - 14;
    depth_entry = k ? (void *)depth_frame_b : (void *)depth_frame_a;
    result = hr;
    write_output = output;
    initial_output = stale;
    gets = releases = sets = clears = sequence = 0;
    before_sp = after_sp = after_bp = after_bx = after_si = after_di = 0;
    depth_return = depth_continuations = observed_exception = 0;
    arguments_ok = TRUE;
    output_was_null = FALSE;
    __try {
        call_depth_lock();
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        observed_exception = GetExceptionCode();
    }
    if (!guarded && !output) {
        ok = observed_exception == EXCEPTION_ACCESS_VIOLATION && arguments_ok &&
             gets == 1 && releases == 0 && sequence == 1 && !depth_continuations &&
             !sets && !clears && context_ok(k, FALSE) && cs_depth_ok(acquired);
    } else if (guarded && (FAILED(hr) || !output)) {
        ok = depth_abi_ok() && depth_return == DEPTH_FAILURE && output_was_null &&
             gets == 1 && releases == 0 && sequence == 1 && !depth_continuations &&
             !sets && !clears && context_ok(k, TRUE) && cs_depth_ok(preexisting);
    } else {
        ok = depth_abi_ok() && depth_return == PREFIX_SUCCESS &&
             (!guarded || output_was_null) && gets == 1 && releases == 1 &&
             sequence == 12 && depth_continuations == 1 && !sets && !clears &&
             context_ok(k, FALSE) && cs_depth_ok(acquired);
    }
    if (!ok)
        printf("FAIL: depth RVA %lx hr=%lx output=%d stale=%lx skip-CS=%d depth=%u guarded=%d; "
               "exception=%lx return=%lx gets=%u releases=%u continuation=%lu sequence=%u "
               "ESP=%lx/%lx CS=%ld\n", depth_sites[k].site, (DWORD)hr, output, stale,
               skip_cs, preexisting, guarded, observed_exception, depth_return,
               gets, releases, depth_continuations, sequence, before_sp, after_sp,
               depth_cs->RecursionCount);
    reset_cs();
    ++depth_cases;
    return ok;
}

static void patch_depth_exit(unsigned k, const BYTE *saved)
{
    BYTE *continuation = base + depth_sites[k].site + 16;
    if (saved) {
        memcpy(continuation, saved, 5);
    } else {
        continuation[0] = 0xe9;
        *(DWORD *)(continuation + 1) =
            (DWORD)(ULONG_PTR)(k ? (void *)depth_success_b : (void *)depth_success_a) -
            (DWORD)(ULONG_PTR)(continuation + 5);
    }
    FlushInstructionCache(GetCurrentProcess(), continuation, 5);
}

static BOOL sites_equal(const BYTE saved[DEPTH_SITES][6])
{
    unsigned k;
    for (k = 0; k < DEPTH_SITES; k++)
        if (memcmp(saved[k], base + depth_sites[k].site, 6))
            return FALSE;
    return TRUE;
}

int main(int argc, char **argv)
{
    const HRESULT failures[] = { (HRESULT)0x88760868, (HRESULT)0x8876086c, E_FAIL, S_OK };
    const DWORD stale[] = { 0, 0x3f800000, (DWORD)(ULONG_PTR)&surface_without_vtable };
    char path[MAX_PATH];
    HMODULE wrapper;
    void *reservation = NULL;
    IMAGE_NT_HEADERS *nt;
    BYTE saved_sites[DEPTH_SITES][6], installed_sites[DEPTH_SITES][6];
    BYTE saved_continuations[DEPTH_SITES][5];
    DWORD old_text, old_header, old_iat, ignored, original_stamp;
    void *saved_leave;
    unsigned k, i, j, skip, depth;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc == 3 && strcmp(argv[2], "--relocate") == 0) {
        reservation = VirtualAlloc((void *)0x18000000, 0x561000, MEM_RESERVE, PAGE_NOACCESS);
        if (!reservation)
            return puts("FAIL: cannot reserve the preferred wrapper address for relocation test"), 1;
    }
    if ((argc != 2 && !reservation) || !GetFullPathNameA(argv[1], sizeof(path), path, NULL) ||
        !(wrapper = LoadLibraryExA(path, NULL, DONT_RESOLVE_DLL_REFERENCES)))
        return puts("FAIL: pass the original GOG DDRAW.DLL path"), 1;
    base = (BYTE *)wrapper;
    if (reservation && base == (BYTE *)0x18000000)
        return puts("FAIL: wrapper did not relocate"), 1;
    nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != 0x61dd5c00 || nt->OptionalHeader.SizeOfImage != 0x561000 ||
        !VirtualProtect(base + 0x27000, 0x13000, PAGE_EXECUTE_READWRITE, &old_text) ||
        !VirtualProtect(nt, sizeof(*nt), PAGE_READWRITE, &old_header) ||
        !VirtualProtect(base + 0x54e780, sizeof(void *), PAGE_READWRITE, &old_iat))
        return puts("FAIL: unsupported GOG wrapper or image protection"), 1;
    depth_cs = (CRITICAL_SECTION *)(base + 0x176da0);
    InitializeCriticalSection(depth_cs);
    saved_leave = *(void **)(base + 0x54e780);
    *(void **)(base + 0x54e780) = (void *)LeaveCriticalSection;
    device_vtable[0x98 / 4] = (void *)get_target;
    surface_vtable[2] = (void *)release_target;
    *(void **)(base + 0x460724) = &device;
    for (k = 0; k < DEPTH_SITES; k++) {
        memcpy(saved_sites[k], base + depth_sites[k].site, 6);
        memcpy(saved_continuations[k], base + depth_sites[k].site + 16, 5);
        patch_depth_exit(k, NULL);
    }
    for (k = 0; k < DEPTH_SITES; k++) {
        for (i = 0; i < sizeof(stale) / sizeof(stale[0]); i++)
            for (skip = 0; skip < 2; skip++)
                for (depth = 0; depth <= 2; depth += 2)
                    if (!exercise_depth(k, failures[0], FALSE, stale[i], skip, depth, FALSE))
                        return 1;
        if (!exercise_depth(k, S_OK, TRUE, 0x3f800000, FALSE, 2, FALSE))
            return 1;
        patch_depth_exit(k, saved_continuations[k]);
    }
    puts("PASS: both original depth-readback prefixes reproduce invalid-Pointer Access Violations; fixture CS restored");

    original_stamp = nt->FileHeader.TimeDateStamp;
    nt->FileHeader.TimeDateStamp ^= 1;
    if (install_ddraw_depth_readback_fix(wrapper) || !sites_equal(saved_sites))
        return puts("FAIL: unsupported build modified a depth-readback site"), 1;
    nt->FileHeader.TimeDateStamp = original_stamp;
    for (k = 0; k < DEPTH_SITES; k++) {
        base[depth_sites[k].site] ^= 1;
        if (install_ddraw_depth_readback_fix(wrapper) ||
            memcmp(saved_sites[1 - k], base + depth_sites[1 - k].site, 6))
            return puts("FAIL: changed GetRenderTarget signature accepted or another site modified"), 1;
        base[depth_sites[k].site] ^= 1;
        if (!sites_equal(saved_sites))
            return puts("FAIL: signature rejection modified a depth-readback site"), 1;
    }
    puts("PASS: unsupported build and either changed call signature leave both depth-readback sites unpatched");
    if (!install_ddraw_depth_readback_fix(wrapper))
        return puts("FAIL: known wrapper depth-readback guard not installed"), 1;
    for (k = 0; k < DEPTH_SITES; k++)
        memcpy(installed_sites[k], base + depth_sites[k].site, 6);
    if (sites_equal(saved_sites) || !install_ddraw_depth_readback_fix(wrapper) || !sites_equal(installed_sites))
        return puts("FAIL: depth-readback install did not patch sites or is not idempotent"), 1;
    for (k = 0; k < DEPTH_SITES; k++) {
        patch_depth_exit(k, NULL);
        for (i = 0; i < sizeof(failures) / sizeof(failures[0]); i++)
            for (j = 0; j < sizeof(stale) / sizeof(stale[0]); j++)
                for (skip = 0; skip < 2; skip++)
                    for (depth = 0; depth <= 2; depth += 2)
                        if (!exercise_depth(k, failures[i], FALSE, stale[j], skip, depth, TRUE))
                            return 1;
        for (i = 0; i < 3; i++)
            if (!exercise_depth(k, failures[i], TRUE, 0x3f800000, FALSE, 2, TRUE))
                return 1;
        for (i = 0; i < 2; i++)
            for (skip = 0; skip < 2; skip++)
                for (depth = 0; depth <= 2; depth += 2)
                    if (!exercise_depth(k, i ? S_FALSE : S_OK, TRUE, 0x3f800000, skip, depth, TRUE))
                        return 1;
        patch_depth_exit(k, saved_continuations[k]);
    }
    printf("PASS: %u native cases; failures/NULL preserve caller ESP/nonvolatile registers, initialize output,\n"
           "      restore dirty state and recursive CS depth, and skip Release/GPU continuation;\n"
           "      all other Context bytes (including lockActive/lockFlags) remain unchanged\n", depth_cases);
    puts("PASS: successful prefix only: original GetRenderTarget/Release execute once and reach the test exit; no GPU readback claimed");
    for (k = 0; k < DEPTH_SITES; k++)
        memcpy(base + depth_sites[k].site, saved_sites[k], 6);
    DeleteCriticalSection(depth_cs);
    *(void **)(base + 0x54e780) = saved_leave;
    VirtualProtect(base + 0x54e780, sizeof(void *), old_iat, &ignored);
    VirtualProtect(base + 0x27000, 0x13000, old_text, &ignored);
    VirtualProtect(nt, sizeof(*nt), old_header, &ignored);
    FreeLibrary(wrapper);
    if (reservation) {
        VirtualFree(reservation, 0, MEM_RELEASE);
        puts("PASS: depth-readback guard and original prefixes execute at a relocated module address");
    }
    return 0;
}
