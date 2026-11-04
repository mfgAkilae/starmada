/* Execute the real GOG CreateDevice retry graph with controlled COM calls.
   No GPU, window creation, focus changes or input. */
#define ARMADA_TESTHOOKS
#include <assert.h>
#include <stdio.h>
#include "../src/strlkup_proxy/strlkup_proxy.c"
static BYTE *flow_entry, *mapped;
static DWORD flow_result, flow_before, flow_after;
static int flow_outcome;
static void *fake_vtable[17], *fake_object = fake_vtable;
static unsigned called;
static const DWORD *requested;
static HRESULT WINAPI fake_create(void *object, UINT adapter, DWORD type, HWND focus,
    DWORD flags, DWORD *parameters, void **output)
{
    assert(object==&fake_object && adapter==0 && type==1 && !focus);
    assert(flags==0x82 && parameters==(DWORD *)(mapped+0x468458));
    assert(output==(void **)(mapped+0x460724) && called<4);
    return (HRESULT)requested[called++];
}
static BOOL WINAPI fake_position(HWND window,HWND after,int x,int y,int width,int height,UINT flags)
{
    (void)window;(void)after;(void)x;(void)y;(void)width;(void)height;(void)flags;
    return TRUE;
}
static __declspec(naked) void finish_success(void)
{
    __asm { mov flow_result,eax }
    __asm { mov flow_outcome,1 }
    __asm { ret }
}
static __declspec(naked) void finish_failure(void)
{
    __asm { mov flow_result,eax }
    __asm { mov flow_outcome,-1 }
    __asm { ret }
}
static __declspec(naked) void run_flow(void)
{
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        mov flow_before,esp
        xor ebx,ebx
        mov esi,1
        mov edi,offset fake_position
        xor ecx,ecx
        call flow_entry
        mov flow_after,esp
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}
static void redirect(DWORD offset,void *destination)
{
    DWORD previous,ignored;
    BYTE *site=mapped+offset;
    assert(VirtualProtect(site,5,PAGE_EXECUTE_READWRITE,&previous));
    site[0]=0xe9;*(int *)(site+1)=(int)((BYTE *)destination-(site+5));
    VirtualProtect(site,5,previous,&ignored);
    FlushInstructionCache(GetCurrentProcess(),site,5);
}
int main(int argc,char **argv)
{
    static const DWORD offsets[]={0x1e87e,0x1e8e5,0x1e948,0x1e9b2};
    static const DWORD compares[]={0x1e884,0x1e8eb,0x1e94e,0x1e9b8};
    static const DWORD attempts[16][4]={
        {0},{0x8876086a},{0x80004005},
        {0x8876086c,0},{0x8876086c,0x8876086a},{0x8876086c,0x80004005},
        {0x8876086c,0x8876086c,0},{0x8876086c,0x8876086c,0x8876086a},
        {0x8876086c,0x8876086c,0x8876086c,0},
        {0x8876086c,0x8876086c,0x8876086c,0x8876086a},
        {0x88760868,0},{0x88760868,0x8876086a},
        {0x8876086c,0x88760868,0},{0x8876086c,0x88760868,0x8876086a},
        {0x8876086c,0x8876086c,0x88760868,0},
        {0x8876086c,0x8876086c,0x88760868,0x8876086a}};
    static const unsigned counts[]={1,1,1,2,2,2,3,3,4,4,2,2,3,3,4,4};
    BYTE original_compares[4][7];
    HMODULE module;
    DWORD previous,ignored;
    unsigned i;
    if(argc!=2) return 2;
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
    module=LoadLibraryExA(argv[1],NULL,DONT_RESOLVE_DLL_REFERENCES);
    if(!module) return 3;
    mapped=(BYTE *)module;
    for(i=0;i<4;i++) CopyMemory(original_compares[i],mapped+compares[i],7);
    SetEnvironmentVariableA("ARMADA_TEST_D3D_INIT_TRACE","0");
    install_test_d3d_trace(module);
    for(i=0;i<4;i++) assert(mapped[offsets[i]]==0x56);
    assert(VirtualProtect(mapped+offsets[2]+5,1,PAGE_EXECUTE_READWRITE,&previous));
    mapped[offsets[2]+5]=0x41;
    SetEnvironmentVariableA("ARMADA_TEST_D3D_INIT_TRACE","1");
    install_test_d3d_trace(module);
    for(i=0;i<4;i++) assert(mapped[offsets[i]]==0x56);
    mapped[offsets[2]+5]=0x40;
    VirtualProtect(mapped+offsets[2]+5,1,previous,&ignored);
    install_test_d3d_trace(module);
    for(i=0;i<4;i++) {
        assert(mapped[offsets[i]]==0xe9);
        /* The final CMP is also the destination of branches from earlier calls. */
        assert(!memcmp(original_compares[i],mapped+compares[i],7));
    }
    fake_vtable[16]=(void *)fake_create;
    *(void **)(mapped+0x4557b0)=&fake_object;
    *(HWND *)(mapped+0x4557c0)=NULL;
    /* Bypass the presentation-setting helper and Window positioning, retaining
       the actual CreateDevice retry graph and its comparison/branch targets. */
    assert(VirtualProtect(mapped+0x47040,3,PAGE_EXECUTE_READWRITE,&previous));
    mapped[0x47040]=0xc2;mapped[0x47041]=4;mapped[0x47042]=0;
    VirtualProtect(mapped+0x47040,3,previous,&ignored);
    redirect(0x1e9c0,(void *)finish_success);
    redirect(0x1f466,(void *)finish_failure);
    flow_entry=mapped+0x1e867;
    for(i=0;i<16;i++) {
        requested=attempts[i];called=0;flow_outcome=0;
        run_flow();
        assert(called==counts[i] && flow_before==flow_after);
        assert(flow_result==attempts[i][counts[i]-1]);
        assert(flow_outcome==(flow_result==0 ? 1 : -1));
    }
    puts("PASS: disabled/mismatched admission; original comparison/branch targets intact;");
    puts("      actual GOG retry graph with 16 success/failure sequences, all four call-sites,");
    puts("      original Arguments, HRESULT, retry counts and balanced Stack; no GPU/window/input");
    return 0;
}
