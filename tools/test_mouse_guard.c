/* Exercise the production background guard with recording callbacks. No window,
   activation, cursor movement or cursor confinement is performed by this test. */
#include <assert.h>
#include <stdio.h>
#include "../src/strlkup_proxy/strlkup_proxy.c"

static int moves, clips, releases, activations, focuses;

static BOOL WINAPI record_foreground(HWND hwnd)
{
    (void)hwnd;
    activations++;
    return TRUE;
}

static HWND WINAPI record_focus(HWND hwnd)
{
    focuses++;
    return hwnd;
}

static BOOL WINAPI record_move(int x, int y)
{
    (void)x; (void)y;
    moves++;
    return TRUE;
}

static BOOL WINAPI record_clip(const RECT *rect)
{
    if (rect)
        clips++;
    else
        releases++;
    return TRUE;
}

int main(void)
{
    RECT rect = { 0, 0, 640, 480 };
    assert(!game_in_front());  /* this console helper creates no game window */
    g_real_SetCursorPos = record_move;
    g_real_ClipCursor = record_clip;
    g_real_SetForegroundWindow = record_foreground;
    g_real_SetFocus = record_focus;
    assert(local_SetCursorPos(100, 100));
    assert(local_ClipCursor(&rect));
    assert(local_SetForegroundWindow(NULL));
    assert(local_SetFocus(NULL) == NULL);
    assert(activations == 0 && focuses == 0);
    assert(moves == 0 && clips == 0 && releases == 0 && g_clipped == 0);
    assert(local_ClipCursor(NULL));
    assert(releases == 0);  /* another process's clip is never released */
    g_clipped = 1;
    release_clip();
    release_clip();
    assert(releases == 1 && g_clipped == 0);
    g_clipped = 1;
    assert(local_ClipCursor(NULL));
    assert(releases == 2 && g_clipped == 0);
    puts("PASS: production background mouse/focus guards, clip ownership and release");
    return 0;
}
