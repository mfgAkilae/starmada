#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static DWORD test_root;
static int legacy, legacy_wait;
static LPSECURITY_ATTRIBUTES last_attributes;
static BOOL last_owner, last_unnamed;
static char last_name[128];
static BOOL observe_releases;
static unsigned release_count;
static HANDLE released_handles[8];
static DWORD error_before_release, error_after_finish;
static BOOL error_preserved;
static HANDLE WINAPI isolated_CreateMutexA(LPSECURITY_ATTRIBUTES attributes, BOOL owner, LPCSTR name);
static BOOL WINAPI recorded_ReleaseMutex(HANDLE mutex);

/* The native primitive uses a test-only namespace so frozen games are untouched. */
#define CreateMutexA isolated_CreateMutexA
#define ReleaseMutex recorded_ReleaseMutex
#include "../src/strlkup_proxy/strlkup_proxy.c"
#undef CreateMutexA
#undef ReleaseMutex

enum { CHILD_TIMEOUT = 42, CHILD_ABANDONED = 43, CHILD_EXIT_OWNING = 77 };

static BOOL WINAPI recorded_ReleaseMutex(HANDLE mutex)
{
    BOOL released;
    if (observe_releases) {
        if (!release_count)
            error_before_release = GetLastError();
        if (release_count < sizeof(released_handles) / sizeof(released_handles[0]))
            released_handles[release_count] = mutex;
        ++release_count;
    }
    released = ReleaseMutex(mutex);
    if (observe_releases)
        SetLastError(ERROR_NOT_SUPPORTED);
    return released;
}

static HANDLE WINAPI isolated_CreateMutexA(LPSECURITY_ATTRIBUTES attributes, BOOL owner, LPCSTR name)
{
    char scoped[256];
    last_attributes = attributes;
    last_owner = owner;
    last_unnamed = name == NULL;
    last_name[0] = '\0';
    if (name) {
        if (strcpy_s(last_name, sizeof(last_name), name) != 0 ||
            _snprintf_s(scoped, sizeof(scoped), _TRUNCATE, "Codex.Armada.RenderMutexTest.%lu.%s", test_root, name) < 0)
            return NULL;
        name = scoped;
    }
    return CreateMutexA(attributes, owner, name);
}

static HANDLE create_mutex(LPSECURITY_ATTRIBUTES attributes, BOOL owner, LPCSTR name)
{
    return legacy ? isolated_CreateMutexA(attributes, owner, name) : local_CreateMutexA(attributes, owner, name);
}

static int child_process(const char *name, const char *mode, DWORD *exit_code)
{
    char executable[MAX_PATH], command[1024];
    DWORD length, waited;
    STARTUPINFOA startup;
    PROCESS_INFORMATION process;
    length = GetModuleFileNameA(NULL, executable, sizeof(executable));
    if (!length || length >= sizeof(executable) ||
        _snprintf_s(command, sizeof(command), _TRUNCATE, "\"%s\" --child %lu %d %s \"%s\"",
                    executable, test_root, legacy, mode, name ? name : "@unnamed") < 0) {
        puts("FAIL: child command could not be constructed");
        return 0;
    }
    ZeroMemory(&startup, sizeof(startup));
    ZeroMemory(&process, sizeof(process));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    if (!CreateProcessA(executable, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &startup, &process)) {
        printf("FAIL: CreateProcessA error %lu\n", GetLastError());
        return 0;
    }
    CloseHandle(process.hThread);
    waited = WaitForSingleObject(process.hProcess, 2500);
    if (waited != WAIT_OBJECT_0) {
        TerminateProcess(process.hProcess, 99);
        WaitForSingleObject(process.hProcess, 500);
        CloseHandle(process.hProcess);
        printf("FAIL: own child did not finish within 2500 ms (wait %lu)\n", waited);
        return 0;
    }
    if (!GetExitCodeProcess(process.hProcess, exit_code)) {
        CloseHandle(process.hProcess);
        puts("FAIL: child exit code unavailable");
        return 0;
    }
    CloseHandle(process.hProcess);
    return 1;
}

