# Findings – Star Trek: Armada multiplayer (GOG 1.2 "RDNA fix")

Target: `Armada.exe` from `setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`,
SHA-256 `1c37ee8e4a24380c950a91ce5a7f9f96c4fcf3d8ffc0cc7e58faec3835350be6`, image base
`0x400000`. All addresses below refer to this file. GOG already patched this executable
(for example the long-`PATH` overflow at `0x43ff64` is skipped with a `jmp`, and a code cave
at `0x402263` jumps into `0x47747f`).

Tools: Ghidra 12.1 through REA (decompiler, xrefs), capstone and the scripts in `tools/`
(RTTI vtable map, call-site scans, direct-call reachability), runtime probes on Windows 11.

## How the multiplayer simulation works

- **Lockstep.** `TransportNetwork` vtable slot 6 (`0x4cfd20`) is the network game loop. Once per
  network turn it calls `0x43f880(turn_ms)` with `turn_ms = 1000 / rate`; the rate is agreed
  between the nodes. Between turns it calls `0x43f970` to render frames with the real time.
- **Simulation step** `0x43f880`: runs the AI script engine (`0x4032d0`: timers, IIIE inference
  engine, `character::execute_scripts`), the simulation tick `0x43f2b0` → `0x43f1a0`
  (dt = tick time × game speed; objects, weapons, special effects, then all `GameFeature`
  updates through `0x510590`, which includes explosions) and the transport update.
- **Render** `0x43f970` → `0x5b9730` → scene `0x5b9440`: ordnance lights `0x4eda60`, ordnance
  render `0x4edaf0`, special effect render `0x55ee90`, `GameFeature` render `0x5105d0`. It runs a
  different number of times per turn on every PC and once per extra view (cinematic view,
  bridge display).
- **Sync check** `0x442af0`: checksum over game objects (`0x46f0d0`), weapons (`0x50ba80`),
  ordnance (`0x4edd40`), `0x6787f4`, one draw `rand(100000)` of the synchronized generator and
  one value of the table generator `0x501410`. `0x4c8f50` compares the nodes; on the first
  mismatch it logs "CRC For node %d is %08x", writes `Logs\SYNC__…__DUMP__…` (`0x43fc50`:
  random values, `0x46f190` objects, `0x50bb20` weapons, `0x4edde0` ordnance) and shows
  "This network game is out of sync".

## Random generators

Two generators share the code `s = (s * 0x8e1 + 0x1f) % 0x19981595; return s % n`:

| Generator | State | Seeded by | Same on all nodes |
|---|---|---|---|
| synchronized: `0x5014d0` (int), `0x501430`, `0x501480`, `0x501500`, `0x501640` | `0x67dc98` | `0x5013a0(session seed)` | yes |
| local: `0x5018c0` (int), `0x501800`, `0x501820`, `0x501870`, `0x5018f0` | `0x67dca4` | `0x501330`: `srand(time(0))`, `rand()` | no |
| table: `0x501410` (256 floats at `0x5d1a48`) | index `0x67dc9c` | `0x5013a0` | yes |

## Finding 1 – local random numbers in the docking orders (fixed)

`CraftProcess` vtable slot 23 (`0x42a450`, send a ship to the nearest shipyard) and slot 27
(`0x42b430`, approach/dock) set the approach angle `CraftProcess+0x114 = rand(4) · π/2` with the
**local** generator `0x5018c0` (`0x42a540`, `0x42b76e`). The unreferenced helper `0x430270`
contains the same code (`0x430296`). Every node runs these handlers for every ship, so every
node computes a different docking position. Other `CraftProcess` methods (slots 12, 18, 20, 22,
30) already use the synchronized generator, which confirms that this is simulation code.

Fix: the three `call 0x5018c0` become `call 0x5014d0` (same calling convention, `rand(4)`).

All other callers of the local generators were checked and only drive presentation: unit
acknowledgement sounds (`0x43bd60`…`0x43c060`), explosion effects and sounds (`0x465100`,
`0x466180`, `0x466320`, `0x4683d0`), beam jitter (`0x4e6c80`), nebula and ion storm visuals
(`0x451e00`, `0x452230`, IonStorm flicker), `WorkerBee`, `FireballExplosion`, particle emitters
(`0x574xxx`–`0x57dxxx`), mesh shuffling (`0x551340`), cameras (`0x47b100`), music and sound
(`0x5b61b0`, `0x5b62a0`, `0x5ba790`), the interface scrambler of the local victim
(`TimedScrambleInterface`, only when the victim is the local player).

