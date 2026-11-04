/* Execute the original GOG color-fill blocks with a controlled D3D9 interface.
   The original wrapper DLL is mapped without executing its DllMain. No GPU,
   game Process, screen mode or desktop input is used by this regression.
   All five color-fill routines (one per surface slot) are exercised, original
   and guarded. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "../src/strlkup_proxy/strlkup_proxy.c"

typedef struct { void **vtable; } object;
static void *device_vtable[120], *surface_vtable[3];
static object device = { device_vtable }, old_surface = { surface_vtable }, new_surface = { surface_vtable };
static object surface_without_vtable;
static BYTE surface_context[0x8b0];
static BYTE *entry, *base;
static DWORD expected_di, initial_output, before_sp, after_sp, before_bp, after_bp, after_bx, after_si, after_di;
static HRESULT result;
static BOOL write_output, output_was_null;
static unsigned gets, releases, sets, clears, sequence;
static DWORD observed_exception;
static BOOL arguments_ok;

static HRESULT WINAPI get_target(object *self, DWORD index, void **output)
{
    ++gets;
    arguments_ok = arguments_ok && self == &device && index == 0;
    output_was_null = *output == NULL;
    if (write_output)
        *output = &old_surface;
    sequence = sequence * 10 + 1;
    return result;
}

static ULONG WINAPI release_target(object *self)
{
    ++releases;
    arguments_ok = arguments_ok && self == &old_surface;
    sequence = sequence * 10 + 2;
    return 2;
}

static HRESULT WINAPI set_target(object *self, DWORD index, void *surface)
{
    ++sets;
    arguments_ok = arguments_ok && self == &device && index == 0 &&
                   surface == (sets == 1 ? &new_surface : &old_surface);
    sequence = sequence * 10 + (sets == 1 ? 3 : 5);
    return S_OK;
}

static HRESULT WINAPI clear_target(object *self, DWORD count, void *rectangles,
                                  DWORD flags, DWORD color, float depth, DWORD stencil)
{
    ++clears;
    arguments_ok = arguments_ok && self == &device && count == 1 && rectangles != NULL &&
                   flags == 1 && color == 0x00c0ffee && depth == 0 && stencil == 0;
    sequence = sequence * 10 + 4;
    return S_OK;
}

/* The routines read the surface context from [esp+0x1e0] (one variant [esp+0x1dc])
   after the call below pushed its return address. */
static __declspec(naked) void run_fragment(void)
{
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        sub esp, 0x220
        mov before_sp, esp
        mov before_bp, ebp
        mov eax, initial_output
        mov [esp + 0x44], eax
        lea eax, surface_context
        mov [esp + 0x1dc], eax
        mov [esp + 0x1d8], eax
        lea ecx, device
        mov ebx, 0x12345678
        mov esi, 0x00c0ffee
        mov edi, 0x76543210
        call entry
        mov after_sp, esp
        mov after_bp, ebp
        mov after_bx, ebx
        mov after_si, esi
        mov after_di, edi
        add esp, 0x220
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}

static void exercise(HRESULT hr, BOOL output, DWORD stale)
{
    result = hr;
    write_output = output;
    initial_output = stale;
    gets = releases = sets = clears = sequence = 0;
    before_sp = after_sp = before_bp = after_bp = 0;
    arguments_ok = TRUE;
    output_was_null = FALSE;
    observed_exception = 0;
    __try {
        run_fragment();
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        observed_exception = GetExceptionCode();
    }
}

static BOOL abi_ok(void)
{
    return !observed_exception && arguments_ok && before_sp == after_sp && before_bp == after_bp &&
           after_bx == 0x12345678 && after_si == 0x00c0ffee && after_di == expected_di;
}

static void stop_at(DWORD rva, BYTE value)
{
    base[rva] = value;
    FlushInstructionCache(GetCurrentProcess(), base + rva, 1);
}

