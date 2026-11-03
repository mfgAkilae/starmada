# Star Trek: Armada – multiplayer fix and windowed mode

Multiplayer games of *Star Trek: Armada* (Activision, 2000) end again and again with
**"This network game is out of sync. You are advised to exit the game."**, often late in a
match. The bug was never fixed officially.

This repository contains **armada_fix**, a patcher for the GOG release of the game
(`setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`, Armada.exe 1.2), and the tools used to
reverse engineer it. The patch removes the two causes of the out-of-sync error that we found,
fixes several crashes, and makes the game run in a normal window, so you can keep using
your PC while you play.

No game files are included. You need your own copy of the game.

## What it fixes

| Problem | Cause | Fix |
|---|---|---|
| "out of sync" in multiplayer, typically after a while | Ships that dock at a shipyard take their approach angle from a random generator seeded with the local clock, so every PC puts them somewhere else | These 3 calls use the game's synchronized random generator |
| "out of sync" in multiplayer, fights with torpedoes | The torpedo renderer clears a torpedo's target when the shooter is hidden by the local fog of war; the simulation uses that target | The renderer no longer changes the target |
| Crash without a message at start when the `Logs` folder is missing or read-only | A debugger break (`int3`) after the failed `fopen` | The game starts without file logging |
| Crash in `ddraw.dll` when another game with the GOG DirectX wrapper runs (e.g. Armada II) | The wrapper shares its Direct3D device pointer through a session-wide shared memory name and reads the other game's pointer | The name is unique to the game and, at run time, to the process |
| Crash "pure virtual function call" during a match (v1.1.0) | The loading screen leaves hundreds of references to its deleted light in the render engine's light list; the engine then calls and writes into the dead object | A destroyed light leaves the light list |
| All players crash at the same moment during a match (v1.2.0) | A ship whose target of order 8 no longer exists reads through a null pointer; the simulation is the same on every PC | The handler returns, as it already does on its other branch |
| The mouse is caught in the game window, also when the window is in the background (v1.2.0) | GOG's wrapper confines the cursor to the window (`ClipCursor`) to emulate fullscreen, and the game re-centres it during a match | Both only while the game window is in front; Alt+Tab releases the mouse |
| Closing the window (X, Alt+F4) leaves the game running invisibly (v1.1.0) | The game window ignores `WM_CLOSE`; Windows destroys the window and the game runs on without it | The game ends when its window is closed |
| The game changes the mouse arrow of the whole desktop, and keeps it after a crash | Armada shows its cursor with `SetSystemCursor` | The cursor applies to the game's windows only |
| Fullscreen only | GOG's wrapper supports a window, but is set to fullscreen | `dxcfg.ini`: `presentation=windowed` and a window size |

Details, addresses and the evidence for each finding: [`docs/findings.md`](docs/findings.md).

## How to install (Windows)

1. Install the game with the GOG installer (as administrator; it enables DirectPlay, adds the
   firewall rule and creates the `Logs` and `save` folders).