## Finding 2 – the torpedo renderer changes the torpedo's target (fixed)

The ordnance render pass `0x4edaf0` reaches the stores `mov [esi+0xf8], ebx` (ebx = 0) at
`0x4edb9e`, `0x4edbf9`, `0x4edc2a`, `0x4edc86` only when the shooter does not exist or is not
visible to the local player (`GameObject` vtable slot 9 `0x471e10`, which reads the local
player and the fog-of-war map `0x633aa0`). The stores clear `Ordnance+0xf8`, the target id,
when the target is dying (`+0x1b1`) or cloaked (`+0x1b4`) while the shooter is not.

The simulation has its own check: `0x4ee620` (called from ordnance vtable slots 17 and 19)
clears the target only for the cloak case. So the render pass changed simulation state
depending on local visibility and frame rate, and in the "target dying" case in a way the
simulation never does.

Fix: the four stores become `lea ebx, [ebx+0]` (6-byte NOP). The render decisions do not
change, because the same conditions are evaluated again on every frame. `0x4ee620` stays.

## Finding 3 – start-up crash when the log file cannot be created (fixed)

The logging init around `0x4ff6f5` opens `Logs\logfile.txt` with `"wt"`. If `fopen` fails it
jumps to `int3` at `0x4ff738`; without a debugger the game dies with exception `0x80000003`.
Reproduced: unpacked game without the `Logs` folder → crash at start. The instruction after
the `int3` already turns file logging off. Fix: `int3` → `nop`; the game then starts without
file logging (tested).

## Finding 4 – GOG DirectX wrapper crashes when another wrapper game runs (fixed)

`ddraw.dll` ("GOG.com DirectX 1-7 wrapper" 1.1.0.3494) creates a file mapping named
`dxfilemap` (`CreateFileMappingA` at `0x1801d200`, `0x1801e9f1`) and, in `0x18041550`, opens it
again and uses the stored `IDirect3DDevice9*` (`CreateStateBlock`, vtable offset `0xec`). The
name lives in the session namespace, so a second process with the same wrapper (Armada II,
other GOG titles) hands Armada a foreign pointer: access violation at `ddraw.dll+0x4160f`.
Reproduced with a process that holds a fake `dxfilemap` (EAX = the fake pointer).

Fix: the name becomes `armada1fm` in the file; the `Strlkup.dll` proxy hooks Armada's
`LoadLibraryA` and, once the wrapper is loaded, renames it in memory to `dxm<pid>`. Tested
with fake mappings under both names.

## Finding 5 – the game replaces the desktop's arrow cursor (fixed)

Armada shows its cursors with `SetSystemCursor(LoadImage(…), OCR_NORMAL)` (`0x54fd64`,
`0x54ffee`, `0x55020e`, `0x550ecc`, `0x550f4a`). In a window that changes the arrow of the
whole desktop, also while the game is in the background, and after a crash or kill it stays
until the next logon (measured: hash of the arrow bitmap before, during and after).

Fix: the proxy replaces Armada's `SetSystemCursor` import. The cursor becomes the class
cursor of the game's own top-level windows (the game window has no child windows) and is set
directly when the mouse is over the game; the previous cursor is destroyed, as
`SetSystemCursor` would do.

## Finding 6 – the loading screen leaves dead lights in the render engine (fixed, v1.1.0)

Found with the two-instance test bed: the host crashed after about 10 minutes of a LAN match
with "pure virtual function call" (`msvcrt!_purecall`, exception `0xc0000002`). Stack:
render `0x43f970` → `0x5b9730` → scene `0x5b9440` → objects `0x5b6620` → `Planet` vtable slot
2 → mesh `0x58fd80` → mesh lighting `0x5a4410`, which calls virtual slot 18 of every light in
the engine's active light list. The light had already been destroyed (its vtable was the
abstract `ST3D_Light` base `0x5d40a8`).