/* Entry 10 bytes before the call; the GPU clear ends 0x5f bytes after it, the skip
   target is the wrapper's own "no GPU clear" branch target. Both get a ret. */
static int run_site(unsigned k, BOOL guarded)
{
    const HRESULT failures[] = { (HRESULT)0x8876086c, (HRESULT)0x88760866, (HRESULT)0x88760868, E_FAIL };
    const DWORD stale[] = { 0, 0x3f800000, (DWORD)(ULONG_PTR)&surface_without_vtable };
    DWORD site = g_render_target_sites[k].site, skip = g_render_target_sites[k].skip;
    DWORD success_di = site == 0x398b6 ? 0x76543210 : (DWORD)(ULONG_PTR)surface_context;
    BYTE saved_skip = base[skip], saved_end = base[site + 0x5f];
    unsigned i;
    entry = base + site - 0xa;
    stop_at(skip, 0xc3);
    stop_at(site + 0x5f, 0xc3);
    if (!guarded) {
        for (i = 0; i < sizeof(stale) / sizeof(stale[0]); i++) {
            expected_di = 0x76543210;
            exercise(failures[0], FALSE, stale[i]);
            if (observed_exception != EXCEPTION_ACCESS_VIOLATION || gets != 1 || releases || sets || clears) {
                printf("FAIL: site %lx baseline did not reproduce invalid Release, stale=%lx exception=%lx\n",
                       site, stale[i], observed_exception);
                return 1;
            }
        }
    } else {
        for (i = 0; i < sizeof(failures) / sizeof(failures[0]); i++) {
            expected_di = 0x76543210;
            exercise(failures[i], FALSE, stale[i % 3]);
            if (!abi_ok() || !output_was_null || gets != 1 || releases || sets || clears || sequence != 1) {
                printf("FAIL: site %lx failed GetRenderTarget did not skip the complete GPU clear\n", site);
                return 1;
            }
        }
        expected_di = 0x76543210;
        exercise(S_OK, FALSE, 0x3f800000);
        if (!abi_ok() || !output_was_null || sequence != 1) {
            printf("FAIL: site %lx successful NULL output was dereferenced\n", site);
            return 1;
        }
    }
    for (i = 0; i < 2; i++) {
        expected_di = success_di;
        exercise(i ? S_FALSE : S_OK, TRUE, 0x3f800000);
        if (!abi_ok() || sequence != 12345 || gets != 1 || releases != 1 || sets != 2 || clears != 1 ||
            (guarded && !output_was_null)) {
            printf("FAIL: site %lx successful clear, reference count or ABI changed\n", site);
            return 1;
        }
    }
    stop_at(skip, saved_skip);
    stop_at(site + 0x5f, saved_end);
    return 0;
}

