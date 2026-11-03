## Star Trek: Armada multiplayer fix v1.0.0

First release. For the GOG version of *Star Trek: Armada* (Armada.exe 1.2,
`setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`).

### How to install (Windows)

1. Download **`Armada_MP_fix.exe`**.
2. Put it into your Armada game folder (where `Armada.exe` is) and **double-click it**.
   (Or drag `Armada.exe` onto `Armada_MP_fix.exe`.)
3. Done. Backups `<file>.armadafix-backup` are created automatically.
4. **Every player in your game needs the fix.** Compare the SHA-256 of `Armada.exe` that the
   tool prints; the main menu shows `v1.2s` instead of `v1.2`. For the GOG installation the
   patched `Armada.exe` has the SHA-256
   `0d8fa21add19801926ebc95752b591a820990bbad4f0b7fb49bf8e4a0d05e76e`.

With Python 3.8+ you can run `armada_fix.py` instead (`apply`, `status`, `restore`).

### What it fixes

- **Out of sync:** ships that dock at a shipyard took their approach angle from a random
  generator seeded with each PC's clock. They now use the game's synchronized generator.
- **Out of sync:** the torpedo renderer cleared a torpedo's target when the shooter was hidden
  by the local fog of war. The renderer no longer changes the target.
- **Crash at start** when the `Logs` folder is missing or read-only.
- **Crash in `ddraw.dll`** when another game with the GOG DirectX wrapper runs at the same time.
- **Windowed mode:** the game runs in a normal, scaled window (`--window WxH` to choose the size).
- **Mouse cursor:** the game no longer replaces the arrow cursor of the whole desktop.

Details and addresses: `docs/findings.md`.

### Known limits

- Not yet tested in a real multiplayer match on two PCs. If an out-of-sync error still
  happens, please send the `Logs\SYNC__…__DUMP__…` files of both PCs.
- A patched and an unpatched `Armada.exe` must not play together.