The engine (`ST3D`, global `0x6d4aa0`) keeps the lights of the current render in a list at
engine+`0x70`: `0x58b380` (AddLight) appends a record that holds a raw `ST3D_Light*`,
`0x58b440` (via `0x580a00`) deletes all records. The scene render `0x5b9440` clears the list
at its end. The **loading screen** does not: `0x5b99d0` draws every loading message, adds its
light `0x6d6854` each time and never clears the list, and its teardown `0x5b9fe0` deletes the
light. In the test bed one map load left **370 records** of the deleted light in the list
(host only; the client logged none). By the code, the first scene render after the load calls
methods of the deleted light through these records before it clears the list, and
`0x57d670` / `0x5a4410` write the transformed light position into the freed memory. That
corrupts whatever object reuses the memory; it is the only path we found that puts a dead
light into the list. Whether the crash at minute 10 came from this corruption or from another
light destroyed during a render was not proven; the fix below covers both.

No ST3D light destructor removes its records: all four (`ST3D_Light`, `ST3D_Point_Light`,
`ST3D_Directional_Light`, `ST3D_Spot_Light`) end with `mov [ecx], 0x5d40a8; jmp 0x5958b0`
(`ST3D_Node` destructor). Fix (runtime proxy): the four jumps go through a function that first
removes every record of the light from the active list, the same way `0x58b440` does. With the
fix the test bed logged the 370 removals at the end of the first map load and no further
dead-light use.

## Finding 7 – closing the window leaves an invisible game running (fixed, v1.1.0)

The game window procedure `0x442d10` does not handle `WM_CLOSE`. `DefWindowProc` destroys
the window, the main loop keeps running without it and logs "Storm3D Error: Invalid window
handle" until the process is killed. In fullscreen this needed Alt+F4; in a window the title
bar's X does it. Reproduced: after `WM_CLOSE` in an Instant Action game the process stayed
alive without a window. Fix (runtime proxy): `RegisterClassA` for the class "Armada" wraps the
window procedure; on `WM_CLOSE` the process ends (exit code 0). In a multiplayer game the
other players see this player leave, as after a disconnect.

## Finding 8 – a ship with a vanished target crashes every node (fixed, v1.2.0)

`CraftProcess` slot 21 (`0x42af80`, the handler of order 8) looks up the ship's target by
its id (`+0x134`, lookup `0x46cf50`). When the target no longer exists, the code sets
`edi = 0` (`xor edi, edi` at `0x42afe7`) and, unless the ship was hit within the last
second, reads `[edi+0x1c]` at `0x42affa`: access violation. The sibling code in `0x4268e0`
has the same lookup with a null check (`cmp edi, ecx; je`); here it is missing.

The simulation is deterministic, so every node of a match reaches this instruction in the
same step: all players crash at once (not an out-of-sync message). Reproduced in the test bed
(run mp5, original exe, order 23 "go to a shipyard" injected for every ship): both instances ended at about
step 20,450 with `c0000005` at `Armada.exe+0x2affa`, EDI = 0 (Windows event log, game log
"ACCESS VIOLATION … EIP 0042affa").

Fix (Armada.exe, 2 bytes): `xor edi, edi` becomes `jmp 0x42b034`, the function's return.
That is what the handler already does for a missing target on its other branch (ship hit
within the last second): `__RTDynamicCast(edi = 0)` at `0x42b01a` returns 0 and the code
jumps to `0x42b034` without any action. So the patch changes only the case that crashed;
everything else stays bit-identical with v1.0.0/v1.1.0. The patcher finds the site by its
code signature and checks that the jump target is `pop edi; pop esi; ret`.

Order numbers: the dispatcher `0x427ff0` maps the order through a byte table (`0x42813c`) to a
`CraftProcess` slot: order 8 → slot 21 (`[vtbl+0x54]`, this handler), order 21 → slot 25,
order 23 → slot 23, order 24 → slot 27. Earlier notes incorrectly called the faulty handler
"order 21" after its slot number.

