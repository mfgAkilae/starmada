/* Controlled negative replay of the two remaining original GetRenderTarget uses.
   Includes the existing native fixture; no GPU or desktop input is used. */
#define main archived_color_test_main
#include "test_ddraw_render_target.c"
#undef main

static __declspec(naked) void depth_fragment(void)
{
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        sub esp, 0x300
        mov eax, initial_output
        mov [esp + 0x48], eax
        mov [esp + 0x50], eax
        xor esi, esi
        call entry
        add esp, 0x300
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}

int main(int argc, char **argv)
{
    HMODULE module;
    char path[MAX_PATH];
    const DWORD sites[] = {0x2b736, 0x36d3f};
    const DWORD stale[] = {0, 0x3f800000, (DWORD)(ULONG_PTR)&surface_without_vtable};
    DWORD previous, ignored;
    unsigned k, i;
    BYTE saved;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc != 2 || !GetFullPathNameA(argv[1], sizeof(path), path, NULL) ||
        !(module = LoadLibraryExA(path, NULL, DONT_RESOLVE_DLL_REFERENCES))) return 2;
    base = (BYTE *)module;
    device_vtable[0x98 / 4] = (void *)get_target;
    surface_vtable[2] = (void *)release_target;
    *(void **)(base + 0x460724) = &device;
    if (!install_ddraw_render_target_fix(module)) return 3;
    for (k = 0; k < 2; k++) {
        if (!VirtualProtect(base + sites[k] - 14, 32, PAGE_EXECUTE_READWRITE, &previous)) return 4;
        saved = base[sites[k] + 16];
        base[sites[k] + 16] = 0xc3;
        FlushInstructionCache(GetCurrentProcess(), base + sites[k] + 16, 1);
        entry = base + sites[k] - 14;
        for (i = 0; i < 3; i++) {
            result = (HRESULT)0x88760866;
            write_output = FALSE;
            initial_output = stale[i];
            gets = releases = sequence = 0;
            arguments_ok = TRUE;
            observed_exception = 0;
            __try { depth_fragment(); }
            __except(EXCEPTION_EXECUTE_HANDLER) { observed_exception = GetExceptionCode(); }
            if (observed_exception != EXCEPTION_ACCESS_VIOLATION || gets != 1 || releases || !arguments_ok) return 5;
        }
        result = S_OK;
        write_output = TRUE;
        gets = releases = sequence = 0;
        arguments_ok = TRUE;
        depth_fragment();
        if (!arguments_ok || sequence != 12 || gets != 1 || releases != 1) return 6;
        printf("CONFIRMED: original depth readback RVA %lx crashes on failed GetRenderTarget; successful prefix works; v1.3.0 color Guards are installed\n", sites[k]);
        base[sites[k] + 16] = saved;
        VirtualProtect(base + sites[k] - 14, 32, previous, &ignored);
    }
    return 0;
}
