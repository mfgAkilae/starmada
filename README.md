# Star Trek: Armada – multiplayer fix and windowed mode

Multiplayer games of *Star Trek: Armada* (Activision, 2000) end again and again with
**"This network game is out of sync. You are advised to exit the game."**, often late in a
match. The bug was never fixed officially.

This repository contains **armada_fix**, a patcher for the GOG release of the game
(`setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`, Armada.exe 1.2), and the tools used to
reverse engineer it. The patch removes the two causes of the out-of-sync error that we found,
fixes a start-up crash, and makes the game run in a normal window, so you can keep using
your PC while you play.

No game files are included. You need your own copy of the game.

## What it fixes

| Problem | Cause | Fix |
|---|---|---|
| "out of sync" in multiplayer, typically after a while | Ships that dock at a shipyard take their approach angle from a random generator seeded with the local clock, so every PC puts them somewhere else | These 3 calls use the game's synchronized random generator |
| "out of sync" in multiplayer, fights with torpedoes | The torpedo renderer clears a torpedo's target when the shooter is hidden by the local fog of war; the simulation uses that target | The renderer no longer changes the target |
| Crash without a message at start when the `Logs` folder is missing or read-only | A debugger break (`int3`) after the failed `fopen` | The game starts without file logging |
| Crash in `ddraw.dll` when another game with the GOG DirectX wrapper runs (e.g. Armada II) | The wrapper shares its Direct3D device pointer through a session-wide shared memory name and reads the other game's pointer | The name is unique to the game and, at run time, to the process |
| The game changes the mouse arrow of the whole desktop, and keeps it after a crash | Armada shows its cursor with `SetSystemCursor` | The cursor applies to the game's windows only |
| Fullscreen only | GOG's wrapper supports a window, but is set to fullscreen | `dxcfg.ini`: `presentation=windowed` and a window size |

Details, addresses and the evidence for each finding: [`docs/findings.md`](docs/findings.md).

## How to install (Windows)

1. Install the game with the GOG installer (as administrator; it enables DirectPlay, adds the
   firewall rule and creates the `Logs` and `save` folders).
2. Download **`Armada_MP_fix.exe`** from the latest release.
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

- The patch changes 20 bytes in `Armada.exe` (19 bytes of code, 1 byte of the menu label), one 9-byte name in
  `ddraw.dll`, and puts a small proxy in front of `Strlkup.dll`. File layout, data formats and
  the network protocol stay the same. Mods that only replace game files (ODF, SOD, textures,
  maps, sounds) keep working.
- The tool finds every patch site by its code signature, not by a fixed address. If a modded
  `Armada.exe` does not contain the expected code, the tool stops and changes nothing.
- A patched and an unpatched `Armada.exe` must not play together: the patch changes when the
  synchronized random generator is used.

## Tested

- Static analysis of `Armada.exe` (Ghidra via REA, capstone): every use of both random
  generators, the render pass, the simulation tick, the AI script engine, the sync check.
- On Windows 11 with the GOG installation: the game starts and shows the menus in the window
  (also scaled to 1280×960 and 1920×1440 on a 150 % display), the desktop cursor stays
  unchanged during and after the game, the game starts without a `Logs` folder, and it no
  longer crashes when other processes hold the wrapper's shared memory names.
- **Not yet tested: a real multiplayer match on two PCs.** The causes are shown in the code;
  that the error is gone in a long match still needs a test. If an out-of-sync error still
  happens, see below.

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
  - `make_release.py` – builds the proxy, embeds it into the patcher, packs `Armada_MP_fix.exe`
    (`python -m PyInstaller --onefile --console --name Armada_MP_fix release/armada_fix.py`) and writes `SHA256SUMS.txt`

## License

MIT, see [LICENSE](LICENSE). *Star Trek: Armada* is a trademark of its owners; this project is
not affiliated with them.