Tested: `tools/test_order8.py` replays the handler's real instructions (original and patched
exe) in an emulator with a vanished target. Original: access violation at `0x42affa`, the
address of the mp5 crash. Patched: the handler returns without giving the ship a new order.
With the ship hit within the last second both versions return the same way. In the test bed
(run mp9) order 8 was given to every ship without a target: the patched return was taken
116,000 times on each node, with no crash and no difference between the nodes. In the
original the first of these would end the match.

## Finding 9 – the mouse is held in the game window (fixed, v1.2.0)

Two things keep the mouse in the window, also when the window is in the background:

- **GOG DirectX wrapper (`ddraw.dll`).** To emulate exclusive fullscreen it confines the
  cursor to the game's client area with `ClipCursor` (VAs with image base `0x18000000`:
  `0x1801dad1`, `0x1801f29f`, `0x18020a33`, `0x18044c68`, `0x18045c79`, `0x180461fd`) when
  the game sets up its display and on window events, and releases it on deactivation
  (`0x18044e5a`). The clip is global and is set regardless of which window is in front: an
  Armada window in the background (a game started while the user works elsewhere, or a
  second instance) caught the user's mouse. The wrapper also hooks the game's
  `SetCursorPos` import (scaled coordinates, `0x18048560`) and calls `SetForegroundWindow`
  after a display change (`0x1801d920`, `0x1801f0ee`).
- **The game itself.** In a match it reads the mouse relatively: while its active flag
  (`0x6337b0`, set from `WM_ACTIVATE`) is on, every input poll puts the cursor back to the
  window centre with `SetCursorPos` (`0x477541`).

Fix (runtime proxy): `SetCursorPos` and `ClipCursor` are replaced in the imports of
Armada.exe and of `ddraw.dll` (as soon as the wrapper is loaded). They act only while a
window of the game process is the foreground window; a `ClipCursor(NULL)` releases only a
clip that the game set, and the clip is released when the game window is deactivated. While
the game is in front it behaves as before (the cursor stays in the window, Alt+Tab releases
it). The proxy calls the real functions through `GetProcAddress` pointers, because the wrapper
hooks imports by name.

The production proxy also guards the wrapper's `SetForegroundWindow` and `SetFocus`
imports. Otherwise a background display-change path could reactivate the game first and
then pass the cursor foreground check. The original wrapper calls are observed statically
at `0x1801d920`/`0x1801f0ee`; test-run activation stacks also reach `ddraw.dll+0x45f8f`.
The guarded callbacks run only when a window of the game process is already foreground.
This closes a gap in the earlier mouse-only guard; it is covered by recording callbacks,
not a foreground gameplay run. Win32 API semantics:
[SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow),
[SetFocus](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setfocus).

Tested: before the fix, the PC's user found the mouse pulled into the window of a background
test instance. With the fix, the
test-build instances of runs mp6 and mp7 never confined the cursor and never came to the front
(`tools/mouse_watchdog.py`, polled every 50 ms). The release behaviour while the game is in
front (clip and re-centring as before) is unchanged code of the game and the wrapper and was
not run here, because it would take the mouse of the PC's user.

## Windowed mode

`dxcfg.ini` of the GOG wrapper: `presentation` = `application` | `fullscreen` | `windowed`;
`display` = `desktop` | `application` | `<w>x<h>@<hz>` (the window size; the game image is
scaled with `scaling` and `aspect`). `display=windowed` is not a valid value. Armada's own
`-window` switch also works, but the menus then use the game's 640×480 window.

## Finding 10 – a rejected installation partially changes game files (fixed, v1.2.0)

The patcher validated `--window` after changing the exe, wrapper and proxy. It also checked
for an existing `Strlkup_orig.dll` only after changing the exe and wrapper. Both errors could
leave part of the installation changed, including a mod-library collision that should have
stopped the operation. The option and collision checks now run before the first write.

`tools/test_patcher.py` reproduced both cases on copies of the original GOG files: the
command failed but file hashes changed. With the fix both rejected commands leave every
file identical. Apply/reapply/restore and standalone double-click/drag-and-drop also pass
for both the Python tool and the packaged exe. This is preflight validation, not a guarantee
against interruption or disk failure during writes; the existing backups remain necessary.

## Isolated instruction replays (v1.2.0)