static int check_contention(const char *name)
{
    HANDLE first = NULL, repeated = NULL;
    DWORD created, child_code = 0;
    int ok = 0, owned = 0;
    char expected[128];
    first = create_mutex(NULL, TRUE, name);
    created = GetLastError();
    if (!first || created == ERROR_ALREADY_EXISTS) {
        puts("FAIL: parent did not create an independent test Mutex");
        goto done;
    }
    owned = 1;
    if (legacy)
        strcpy_s(expected, sizeof(expected), name);
    else
        _snprintf_s(expected, sizeof(expected), _TRUNCATE, "%s.armada.%lu", name, GetCurrentProcessId());
    if (last_unnamed || strcmp(last_name, expected) != 0 || last_owner != TRUE || last_attributes != NULL) {
        puts("FAIL: known Mutex name or creation arguments were transformed incorrectly");
        goto done;
    }
    repeated = create_mutex(NULL, FALSE, name);
    created = GetLastError();
    if (!repeated || created != ERROR_ALREADY_EXISTS || last_owner != FALSE) {
        puts("FAIL: repeated creation in one process did not share its Mutex");
        goto done;
    }
    if (!child_process(name, "probe", &child_code))
        goto done;
    if (child_code != (DWORD)(legacy ? CHILD_TIMEOUT : 0)) {
        printf("FAIL: known Mutex child exit %lu, expected %d\n", child_code, legacy ? CHILD_TIMEOUT : 0);
        goto done;
    }
    printf("%s: %s cross-process acquire; same-process repeated creation shares\n",
           legacy ? "EXPECTED LEGACY COLLISION" : "PASS", name);
    ok = 1;
done:
    if (owned)
        ReleaseMutex(first);
    if (repeated)
        CloseHandle(repeated);
    if (first)
        CloseHandle(first);
    return ok;
}

static int check_abandonment(const char *name)
{
    HANDLE parent = create_mutex(NULL, FALSE, name);
    DWORD child_code = 0, waited;
    int ok = 0;
    if (!parent) {
        puts("FAIL: parent abandonment-test Mutex creation failed");
        return 0;
    }
    if (!child_process(name, "abandon", &child_code))
        goto done;
    if (child_code != CHILD_EXIT_OWNING) {
        printf("FAIL: child did not exit while owning its Mutex (exit %lu)\n", child_code);
        goto done;
    }
    waited = WaitForSingleObject(parent, 0);
    if (waited == WAIT_OBJECT_0 || waited == WAIT_ABANDONED_0)
        ReleaseMutex(parent);
    if (waited != (legacy ? WAIT_ABANDONED_0 : WAIT_OBJECT_0)) {
        printf("FAIL: parent acquire after child exit returned %lu\n", waited);
        goto done;
    }
    printf("%s: %s after abrupt child exit\n", legacy ? "EXPECTED LEGACY ABANDONMENT" : "PASS", name);
    ok = 1;
done:
    CloseHandle(parent);
    return ok;
}

static int check_shared_control(const char *name)
{
    HANDLE parent = create_mutex(NULL, TRUE, name);
    DWORD child_code = 0;
    int ok = 0;
    if (!parent) {
        puts("FAIL: control Mutex creation failed");
        return 0;
    }
    if (last_unnamed || strcmp(last_name, name) != 0) {
        puts("FAIL: unrelated Mutex name was changed");
        goto done;
    }
    if (!child_process(name, "probe", &child_code))
        goto done;
    if (child_code != CHILD_TIMEOUT) {
        printf("FAIL: unrelated Mutex stopped sharing between processes (child %lu)\n", child_code);
        goto done;
    }
    printf("PASS: unrelated Mutex remains shared: %s\n", name);
    ok = 1;
done:
    ReleaseMutex(parent);
    CloseHandle(parent);
    return ok;
}