2. Download **[`Armada_MP_fix.exe`](https://github.com/mfgAkilae/starmada/releases/latest/download/Armada_MP_fix.exe)** from the latest release.
3. Put it into the game folder (where `Armada.exe` is) and **double-click it**
   (or drag `Armada.exe` onto it).
4. **Every player in your game needs the fix.** The tool prints the SHA-256 of the patched
   `Armada.exe`; it must be the same on every PC. The main menu shows `v1.2s` in the lower
   right corner instead of `v1.2`.

With Python 3.8 or later you can use `release/armada_fix.py` instead of the exe:

```
python armada_fix.py apply   "C:\GOG Games\Star Trek Armada"
python armada_fix.py apply   "C:\GOG Games\Star Trek Armada" --window 1280x960
python armada_fix.py status  "C:\GOG Games\Star Trek Armada"
python armada_fix.py restore "C:\GOG Games\Star Trek Armada"
```

Without `--window` the tool picks the largest 4:3 window that fits 80 % of the screen height.
`--window native` uses the game's own resolution (640×480 in the menus), `--no-window` keeps
fullscreen. Before its first change to a file the tool saves `<file>.armadafix-backup`;
`restore` puts every file back byte for byte.

Tip: `Armada.exe -nointro` skips the intro videos.

## Compatibility

- The patch changes 22 bytes in `Armada.exe` (21 bytes of code, 1 byte of the menu label), one 9-byte name in
  `ddraw.dll`, and puts a small proxy in front of `Strlkup.dll`. File layout, data formats and
  the network protocol stay the same. Mods that only replace game files (ODF, SOD, textures,
  maps, sounds) keep working.
- The tool finds every patch site by its code signature, not by a fixed address. If a modded
  `Armada.exe` does not contain the expected code, the tool stops and changes nothing.
- Invalid window options and a collision with an existing `Strlkup_orig.dll` are rejected
  before any game file changes. `apply` is idempotent; `restore` recovers the original files.
- A patched and an unpatched `Armada.exe` must not play together: the patch changes when the
  synchronized random generator is used.

## Tested

- Static analysis of `Armada.exe` (Ghidra via REA, capstone): every use of both random
  generators, the render pass, the simulation tick, the AI script engine, the sync check.
- On Windows 11 with the GOG installation: the game starts and shows the menus in the window
  (also scaled to 1280×960 and 1920×1440 on a 150 % display), the desktop cursor stays
  unchanged during and after the game, the game starts without a `Logs` folder, and it no
  longer crashes when other processes hold the wrapper's shared memory names.
- **Two-instance test bed (v1.1.0):** two game instances on one PC play a LAN TCP/IP match
  against two Hard AIs; both write a full state dump every 50 simulation steps and
  `tools/cmpdumps.py` compares them. About 173,000 simulation steps in four matches (patched
  and original): no difference between the two nodes. The AI never used the docking path of
  the first sync fix in these matches, so the test bed shows "no other divergence, no
  regression", not yet the fixed paths themselves. Details: `docs/findings.md`.
- **Docking path (v1.2.0):** the test bed sends every ship to a shipyard (order 23) every
  4,000 steps. Original exe: both instances crashed in the same step (finding 8). Patched exe:
  docking draws from the synchronized generator, no difference between the nodes, no crash.
  Final run mp8: 40,000 steps, 800 matching dump pairs, 40 docking draws per node; both
  instances reached the configured exit step.
  Test instances run in the background and never take the focus or the mouse.
- **Not yet tested: a match on two separate PCs**, in particular with an Intel and an AMD CPU
  (see `docs/findings.md`, "Open"). If an out-of-sync error still happens, see below.
- **Instruction replays (v1.2.0):** actual GOG x86 instructions run in Unicorn with two local
  seeds or two visibility fixtures. All three original docking calls produce different angle
  indices; patched calls agree. The original torpedo renderer changes the target only for
  the hidden-shooter fixture; the patched renderer preserves it for both. These are isolated
  checks, separate from a real multiplayer match.
- **Release tool (v1.2.0):** apply/reapply/restore, unsupported exe, invalid window option,
  mod-library collision, double-click and drag-and-drop checked on copies of the GOG files.
  The production mouse guard is also checked with recording callbacks: a background game
  cannot call the real mouse-move, clip or wrapper focus functions, and releases only its
  own clip. Foreground gameplay and Alt+Tab still require an interactive check.

## If "out of sync" still happens

At the first out-of-sync error the game writes a state dump to
`Logs\SYNC__<name>__DUMP__…` on every PC (random generator values, every game object, weapon
and torpedo). Compare the dumps of two PCs with `diff`; the first different line names the
object that drifted. Please open an issue with both files.

## Files

- `release/armada_fix.py` – the patcher (Python 3, no dependencies, includes the proxy DLL)
- `src/strlkup_proxy/` – source of the `Strlkup.dll` runtime proxy (`build.cmd`, VS 2022 Build Tools, x86)
- `docs/findings.md` – reverse engineering results with addresses
- `docs/release_notes_v*.md` – release notes
- `tools/` – analysis and test helpers:
  - `gog_unpack.py` – rebuilds the game files from an `innounp -x` extraction of the GOG installer
  - `pe.py`, `xref.py`, `ctxdis.py`, `audit_callers.py`, `vcall.py`, `reach.py`, `rng_ancestors.py`, `hier.py` – disassembly, RTTI vtable map, call sites, reachability
  - `probe.py`, `launch.ps1`, `trycfg.ps1`, `clickseq.py`, `cursorhash.py`, `fake_dxfilemap.py` – runtime checks (windows, screenshots, FPU control word, cursor, wrapper mapping)
  - `mp_match.ps1`, `mp_inst.ps1`, `start_bg.py`, `clk.py`, `drag.py`, `shot.py`, `cmpdumps.py`, `watch_mp.sh`, `mouse_watchdog.py` – two-instance multiplayer test bed (needs the test build of the proxy, `src\strlkup_proxy\build.cmd test`)
  - `make_release.py` – builds the proxy, embeds it into the patcher, packs `Armada_MP_fix.exe`
    (`python -m PyInstaller --onefile --console --name Armada_MP_fix release/armada_fix.py`) and writes `SHA256SUMS.txt`
  - `test_sync_instructions.py` – isolated instruction replays (requires `pefile`, `unicorn`)
  - `test_order8.py` – lost-target crash and surviving-branch regression replays
  - `test_patcher.py`, `test_cmpdumps.py`, `test_mouse_guard.cmd` – patcher, comparator and
    production background mouse-guard checks

## License

MIT, see [LICENSE](LICENSE). *Star Trek: Armada* is a trademark of its owners; this project is
not affiliated with them.