`python tools/test_sync_instructions.py work/install/Armada.exe` executes the original GOG
x86 instructions in Unicorn 2.1.4. It verifies the input SHA-256 and derives patched bytes
with the real patcher's signatures. Game lookup/visibility queries are controlled fixtures;
no game process, UI or network is started. Three checks pass:

- At each docking call (`0x42a540`, `0x42b76e`, `0x430296`), execute the actual `push 4`, call
  and complete RNG function with identical session state (1234) and local states 1/2.
  Original angle indices are `[0, 1]`; patched indices are `[1, 1]` at all three sites.
- Run the actual torpedo-render branches from `0x4edaf0` up to the draw/checkpoint with
  target id 22, target dying, and shooter visible/hidden. Original target ids are `[22, 0]`;
  patched target ids are `[22, 22]`. Thus a presentation decision changes simulation state
  in the original and no longer does in the patched code.
- A live target remains 22 for both visibility fixtures in both versions.

These are controlled instruction observations. They demonstrate the two faulty state
transitions but do not replace a live-match reproduction through the final docking approach
or the complete fog-of-war combat scenario.

`tools/test_mouse_guard.cmd` compiles the production proxy code into a console helper with
recording mouse callbacks. Background movement/confinement is blocked and clip release
respects ownership. This invokes neither the real cursor functions nor a foreground game;
background wrapper focus/activation requests are also suppressed. Foreground gameplay and
Alt+Tab still need an interactive check.

## Checked and ruled out

- **FPU precision:** the CRT sets 53-bit precision at start (`0x5bbf34`); with the GOG wrapper
  every thread runs with control word `0x027f` (measured at run time).
- **Table generator `0x501410`:** used only by the sync check and the dump. `0x55d9c0` (random
  cone matrix) also calls it but has no callers.
- **Frame-rate dependent simulation:** explosions (including the damage of
  `ShockwaveExplosion`, slot 11 `0x51d2a0`) are updated by `ExplosionFeature` in the
  simulation tick with the tick dt; weapon fire (`Weapon` slots 20 and 21) creates the ordnance
  unconditionally and uses visibility only for camera events (`0x47aef0`, `0x47ad10`); special
  effect render (`0x55ee90`, vtable slot 0) only draws.
- **Real-time sources:** `timeGetTime`, `QueryPerformanceCounter`, `GetTickCount`, `time`,
  `clock`, `_ftime` are used by the transport, the interface, loading, logging and save names,
  not by the simulation.
- **Local player in simulation code:** every caller of the local player index `0x46d060`,
  mask `0x46d070` and `0x4c97b0` was checked; they drive the interface (command panel
  `Craft` slot 48, cursor choice `Craft` slots 30/31, radar, overview), sounds and the fog of
  war display.
- **Synchronized generator from local code:** all transitive direct callers of the
  synchronized generator were listed (`tools/rng_ancestors.py`); none is reached from the
  render or interface code, except the debug object editor `0x495310` (sets name, energy,
  crew and hull of an object directly; not part of normal play).
- **Version check:** `0x53374e` compares the version label only for the old WON login, not in
  LAN/DirectPlay games.

## Two-instance test bed (v1.1.0, v1.2.0)

Armada allows one instance per PC (`FindWindowA("Armada")` at `0x43b115`). The test build of
the proxy (`src/strlkup_proxy/build.cmd test`, `ARMADA_TESTHOOKS`) adds, controlled by
environment variables:

- `ARMADA_TEST_MULTI=1`: `FindWindowA("Armada")` returns NULL, so two instances run on one PC;
- `ARMADA_TEST_DUMP_EVERY=N`: after every N simulation steps (hook on `0x43f880`) a state dump
  with the game's own sync dump writers (all objects, weapons, ordnance) and the generator
  states, written to `ARMADA_TEST_DUMP_DIR`; no random numbers are consumed;
  completed dumps have an `END step N` marker and are renamed from `.tmp` only after close;
- `ARMADA_TEST_INJECT_STEP=S`, `ARMADA_TEST_INJECT_ORDER=O`, `ARMADA_TEST_INJECT_REPEAT=R`
  (v1.2.0): at step S, and then every R steps, the instance calls the mission function
  `CommandAllShips` (`0x436cb0`) with order O for the ships of every player. Both instances do
  it in the same step, as a mission script would, so the simulation stays the same on both
  nodes. Order 23 sends every ship to a shipyard (docking path of finding 1);