static int check_unnamed(void)
{
    SECURITY_ATTRIBUTES attributes;
    HANDLE first = NULL, second = NULL;
    DWORD flags = 0, child_code = 0, created, waited;
    int ok = 0, first_owned = 0, second_owned = 0;
    ZeroMemory(&attributes, sizeof(attributes));
    attributes.nLength = sizeof(attributes);
    attributes.bInheritHandle = TRUE;
    first = create_mutex(&attributes, TRUE, NULL);
    if (!first)
        goto done;
    first_owned = 1;
    if (!last_unnamed || last_attributes != &attributes || last_owner != TRUE ||
        !GetHandleInformation(first, &flags) || !(flags & HANDLE_FLAG_INHERIT)) {
        puts("FAIL: unnamed Mutex arguments were not passed through");
        goto done;
    }
    second = create_mutex(NULL, FALSE, NULL);
    created = GetLastError();
    if (!second || created == ERROR_ALREADY_EXISTS || !last_unnamed || last_attributes != NULL || last_owner != FALSE) {
        puts("FAIL: unnamed Mutex repeated creation was not independent");
        goto done;
    }
    waited = WaitForSingleObject(second, 0);
    if (waited != WAIT_OBJECT_0) {
        puts("FAIL: second unnamed Mutex was not available");
        goto done;
    }
    second_owned = 1;
    if (!child_process(NULL, "probe", &child_code) || child_code != 0) {
        puts("FAIL: unnamed child Mutex was not independent");
        goto done;
    }
    puts("PASS: unnamed Mutexes and creation attributes pass through");
    ok = 1;
done:
    if (second_owned)
        ReleaseMutex(second);
    if (first_owned)
        ReleaseMutex(first);
    if (second)
        CloseHandle(second);
    if (first)
        CloseHandle(first);
    return ok;
}

typedef struct mutex_thread {
    HANDLE mutex, ready, finish, thread;
    DWORD result;
    BOOL abandon;
} mutex_thread;

static DWORD WINAPI hold_mutex(void *argument)
{
    mutex_thread *owner = (mutex_thread *)argument;
    owner->result = WaitForSingleObject(owner->mutex, 0);
    SetEvent(owner->ready);
    if (owner->result == WAIT_OBJECT_0 || owner->result == WAIT_ABANDONED_0) {
        if (owner->abandon)
            ExitThread(CHILD_EXIT_OWNING);
        WaitForSingleObject(owner->finish, 2500);
        ReleaseMutex(owner->mutex);
    }
    return 0;
}

static void stop_owner(mutex_thread *owner)
{
    if (owner->finish)
        SetEvent(owner->finish);
    if (owner->thread) {
        if (WaitForSingleObject(owner->thread, 1500) != WAIT_OBJECT_0) {
            puts("FAIL: own holder Thread did not stop");
            ExitProcess(2);
        }
        CloseHandle(owner->thread);
    }
    if (owner->ready)
        CloseHandle(owner->ready);
    if (owner->finish)
        CloseHandle(owner->finish);
    ZeroMemory(owner, sizeof(*owner));
}

static int start_owner(mutex_thread *owner, HANDLE mutex, BOOL abandon)
{
    ZeroMemory(owner, sizeof(*owner));
    owner->mutex = mutex;
    owner->abandon = abandon;
    owner->result = WAIT_FAILED;
    owner->ready = CreateEventA(NULL, TRUE, FALSE, NULL);
    owner->finish = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (owner->ready && owner->finish)
        owner->thread = CreateThread(NULL, 0, hold_mutex, owner, 0, NULL);
    if (!owner->thread || WaitForSingleObject(owner->ready, 1500) != WAIT_OBJECT_0 ||
        owner->result != WAIT_OBJECT_0 ||
        (abandon && WaitForSingleObject(owner->thread, 1500) != WAIT_OBJECT_0)) {
        puts("FAIL: own holder Thread did not acquire its Mutex");
        stop_owner(owner);
        return 0;
    }
    return 1;
}

static DWORD WINAPI probe_mutex(void *argument)
{
    mutex_thread *probe = (mutex_thread *)argument;
    probe->result = WaitForSingleObject(probe->mutex, 0);
    if (probe->result == WAIT_OBJECT_0 || probe->result == WAIT_ABANDONED_0)
        ReleaseMutex(probe->mutex);
    return 0;
}

