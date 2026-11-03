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

## Windowed mode

`dxcfg.ini` of the GOG wrapper: `presentation` = `application` | `fullscreen` | `windowed`;
`display` = `desktop` | `application` | `<w>x<h>@<hz>` (the window size; the game image is
scaled with `scaling` and `aspect`). `display=windowed` is not a valid value. Armada's own
`-window` switch also works, but the menus then use the game's 640×480 window.

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

## Open

- A long multiplayer match on two PCs with the patch.
- Intel vs. AMD: the x87 instructions `fsin`/`fcos`/`fpatan` are not guaranteed to give the
  same last bits on both vendors. Not observed; would need a mixed test.
- Armada allows one instance per PC (`FindWindowA("Armada")` at `0x43b115`), so a local
  two-instance test needs a second PC or a VM.