- `diag.txt`: every pure virtual call, every light destroyed while still in the active
  list (with thread and stack), every injected order and every refused window activation.

Test instances never touch the user's mouse or keyboard focus (v1.2.0). `tools/start_bg.py`
starts them with `SW_SHOWNOACTIVATE`; in the test build `SetCursorPos` and `ClipCursor` do
nothing, windows are shown without activation, `SetForegroundWindow` and `SetFocus` do nothing,
and a thread-local CBT hook refuses every activation of a game window (the GOG wrapper asks for
it at `ddraw.dll+0x45f8f`). The menus are driven with posted messages, which need no focus.
`tools/mouse_watchdog.py` polls the cursor clip and the foreground window every 50 ms during a
run and kills the instances if one of them confines the cursor or comes to the front.

`tools/mp_match.ps1` drives both instances through the menus with window messages (host:
Multiplayer → LAN TCP/IP → Create Game, client: join, host: two "Computer AI: Hard" slots →
Launch), `tools/cmpdumps.py` compares the dumps of both nodes step by step (ignoring the
per-node visibility fields), `tools/watch_mp.sh` repeats that every minute. The test build
also counts the docking approach-angle draws of finding 1 (`docking_angle_draws` in every
dump).

The comparator now returns nonzero for divergence or insufficient evidence (including zero
pairs), compares extra/missing lines, and never trusts an old filename-only cache. Final
checks use `--min-step` and `--min-pairs`. Old captures require `--legacy`; new captures must
have the completion marker. Eight regression checks cover these false-green cases.

Release validation commands (run from the repository root; the GOG game directory and
original exe are local fixtures and are never committed):

```text
python tools/test_cmpdumps.py
python tools/test_sync_instructions.py work/install/Armada.exe
python tools/test_order8.py work/install/Armada.exe
python tools/test_patcher.py work/install
python tools/test_patcher.py work/install --exe work/release/Armada_MP_fix.exe
tools\test_mouse_guard.cmd
src\strlkup_proxy\build.cmd test
python tools/make_release.py
```

The replays require `pefile` and `unicorn`; builds require the VS 2022 x86 toolset and
PyInstaller. The patcher itself has no Python package dependencies. Patcher checks also
read the `v1.1.0` Git tag to verify upgrade and preservation of the original backups.
Final results: 8 comparator tests, 3 sync tests, 2 order-8 tests, 7 patcher tests for Python
and the same 7 for the packaged exe pass, as does the native production mouse/focus helper.
Production and test DLL builds pass `/W4`; the embedded DLL matches the production build
and contains no test environment-variable markers.

Results (map `4first.bzn`, two idle human players, two Hard AIs that build fleets and fight;
both instances on one AMD Ryzen 9 9950X3D):

| Run | Armada.exe | Simulation steps | Dumps compared | Differences | Notes |
|---|---|---|---|---|---|
| mp1 | patched | 42,300 | 846 | 0 | host crashed at about 10 min: pure virtual call (finding 6) |
| mp2 | patched + light fix | 24,150 | 483 | 0 | 370 dead light records removed after the map load, no crash |
| mp3 | original | 51,950 | 1,039 | 0 | |
| mp4 | original | 54,350 | 1,087 | 0 | docking draws 0 on both nodes |
| mp5 | original | 20,450 | 409 | 0 | order 23 for all ships from step 8,000 every 4,000 steps; 30 docking draws (local generator); both nodes crashed in the same step (finding 8) |
| mp6 | v1.2.0 | 26,300 | 525 | 0 | as mp5; 20 docking draws (synchronized generator), no crash; stopped by hand |
| mp7 | v1.2.0 | 17,050 | 341 | 0 | 21 docking draws on each node; the old watchdog stopped both instances on a desktop work-area clip, not a proven game clip |
| mp8 | v1.2.0 | 40,000 | 800 | 0 | order 23 from step 8,000 every 4,000 steps; 40 synchronized docking draws per node, no crash; both instances reached the configured exit step |
| mp9 | v1.2.0 | 14,000 | 280 | 0 | order 8 for all ships from step 4,000 every 2,000 steps: the fixed return of finding 8 was taken 116,000 times on each node, no crash |