static int check_probe(HANDLE mutex, DWORD expected, const char *description)
{
    mutex_thread probe;
    ZeroMemory(&probe, sizeof(probe));
    probe.mutex = mutex;
    probe.result = WAIT_FAILED;
    probe.thread = CreateThread(NULL, 0, probe_mutex, &probe, 0, NULL);
    if (!probe.thread) {
        puts("FAIL: own probe Thread could not start");
        return 0;
    }
    if (WaitForSingleObject(probe.thread, 1500) != WAIT_OBJECT_0) {
        puts("FAIL: own probe Thread did not stop");
        ExitProcess(2);
    }
    CloseHandle(probe.thread);
    if (probe.result != expected) {
        printf("FAIL: %s: independent Thread acquired %lu, expected %lu\n", description, probe.result, expected);
        return 0;
    }
    return 1;
}

static DWORD finish_wait(HANDLE waited, DWORD result, BOOL second_acquire)
{
    DWORD completed, original_error = GetLastError();
    release_count = 0;
    observe_releases = TRUE;
    completed = legacy_wait ? result : complete_graphics_wait(waited, result, second_acquire);
    error_after_finish = GetLastError();
    observe_releases = FALSE;
    error_preserved = error_after_finish == original_error;
    return completed;
}

#pragma optimize("", off)
static __declspec(noinline) DWORD wait_through_wrapper(HANDLE waited, DWORD milliseconds, BOOL second_acquire)
{
    void *previous_return = g_cursor_second_wait_return;
    DWORD result = WAIT_FAILED;
    release_count = 0;
    observe_releases = TRUE;
    __asm {
        mov eax, offset second_return
        mov g_cursor_second_wait_return, eax
        cmp second_acquire, 0
        je ordinary_call
        push milliseconds
        push waited
        call local_WaitForSingleObject
    second_return:
        mov result, eax
        jmp call_complete
    ordinary_call:
        push milliseconds
        push waited
        call local_WaitForSingleObject
        mov result, eax
    call_complete:
    }
    error_after_finish = GetLastError();
    observe_releases = FALSE;
    error_preserved = !release_count || error_after_finish == error_before_release;
    g_cursor_second_wait_return = previous_return;
    return result;
}
#pragma optimize("", on)

static int check_releases(HANDLE offscreen, unsigned expected_offscreen, HANDLE onscreen, unsigned expected_onscreen)
{
    unsigned i, offscreen_count = 0, onscreen_count = 0;
    if (!error_preserved) {
        printf("FAIL: wait cleanup changed LastError to %lu\n", error_after_finish);
        return 0;
    }
    if (release_count != expected_offscreen + expected_onscreen) {
        printf("FAIL: ReleaseMutex count %u, expected %u\n", release_count, expected_offscreen + expected_onscreen);
        return 0;
    }
    for (i = 0; i < release_count; ++i) {
        if (released_handles[i] == offscreen)
            ++offscreen_count;
        else if (released_handles[i] == onscreen)
            ++onscreen_count;
        else {
            puts("FAIL: cleanup released an unrelated handle");
            return 0;
        }
    }
    if (offscreen_count != expected_offscreen || onscreen_count != expected_onscreen) {
        puts("FAIL: cleanup did not release each expected handle exactly once");
        return 0;
    }
    return 1;
}

static int graphics_pair(HANDLE *offscreen, HANDLE *onscreen, BOOL own_offscreen)
{
    *offscreen = local_CreateMutexA(NULL, own_offscreen, "m_mutex_draw_cursor_offscreen");
    *onscreen = local_CreateMutexA(NULL, FALSE, "m_mutex_draw_cursor_onscreen");
    if (!*offscreen || !*onscreen) {
        puts("FAIL: graphics wait fixtures could not be created");
        return 0;
    }
    return 1;
}

static void release_and_close(HANDLE mutex)
{
    unsigned i;
    if (!mutex)
        return;
    for (i = 0; i < 8 && ReleaseMutex(mutex); ++i) {}
    CloseHandle(mutex);
}

