# Native-window test rendering repair, 2026-11-04

The user reported a lobby background without labels directly on the screen. This was
an actual rendering failure in the native-window test setup. It was not normal gameplay
and was not merely a screenshot limitation.

## Cause and scope

With `-window`, Armada's DirectX7 mode setup takes the native-window branch at
`0x5816f4`: IDirectDraw7::RestoreDisplayMode. The GOG 1.1.0.3494 wrapper releases
and clears its D3D9 device there. Its SetCooperativeLevel(DDSCL_NORMAL) path does not
create another device. The simulation and render loop continued, but there was no
underlying GPU device to draw the world or HUD. The lobby's separate controls disappeared
on Launch, leaving the old background visible.

This was observed directly in `ui_main2`: renderer active, game mode 2, 11,636 completed
render calls, and the wrapper's D3D9 device pointer still NULL. Setting the logical
active flag afterwards did not repair initialization. A bounded static scan found no
foreground-dependent render Gate in the wrapper; focus queries were not virtualized.

The previous `play10` and `play11` comparisons remain evidence of replicated simulation
state. Their missing 3D output must not be treated as successful visible UI validation.

## Fix

The test proxy intercepts only the native-window RestoreDisplayMode call site, checked
against the stock GOG instructions. On the **menu-to-game transition**, it invokes the
GOG wrapper's SetDisplayMode before creating the new native game surfaces and D3D7
facade. The renderer keeps DDSCL_NORMAL and its fullscreen flag remains zero.

- The wrapper must be the identified GOG 1.1.0.3494 Build and `dxcfg.ini` must explicitly
  request `presentation=windowed`. Other wrappers retain the original path.
- The initial desktop-mode bootstrap and menu setup retain their original behavior.
  Initializing D3D9 during that bootstrap breaks the later Bink/menu transition.
- Canvas width/height come from the actual renderer viewport (`device+0xcc/+0xd0`),
  rather than its desktop-mode descriptor. Using the latter opened 1024x768 for a
  640x480 view, which caused the black margins in the user's follow-up image.
- The x87 control word is preserved across device initialization. No simulation orders,
  health, resources, timers or RNG values are changed.
- Initialization failure reaches the game's existing SetDisplayMode error handler,
  rather than continuing with an unusable device.

`start_play_test.ps1` enables `ARMADA_TEST_NATIVE_MODE_INIT=1` for future test starts.
It also requires a passing live renderer/canvas check on each client before reporting
startup complete; failed rendering stops the owned test instances and retains the logs.
All of this code is behind `ARMADA_TESTHOOKS`; the production proxy and downloadable
v1.2.0 game patch remain unchanged.

## Verification

- Actual world, ships, starbase and HUD became visible in `ui_init3`; the user supplied
  an on-screen image confirming this. The remaining black margins were then removed
  in `ui_init4`, whose 640x480 viewport matched its 640x480 Window client.
- In `ui_init4`, the actual Menu button opened the fully labelled Options dialog.
  Clicking **Return to Game** returned to mode 2, recreated D3D9 and produced the world
  and HUD again. This exercised the GDI-menu/game transition with real game UI actions.
- Final Build, run `render_mp1`: two human slots, no AI slots and no mirrored simulation
  injection. Both clients had a live D3D9 device, `Windowed=1`, native fullscreen flag 0,
  and matching 640x480 viewport/client dimensions.
- `tools/test_window_render.py render_mp1 A` and `... B` each executed **three passing
  checks**. They inspect the live device/canvas and replay each process's actual installed
  x86 shim in Unicorn, checking success, failure propagation and stack/register contracts.
- Both players completed a new construction ship at step 8,000. Their scouts attacked
  each other from commands submitted only on the owning client. Reciprocal enemy IDs
  and health losses are in the dumps; both scouts survived the configured test interval.
- The final comparison passed **100 complete dump pairs through step 10,000**. Both
  processes reached the configured exit step. Audio pre-mute returned S_OK on both
  clients, the firewall preflight made no rule changes, and the scoped watchdog recorded
  no game focus or cursor confinement alert.
- Both DLL variants build with `/W4`, Python compilation passes, and the native production
  mouse/focus guard check passes. The rebuilt production `.text` and exports still match
  the embedded release proxy. Temporary diagnostic instrumentation was removed.
- Final launcher smoke, `render_smoke1`: each automatic live renderer check actually
  executed and passed before startup was reported complete. The clients then reached
  their configured exit at step 3,000, with 30 matching dump pairs and no watchdog alert.

Raw captures remain under the ignored `work/det/render_mp1`; compact results are in
[`validation/render_mp1.json`](validation/render_mp1.json). Run renderer checks while
the clients are in a match, before their configured exit step.

The native screenshot readback can have inverted row order; it is separate from the
actual on-screen orientation. This repair does not establish all keyboard/dialog flows,
all mods, separate-PC interoperability, or the absence of every out-of-sync cause.