Up to 381 objects, damaged ships and torpedoes in flight were in the dumps. The AI never sent
a ship to a shipyard in mp1–mp4 (mp4: 0 draws). From v1.2.0 the test bed injects order 23
(mp5–mp8), so the docking path of finding 1 runs on both nodes. What the runs show: no other
cause of divergence in AI combat on one CPU, no regression from the patch, and with the patch
the docking draws come from the synchronized generator. Every run uses its own session seed,
so mp5 and mp6 are different matches.

The final mp8 acceptance command was
`python tools/cmpdumps.py work/det/mp8/A work/det/mp8/B --min-step 40000 --min-pairs 800`:
exit 0, `compared 800 steps; first difference: None`. Both final dumps have step 40,000,
the same synchronized RNG state `0afe950c` and table index 229; their local RNG states differ
as expected. The watchdog recorded no Armada focus/cursor alert. The lost-target counter
remained zero in this particular match; the dedicated handler replay covers that branch.
The mp8 test DLL predates the cosmetic counter rename from `order21_lost_target` to
`order8_lost_target`; the simulation patch and dump-completion logic are identical.

In mp5 (original exe) the local generator was drawn 30 times for docking, with a different
state on each node, and still the dumps stayed equal until the crash at step 20,450. The drawn
angle (`CraftProcess+0x114`) is not in the dump; it changes the ship only in the final approach
(`0x42f9b0`), which these ships apparently had not reached. So the test bed has not yet shown
the divergence of finding 1 in a live original match. The isolated instruction replay above
now reproduces the differing approach-angle indices directly.

## Active player validation, 2026-11-04

Run `play10` added actual ship construction and reciprocal player attack commands via
the owning clients' native multiplayer output queues, with no AI slots or mirrored
simulation injection. Four new ships completed, one shipyard completed, both players
dealt damage, and four ships died in combat. The final comparison covered 460 complete
dump pairs through step 46,000 with no difference. See
[`gameplay_validation_2026-11-04.md`](gameplay_validation_2026-11-04.md) for the command
path evidence, Windows mute/firewall defaults, GOG fixture repair and remaining limits.

## Native-window rendering in the test setup

The native-window setup branch at `0x5816f4` calls RestoreDisplayMode. In the GOG
wrapper this releases the D3D9 device, so a match can advance with no visible world/HUD.
The test proxy now initializes the identified GOG wrapper in explicit windowed mode
on the menu-to-game transition, before game surfaces are created, using viewport size.
The initial bootstrap/menu behavior is preserved. The production proxy is unchanged.
See [`window_rendering_2026-11-04.md`](window_rendering_2026-11-04.md) for reproduction,
scope guards, observed menu/resume behavior and the rendered two-client regression run.

## 9. Shared graphics Mutexes and failed-acquire ownership

The GOG executable creates `m_mutex_draw_cursor_offscreen` and
`m_mutex_draw_cursor_onscreen` with `CreateMutexA(NULL, FALSE, name)` around
`0x588f62` and `0x588fab`. Handles live at render-engine offsets `+0xa4` and `+0xa8`.
Live inspection of both `late3` clients showed the same Windows object names in
`\\Sessions\\1\\BaseNamedObjects`. During the stall, their main Threads waited
in the corresponding rendering paths; simulation and rendered-frame counters
advanced only about once per two wall seconds. No native out-of-sync report was
observed. This is evidence of a graphics stall, not an OOS reproduction.

`RefreshDisplay` (`0x581fb0`) and the cursor paths (`0x582f10`, `0x583280`) accept
only `WAIT_OBJECT_0`. Windows transfers ownership on `WAIT_ABANDONED` too, so the
original nonzero-return branches leak that ownership. The double-acquire path
first owns Offscreen at `0x58333d`, then waits on Onscreen at `0x583360` (`FF D7`,
return address `0x583362`). Its failure return at `0x583366` also skips releasing
the already-owned Offscreen Mutex.