static int check_second_timeout(BOOL recursive)
{
    HANDLE offscreen = NULL, onscreen = NULL;
    mutex_thread holder;
    DWORD result;
    int ok = 0;
    ZeroMemory(&holder, sizeof(holder));
    if (!graphics_pair(&offscreen, &onscreen, TRUE) || !start_owner(&holder, onscreen, FALSE))
        goto done;
    if (recursive && WaitForSingleObject(offscreen, 0) != WAIT_OBJECT_0)
        goto done;
    result = WaitForSingleObject(onscreen, 0);
    if (result != WAIT_TIMEOUT || finish_wait(onscreen, result, FALSE) != WAIT_TIMEOUT ||
        !check_releases(offscreen, 0, onscreen, 0) ||
        !check_probe(offscreen, WAIT_TIMEOUT, "first wait failure keeps existing ownership"))
        goto done;
    result = WaitForSingleObject(onscreen, 0);
    if (result != WAIT_TIMEOUT || finish_wait(onscreen, result, TRUE) != WAIT_TIMEOUT ||
        !check_releases(offscreen, legacy_wait ? 0u : 1u, onscreen, 0) ||
        !check_probe(offscreen, legacy_wait || recursive ? WAIT_TIMEOUT : WAIT_OBJECT_0,
                     "second wait failure releases the first acquire") ||
        !check_probe(onscreen, WAIT_TIMEOUT, "onscreen holder keeps its ownership"))
        goto done;
    if (recursive) {
        if (!ReleaseMutex(offscreen) || !check_probe(offscreen, legacy_wait ? WAIT_TIMEOUT : WAIT_OBJECT_0,
                                                    "exactly one recursive acquire was released"))
            goto done;
    }
    if (legacy_wait && (!ReleaseMutex(offscreen) || !check_probe(offscreen, WAIT_OBJECT_0, "legacy leak cleanup")))
        goto done;
    if (legacy_wait)
        printf("EXPECTED WAIT OWNERSHIP LEAK: failed second acquire%s retains Offscreen\n",
               recursive ? " with recursive ownership" : "");
    else
        printf("PASS: failed second acquire%s preserves WAIT_TIMEOUT and releases Offscreen once\n",
               recursive ? " with recursive ownership" : "");
    ok = 1;
done:
    stop_owner(&holder);
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_abandoned_wait(BOOL onscreen_wait, BOOL second_acquire)
{
    HANDLE offscreen = NULL, onscreen = NULL, waited;
    mutex_thread holder;
    DWORD result;
    int ok = 0;
    unsigned expected_offscreen, expected_onscreen;
    ZeroMemory(&holder, sizeof(holder));
    if (!graphics_pair(&offscreen, &onscreen, onscreen_wait))
        goto done;
    waited = onscreen_wait ? onscreen : offscreen;
    if (!start_owner(&holder, waited, TRUE))
        goto done;
    result = WaitForSingleObject(waited, 0);
    expected_offscreen = legacy_wait ? 0u : (!onscreen_wait || second_acquire ? 1u : 0u);
    expected_onscreen = !legacy_wait && onscreen_wait ? 1u : 0u;
    if (result != WAIT_ABANDONED_0 || finish_wait(waited, result, second_acquire) != WAIT_ABANDONED_0 ||
        !check_releases(offscreen, expected_offscreen, onscreen, expected_onscreen) ||
        !check_probe(waited, legacy_wait ? WAIT_TIMEOUT : WAIT_OBJECT_0, "abandoned acquired handle is released"))
        goto done;
    if (onscreen_wait && !check_probe(offscreen, legacy_wait || !second_acquire ? WAIT_TIMEOUT : WAIT_OBJECT_0,
                                     "abandoned second wait also releases Offscreen"))
        goto done;
    printf("%s: abandoned %s %s acquire preserves WAIT_ABANDONED and %s acquired graphics ownership\n",
           legacy_wait ? "EXPECTED ABANDONED OWNERSHIP LEAK" : "PASS", onscreen_wait ? "Onscreen" : "Offscreen",
           second_acquire ? "second" : "first", legacy_wait ? "retains" : "releases");
    ok = 1;
done:
    stop_owner(&holder);
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_successful_waits(void)
{
    HANDLE offscreen = NULL, onscreen = NULL;
    DWORD result;
    int ok = 0;
    if (!graphics_pair(&offscreen, &onscreen, FALSE))
        goto done;
    result = WaitForSingleObject(offscreen, 0);
    if (result != WAIT_OBJECT_0 || finish_wait(offscreen, result, FALSE) != WAIT_OBJECT_0 ||
        !check_releases(offscreen, 0, onscreen, 0))
        goto done;
    result = WaitForSingleObject(onscreen, 0);
    if (result != WAIT_OBJECT_0 || finish_wait(onscreen, result, TRUE) != WAIT_OBJECT_0 ||
        !check_releases(offscreen, 0, onscreen, 0) ||
        !check_probe(offscreen, WAIT_TIMEOUT, "successful first acquire stays owned") ||
        !check_probe(onscreen, WAIT_TIMEOUT, "successful second acquire stays owned"))
        goto done;
    puts("PASS: successful first and second waits retain graphics ownership");
    ok = 1;
done:
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_unknown_abandoned_wait(void)
{
    HANDLE offscreen = NULL, onscreen = NULL, unknown = NULL;
    mutex_thread holder;
    DWORD result;
    int ok = 0;
    ZeroMemory(&holder, sizeof(holder));
    if (!graphics_pair(&offscreen, &onscreen, TRUE))
        goto done;
    unknown = local_CreateMutexA(NULL, FALSE, "unrelated_wait_cleanup");
    if (!unknown || !start_owner(&holder, unknown, TRUE))
        goto done;
    result = WaitForSingleObject(unknown, 0);
    if (result != WAIT_ABANDONED_0 || finish_wait(unknown, result, TRUE) != WAIT_ABANDONED_0 ||
        !check_releases(offscreen, 0, onscreen, 0) ||
        !check_probe(unknown, WAIT_TIMEOUT, "unrelated abandoned ownership is unchanged") ||
        !check_probe(offscreen, WAIT_TIMEOUT, "unrelated wait does not release Offscreen") ||
        !check_probe(onscreen, WAIT_OBJECT_0, "unrelated wait leaves Onscreen available"))
        goto done;
    puts("PASS: unknown abandoned Mutex keeps its original ownership and result");
    ok = 1;
done:
    stop_owner(&holder);
    release_and_close(unknown);
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_failed_wait(unsigned path, BOOL recursive, BOOL wrapper)
{
    HANDLE offscreen = NULL, onscreen = NULL, waited = NULL;
    HANDLE expected_offscreen, expected_onscreen;
    DWORD result;
    BOOL second_acquire = path == 0 || path == 3;
    int ok = 0;
    if (!graphics_pair(&offscreen, &onscreen, path != 1))
        goto done;
    expected_offscreen = offscreen;
    expected_onscreen = onscreen;
    if (recursive && WaitForSingleObject(offscreen, 0) != WAIT_OBJECT_0)
        goto done;
    if (path == 1) {
        waited = offscreen;
        CloseHandle(offscreen);
        offscreen = NULL;
    } else if (path >= 2) {
        waited = onscreen;
        CloseHandle(onscreen);
        onscreen = NULL;
    }
    if (wrapper)
        result = wait_through_wrapper(waited, 0, second_acquire);
    else {
        result = WaitForSingleObject(waited, 0);
        result = finish_wait(waited, result, second_acquire);
    }
    if (result != WAIT_FAILED || error_after_finish != ERROR_INVALID_HANDLE ||
        !check_releases(expected_offscreen, path == 3 && !legacy_wait ? 1u : 0u, expected_onscreen, 0))
        goto done;
    if (offscreen && !check_probe(offscreen, path == 3 && !legacy_wait && !recursive ? WAIT_OBJECT_0 : WAIT_TIMEOUT,
                                  "WAIT_FAILED balances only the second acquire's Offscreen ownership"))
        goto done;
    if (onscreen && !check_probe(onscreen, WAIT_OBJECT_0, "WAIT_FAILED leaves available Onscreen unchanged"))
        goto done;
    if (recursive && !legacy_wait &&
        (!ReleaseMutex(offscreen) || !check_probe(offscreen, WAIT_OBJECT_0, "WAIT_FAILED releases exactly one recursive acquire")))
        goto done;
    printf("PASS: %s WAIT_FAILED path %u%s preserves ERROR_INVALID_HANDLE and ownership contract\n",
           wrapper ? "native wrapper" : "helper", path, recursive ? " recursive" : "");
    ok = 1;
done:
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_wrapper_timeout(void)
{
    HANDLE offscreen = NULL, onscreen = NULL;
    mutex_thread holder;
    DWORD result, ordinary_error;
    int ok = 0;
    ZeroMemory(&holder, sizeof(holder));
    if (!graphics_pair(&offscreen, &onscreen, TRUE) || !start_owner(&holder, onscreen, FALSE))
        goto done;
    SetLastError(ERROR_CANCELLED);
    result = WaitForSingleObject(onscreen, 0);
    ordinary_error = GetLastError();
    if (result != WAIT_TIMEOUT)
        goto done;
    SetLastError(ERROR_CANCELLED);
    if (wait_through_wrapper(onscreen, 0, FALSE) != WAIT_TIMEOUT || error_after_finish != ordinary_error ||
        !check_releases(offscreen, 0, onscreen, 0) ||
        !check_probe(offscreen, WAIT_TIMEOUT, "unrelated wrapper caller retains Offscreen"))
        goto done;
    SetLastError(ERROR_CANCELLED);
    if (wait_through_wrapper(onscreen, 0, TRUE) != WAIT_TIMEOUT ||
        !check_releases(offscreen, 1, onscreen, 0) ||
        !check_probe(offscreen, WAIT_OBJECT_0, "actual second ReturnAddress releases Offscreen") ||
        !check_probe(onscreen, WAIT_TIMEOUT, "actual second ReturnAddress leaves Onscreen's owner intact"))
        goto done;
    puts("PASS: actual wrapper distinguishes second and unrelated ReturnAddresses, preserving timeout LastError");
    ok = 1;
done:
    stop_owner(&holder);
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

static int check_wrapper_abandoned(BOOL second_acquire)
{
    HANDLE offscreen = NULL, onscreen = NULL, waited;
    mutex_thread holder;
    int ok = 0;
    ZeroMemory(&holder, sizeof(holder));
    if (!graphics_pair(&offscreen, &onscreen, second_acquire))
        goto done;
    waited = second_acquire ? onscreen : offscreen;
    if (!start_owner(&holder, waited, TRUE))
        goto done;
    SetLastError(ERROR_CANCELLED);
    if (wait_through_wrapper(waited, 0, second_acquire) != WAIT_ABANDONED_0 ||
        !check_releases(offscreen, 1, onscreen, second_acquire ? 1u : 0u) ||
        !check_probe(offscreen, WAIT_OBJECT_0, "wrapper abandonment releases Offscreen") ||
        !check_probe(onscreen, WAIT_OBJECT_0, "wrapper abandonment leaves Onscreen available"))
        goto done;
    printf("PASS: actual wrapper %s acquire preserves WAIT_ABANDONED and LastError without leaked ownership\n",
           second_acquire ? "second" : "first");
    ok = 1;
done:
    stop_owner(&holder);
    release_and_close(offscreen);
    release_and_close(onscreen);
    return ok;
}

typedef DWORD (WINAPI *wait_api)(HANDLE, DWORD);

static __declspec(noinline) wait_api imported_wait(void)
{
    return WaitForSingleObject;
}

static int check_signature_rejection(void)
{
    void *previous_return = g_cursor_second_wait_return;
    wait_api previous_import = imported_wait();
    int ok;
    g_cursor_second_wait_return = (void *)0x12345678;
    install_graphics_wait_fix(GetModuleHandleA(NULL));
    ok = g_cursor_second_wait_return == (void *)0x12345678 && imported_wait() == previous_import;
    g_cursor_second_wait_return = previous_return;
    if (!ok) {
        puts("FAIL: non-GOG image unexpectedly installed the graphics wait Hook");
        return 0;
    }
    puts("PASS: non-GOG image leaves WaitForSingleObject IAT and caller Gate unchanged");
    return 1;
}

static int check_wait_cleanup(void)
{
    return check_second_timeout(FALSE) && check_second_timeout(TRUE) &&
           check_abandoned_wait(FALSE, FALSE) && check_abandoned_wait(TRUE, FALSE) &&
           check_abandoned_wait(TRUE, TRUE) && check_successful_waits() && check_unknown_abandoned_wait() &&
           check_failed_wait(0, FALSE, FALSE) && check_failed_wait(1, FALSE, FALSE) &&
           check_failed_wait(2, FALSE, FALSE) && check_failed_wait(3, FALSE, FALSE) &&
           check_failed_wait(3, TRUE, FALSE) &&
           (legacy_wait || (check_failed_wait(0, FALSE, TRUE) && check_failed_wait(1, FALSE, TRUE) &&
                            check_failed_wait(2, FALSE, TRUE) && check_failed_wait(3, FALSE, TRUE) &&
                            check_failed_wait(3, TRUE, TRUE) && check_wrapper_timeout() &&
                            check_wrapper_abandoned(FALSE) && check_wrapper_abandoned(TRUE) &&
                            check_signature_rejection()));
}

static int child_main(int argc, char **argv)
{
    HANDLE mutex;
    DWORD waited;
    char *end;
    const char *name;
    if (argc != 6)
        return 1;
    test_root = strtoul(argv[2], &end, 10);
    if (!test_root || *end || (strcmp(argv[3], "0") && strcmp(argv[3], "1")) ||
        (strcmp(argv[4], "probe") && strcmp(argv[4], "abandon")))
        return 1;
    legacy = strcmp(argv[3], "1") == 0;
    name = strcmp(argv[5], "@unnamed") == 0 ? NULL : argv[5];
    mutex = create_mutex(NULL, FALSE, name);
    if (!mutex)
        return 1;
    waited = WaitForSingleObject(mutex, 250);
    if (waited == WAIT_OBJECT_0 && strcmp(argv[4], "abandon") == 0)
        ExitProcess(CHILD_EXIT_OWNING);
    if (waited == WAIT_OBJECT_0 || waited == WAIT_ABANDONED_0)
        ReleaseMutex(mutex);
    CloseHandle(mutex);
    if (waited == WAIT_OBJECT_0)
        return 0;
    if (waited == WAIT_TIMEOUT)
        return CHILD_TIMEOUT;
    return CHILD_ABANDONED;
}

int main(int argc, char **argv)
{
    const char *names[] = { "m_mutex_draw_cursor_offscreen", "m_mutex_draw_cursor_onscreen" };
    unsigned i;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (argc > 1 && strcmp(argv[1], "--child") == 0)
        return child_main(argc, argv);
    if (argc == 2 && strcmp(argv[1], "--legacy") == 0)
        legacy = 1;
    else if (argc == 2 && strcmp(argv[1], "--legacy-wait") == 0)
        legacy_wait = 1;
    else if (argc != 1) {
        puts("Usage: test_render_mutex.exe [--legacy | --legacy-wait]");
        return 1;
    }
    test_root = GetCurrentProcessId();
    if (!legacy_wait) {
        for (i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
            if (!check_contention(names[i]) || !check_abandonment(names[i]))
                return 1;
        }
        if (!check_shared_control("unrelated_control") ||
            !check_shared_control("m_mutex_draw_cursor_offscreen.extra") ||
            !check_shared_control("M_mutex_draw_cursor_onscreen") || !check_unnamed())
            return 1;
    }
    if (!legacy && !check_wait_cleanup())
        return 1;
    if (legacy) {
        puts("EXPECTED FAILURE: both raw cursor Mutex names collide and inherit abandoned ownership");
        return CHILD_TIMEOUT;
    }
    if (legacy_wait) {
        puts("EXPECTED FAILURE: graphics waits leak acquired ownership without cleanup");
        return 44;
    }
    puts("PASS: production cursor Mutex isolation, failed-wait cleanup and passthrough contracts");
    return 0;
}
