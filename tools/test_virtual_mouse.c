#define ARMADA_TESTHOOKS
#include <stdio.h>
#include <string.h>
#include "../src/strlkup_proxy/strlkup_proxy.c"

static void reset_input(void)
{
    g_input_available = TRUE;
    g_virtual_input = TRUE;
    g_virtual_buttons = 0;
    g_virtual_x = g_virtual_y = 0;
    g_virtual_seq = g_virtual_ack = 0;
}

static int check_poll(DWORD expected_buttons, int expected_x, int expected_y, const char *description)
{
    int state[4] = { 123, 123, 123, 123 }, output[4] = { 456, 456, 456, 456 };
    DWORD buttons = 0xffffffff;
    int result = test_mousepoll(state, output, &buttons);
    if (result != 0 || buttons != expected_buttons || (buttons & 2) ||
        state[0] != expected_x || state[1] != 0 || state[2] != expected_y || state[3] != 0 ||
        memcmp(state, output, sizeof(state)) != 0 || g_virtual_seq != 0 || g_virtual_ack != 0) {
        printf("FAIL: %s: result=%d buttons=%lu expected=%lu axes=%d,%d,%d,%d\n",
               description, result, buttons, expected_buttons, state[0], state[1], state[2], state[3]);
        return 0;
    }
    return 1;
}

static int button(LPARAM action, DWORD expected_buttons, const char *description)
{
    if (!test_input_event(NULL, INPUT_BUTTON, 0, action)) {
        printf("FAIL: %s: private button event was not consumed\n", description);
        return 0;
    }
    return check_poll(expected_buttons, 0, 0, description);
}

static int check_buttons(void)
{
    reset_input();
    if (!check_poll(0, 0, 0, "initial state") ||
        !button(1, 1, "left down") || !button(1, 1, "repeated left down") ||
        !button(3, 5, "right down while left held") ||
        !button(2, 4, "left release keeps right held") || !button(4, 0, "right release") ||
        !button(3, 4, "right down") || !button(3, 4, "repeated right down") ||
        !button(1, 5, "left down while right held") ||
        !button(4, 1, "right release keeps left held") || !button(2, 0, "left release") ||
        !button(2, 0, "repeated left release") || !button(4, 0, "repeated right release"))
        return 0;
    puts("PASS: native button masks left=1 right=4 combined=5; independent releases; no middle bit");
    return 1;
}

static int check_ignored_input(void)
{
    reset_input();
    if (!button(1, 1, "left setup") || !button(3, 5, "right setup") ||
        !button(0, 5, "unsupported zero action") || !button(5, 5, "unsupported action") ||
        !button(-1, 5, "unsupported negative action"))
        return 0;
    if (test_input_event(NULL, INPUT_ENABLE - 1, 0, 0) ||
        test_input_event(NULL, INPUT_CAPTURE + 1, 0, 0) ||
        !check_poll(5, 0, 0, "unrelated messages leave input unchanged"))
        return 0;
    g_input_available = FALSE;
    if (!button(2, 5, "unavailable left release") || !button(4, 5, "unavailable right release"))
        return 0;
    g_input_available = TRUE;
    g_virtual_input = FALSE;
    if (!test_input_event(NULL, INPUT_BUTTON, 0, 2) ||
        !test_input_event(NULL, INPUT_BUTTON, 0, 4) || g_virtual_buttons != 5) {
        puts("FAIL: disabled virtual input changed button state");
        return 0;
    }
    g_virtual_input = TRUE;
    if (!check_poll(5, 0, 0, "disabled virtual input leaves state unchanged"))
        return 0;
    puts("PASS: unsupported messages/actions and unavailable/disabled input leave state unchanged");
    return 1;
}

static int check_coordinates(void)
{
    int state[4], output[4];
    reset_input();
    if (!test_input_event(NULL, INPUT_MOVE, 0, MAKELPARAM(320, 240)) ||
        !check_poll(0, 0, 0, "center coordinates") ||
        !test_input_event(NULL, INPUT_MOVE, 0, MAKELPARAM(0, 0)) ||
        !check_poll(0, -65536, -65536, "top-left coordinates") ||
        !test_input_event(NULL, INPUT_MOVE, 0, MAKELPARAM(639, 479)) ||
        !check_poll(0, 65331, 65262, "bottom-right coordinates"))
        return 0;
    if (test_mousepoll(state, output, NULL) != 0 || memcmp(state, output, sizeof(state)) != 0) {
        puts("FAIL: polling without a button output changed the device result");
        return 0;
    }
    puts("PASS: center/corner normalization and Poll output contract");
    return 1;
}

int main(void)
{
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (!check_buttons() || !check_ignored_input() || !check_coordinates())
        return 1;
    puts("PASS: actual test-proxy virtual mouse functions; no game/UI/OS input calls");
    return 0;
}