The v1.3 proxy scopes only those two exact names to `.armada.<PID>`. A separate
77-byte signature check over `0x583325..0x583371`, bounded to readable committed
image memory belonging to the executable, enables the Wait import Hook. It
releases abandoned ownership and the failed second-acquire's Offscreen ownership
once, retaining the native failure result and LastError. Successful waits and
unrelated Handles retain their original behavior. No simulation code changes.

Native tests require original-name failure (exit 42), original-wait failure
(exit 44), then fixed success (exit 0). Worker Threads probe actual ownership;
tests cover recursive acquisition, abandoned first/second acquires, timeout,
invalid Handles, original error preservation, actual wrapper ReturnAddress
selection and negative signature gating. Runtime `ui_stress2` inspection confirms
both imports point into the loaded proxy and both client names have distinct PID
suffixes. The production DLL is embedded byte-for-byte in the release patcher.

A bounded audit of 27 shipped GOG EXE/DLL/DRV/OCX files found these literals only
in Armada's render-engine constructor, and no other shipped consumer opening
them by name. Data-only mods keep their formats. Custom renderer modules and
multiple engine/Handle aliases are outside that audit: the cleanup tracks the
latest created Handle for each of the two names. Earlier multi-instance attempts
also encountered GOG device-creation failures. Their loaded WIP artifact hashes
and raw CreateDevice results were not retained, so neither a client-count limit
nor a cause related to Mutex isolation is established. Fresh six-client attempts
record their artifacts before initialization and isolate one owned match.

The Late-Game validation method and measured gameplay evidence are in
[`late_game_validation_2026-11-04.md`](late_game_validation_2026-11-04.md).

## Finding 11 – the screen turning off crashes every client (fixed, v1.3.0)

All six clients of the six-player match `agents6_2` crashed at 21:10:27, eight seconds
after Windows logged the display switching off (Kernel-Power 566, session type 1 → 0;
the screen-on transitions that evening carry the reason `SessionUnlock`). Direct3D 9
loses its device then. The GOG wrapper's color-fill routine calls `GetRenderTarget`,
ignores the failed HRESULT and releases its uninitialized output (dumps at
`ddraw.dll+0x398c1`/`+0x398c3`, and `Armada.exe+0x183dbd` from the same `Release`).
The same unchecked block exists five times (RVAs `0x27bab`, `0x2e3de`, `0x3104e`,
`0x33d1e`, `0x398b6`, one per surface slot). The proxy checks HRESULT and output at all
five and takes the wrapper's own "no GPU clear" branch target on failure; the wrapper's
present path already resets a lost device (`TestCooperativeLevel`, RVA `0x20545`).
The failed restart `agents6_3` (`DDERR_UNSUPPORTEDMODE` in the test-only native mode
switch) started while the display was off. Details and verification:
[`gog_render_target_crash_2026-11-04.md`](gog_render_target_crash_2026-11-04.md).
An actual lock/display-off during a match with the fix is still to be checked by hand.

## Open

- A long multiplayer match on two separate PCs.
- The divergence of finding 1 in the original exe at run time: a test bed run where ships
  reach the final docking approach (`0x42f9b0`) after a local draw (mp5 ended earlier).
- Finding 2 at run time: fights where a torpedo's shooter is hidden by one player's fog of war.
- Selection helpers `0x431710`/`0x4318a0`: four apparent unchecked lookup results at
  `0x431756`, `0x4317ed`, `0x4318d9`, `0x431940` in overview/radar paths. Whether ordinary
  object removal can leave a stale selection id is unproven; no patch is applied. A bounded
  static pass over 48 `FindObject` call sites in `0x420000`–`0x433000` found no further
  validated simulation defect. This does not rule out bugs elsewhere.
- Intel vs. AMD: the simulation uses the x87 instructions `fpatan` (17 sites, e.g. craft
  orders `0x42af31`, `0x42cd8d`), `fsin`/`fcos` (19/11) and `fptan` (9), and the CRT
  `_CIasin`, `_CIacos`, `_CIpow`. Intel documents that these instructions use an internal π
  approximation; results are not guaranteed to be bit-identical between vendors. Not observed
  (both test instances run on the same CPU); a mixed Intel/AMD match would show it in the sync
  dumps.
