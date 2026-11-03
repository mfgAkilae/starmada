## Star Trek: Armada multiplayer fix v1.1.0

For the GOG version of *Star Trek: Armada* (Armada.exe 1.2,
`setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`).

### New in v1.1.0

- **Crash "pure virtual function call" during a match.** The loading screen adds its light to
  the render engine's light list for every loading message and never removes it; when the
  loading screen closes, the light is deleted while hundreds of references to it remain.
  The game then calls methods of the deleted light and writes into its freed memory. Found
  when the host of a test match crashed after about ten minutes. Now a destroyed light
  leaves the light list (runtime proxy `Strlkup.dll`).
- **Two-instance test bed.** Two game instances on one PC play a LAN match against AI players
  and write a full state dump every 50 simulation steps; the dumps of both PCs are compared
  step by step. Four matches with about 173,000 simulation steps (patched and original):
  no difference between the nodes. The AI did not use the docking path of the first sync fix
  in these matches, so this shows no regression and no further cause of divergence in AI
  combat, not the fixed paths themselves.
- **Closing the window (X or Alt+F4) left the game running without a window.** The game now
  ends when its window is closed (in multiplayer the others see you leave).
- The wrapper's shared memory name is now also unique per process at run time, so even a
  second Armada instance cannot crash the first one.

`Armada.exe` is patched exactly as in v1.0.0 (same SHA-256
`0d8fa21add19801926ebc95752b591a820990bbad4f0b7fb49bf8e4a0d05e76e`), so v1.0.0 and v1.1.0
players can play together. The new fixes are in `Strlkup.dll`; run the new tool once to update it.

### How to install (Windows)

1. Download **`Armada_MP_fix.exe`**.
2. Put it into your Armada game folder (where `Armada.exe` is) and **double-click it**.
   (Or drag `Armada.exe` onto `Armada_MP_fix.exe`.) Already on v1.0.0? Just run the new
   version the same way.
3. **Every player in your game needs the fix** (at least v1.0.0 for the sync fix). The main
   menu shows `v1.2s` instead of `v1.2`.

With Python 3.8+ you can run `armada_fix.py` instead (`apply`, `status`, `restore`).

### Known limits

- Not yet tested on two separate PCs, in particular Intel against AMD: the simulation uses
  x87 instructions (`fpatan`, `fsin`, `fcos`) whose last bits are not guaranteed to match
  between CPU vendors. If an out-of-sync error happens, please send the
  `Logs\SYNC__…__DUMP__…` files of both PCs.
- A patched and an unpatched `Armada.exe` must not play together.

Details and addresses: `docs/findings.md`.