int main(int argc, char **argv)
{
    char path[MAX_PATH];
    HMODULE wrapper;
    void *reservation = NULL;
    BYTE saved_sites[RT_SITES][6], saved_tail, *installed;
    IMAGE_NT_HEADERS *nt;
    DWORD old_text, old_header, ignored, original_stamp;
    unsigned k;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc == 3 && strcmp(argv[2], "--relocate") == 0) {
        reservation = VirtualAlloc((void *)0x18000000, 0x561000, MEM_RESERVE, PAGE_NOACCESS);
        if (!reservation)
            return puts("FAIL: cannot reserve the preferred wrapper address for relocation test"), 1;
    }
    if ((argc != 2 && !reservation) || !GetFullPathNameA(argv[1], sizeof(path), path, NULL) ||
        !(wrapper = LoadLibraryExA(path, NULL, DONT_RESOLVE_DLL_REFERENCES))) {
        puts("FAIL: pass the original GOG DDRAW.DLL path");
        return 1;
    }
    base = (BYTE *)wrapper;
    if (reservation && base == (BYTE *)0x18000000)
        return puts("FAIL: wrapper did not relocate"), 1;
    nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != 0x61dd5c00 || nt->OptionalHeader.SizeOfImage != 0x561000 ||
        !VirtualProtect(base + 0x27000, 0x13000, PAGE_EXECUTE_READWRITE, &old_text) ||
        !VirtualProtect(nt, sizeof(*nt), PAGE_READWRITE, &old_header)) {
        puts("FAIL: unsupported GOG wrapper or image protection");
        return 1;
    }
    for (k = 0; k < RT_SITES; k++)
        memcpy(saved_sites[k], base + g_render_target_sites[k].site, 6);
    saved_tail = base[0x39915];
    device_vtable[0x98 / 4] = (void *)get_target;
    device_vtable[0x94 / 4] = (void *)set_target;
    device_vtable[0xac / 4] = (void *)clear_target;
    surface_vtable[2] = (void *)release_target;
    for (k = 0; k < 5; k++)
        *(void **)(surface_context + 0x898 + 4 * k) = &new_surface;
    *(void **)(base + 0x460724) = &device;

    /* Original code: every block dereferences the unchecked output. */
    for (k = 0; k < RT_SITES; k++)
        if (run_site(k, FALSE))
            return 1;
    printf("PASS: original GOG code reproduces invalid-Pointer Access Violations at all %d color-fill sites\n",
           RT_SITES);

    original_stamp = nt->FileHeader.TimeDateStamp;
    nt->FileHeader.TimeDateStamp ^= 1;
    if (install_ddraw_render_target_fix(wrapper) || memcmp(saved_sites[4], base + 0x398b6, 6))
        return puts("FAIL: wrong build modified"), 1;
    nt->FileHeader.TimeDateStamp = original_stamp;
    base[0x398b6] ^= 1;
    if (install_ddraw_render_target_fix(wrapper) || memcmp(saved_sites[0], base + 0x27bab, 6))
        return puts("FAIL: changed call signature accepted"), 1;
    base[0x398b6] ^= 1;
    base[0x27b9d] ^= 1;   /* rel32 of the wrapper's own skip branch before 0x27bab */
    if (install_ddraw_render_target_fix(wrapper) || memcmp(saved_sites[4], base + 0x398b6, 6))
        return puts("FAIL: changed skip branch accepted"), 1;
    base[0x27b9d] ^= 1;
    base[0x39915] ^= 1;
    if (install_ddraw_render_target_fix(wrapper) || memcmp(saved_sites[4], base + 0x398b6, 6))
        return puts("FAIL: changed continuation accepted"), 1;
    base[0x39915] = saved_tail;
    puts("PASS: unknown build, call signature, skip branch and continuation leave every site unpatched");

    if (!install_ddraw_render_target_fix(wrapper))
        return puts("FAIL: known wrapper guard not installed"), 1;
    installed = g_render_target_thunk;
    if (!install_ddraw_render_target_fix(wrapper) || g_render_target_thunk != installed)
        return puts("FAIL: repeated install is not idempotent"), 1;
    for (k = 0; k < RT_SITES; k++)
        if (run_site(k, TRUE))
            return 1;
    printf("PASS: at all %d sites HRESULT failures and NULL output skip Release, SetRenderTarget and Clear;\n"
           "      successful calls keep the sequence, one Release, arguments and nonvolatile registers\n",
           RT_SITES);

    /* This Process owns the mapped test image. Nothing on disk was patched. */
    for (k = 0; k < RT_SITES; k++)
        memcpy(base + g_render_target_sites[k].site, saved_sites[k], 6);
    VirtualProtect(base + 0x27000, 0x13000, old_text, &ignored);
    VirtualProtect(nt, sizeof(*nt), old_header, &ignored);
    FreeLibrary(wrapper);
    if (reservation) {
        VirtualFree(reservation, 0, MEM_RELEASE);
        puts("PASS: runtime Guard and original wrapper execute at a relocated module address");
    }
    return 0;
}
