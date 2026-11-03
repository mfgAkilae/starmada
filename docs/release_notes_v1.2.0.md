## Star Trek: Armada multiplayer fix v1.2.0

For the GOG version of *Star Trek: Armada* (Armada.exe 1.2,
`setup_star_trektm_armada_1.2_rdna_fix_(52907).exe`).

### New in v1.2.0

- **All players crashed at the same moment during a match.** When a ship's target of order 8
  no longer exists, the game reads through a null pointer. The simulation runs the same on
  every PC, so every player crashes in the same step. The handler now returns instead, as it
  already does for a missing target on its other branch. Found in the two-instance test bed
  when every ship was sent to a shipyard: both instances crashed at the same step
  (`Armada.exe+0x2affa`). Verified in a test match that gives order 8 to every ship (mp9):
  the fixed path ran 116,000 times on each node, no crash, no difference between the nodes.
- **The mouse was caught in the game window, also when the window was in the background.**
  GOG's DirectX wrapper confines the cursor to the game window to emulate fullscreen
  (`ClipCursor`). During a match the game also puts the cursor back to the window centre. Both
  now happen only while the game window is in front. Alt+Tab releases the mouse, and a game
  in the background never moves or holds it (runtime proxy `Strlkup.dll`). The wrapper's
  focus calls are guarded too, so they cannot reactivate a background game before the
  cursor check. Recording callbacks cover the production background guard; an interactive
  foreground/Alt+Tab check remains open.
- **Docking path tested.** The test bed now sends every ship to a shipyard (order 23). In a
  final patched run (mp8), the docking approach angle was drawn 40 times on both
  nodes with no divergence in 800 compared dumps through 40,000 simulation steps. Both
  instances reached the configured exit step with no crash or mouse/focus alert. The
  original exe crashed at about step 20,450 in this scenario (a different match seed).
- **Both sync bugs reproduced in isolated instruction checks.** With different local seeds,
  all three original docking calls produce different angle indices; patched calls agree.
  With visible/hidden shooter fixtures, the original torpedo renderer produces target ids
  `[22, 0]`; patched code preserves `[22, 22]`. These execute actual GOG x86 instructions,
  with explicit fixtures for lookup/visibility, and do not replace a two-PC test.
- **Safer installation.** Invalid window options and existing mod-library collisions now
  stop before changing any game file. Apply/reapply/restore, double-click and drag-and-drop
  are checked with both the Python tool and the packaged exe.
- **Reliable multiplayer comparisons.** A divergence or zero compared dumps is an error;
  old cache entries cannot hide a new run. New dumps are published only after completion.

Validation: 8 comparator tests, 3 sync instruction tests, 2 lost-target instruction tests,
7 patcher checks for Python and the same 7 for the packaged exe, and the native production
mouse/focus helper pass. Both DLL variants build with `/W4`. Upgrade from v1.1.0 preserves
the original backups and restore recovers the original GOG files byte for byte.

`Armada.exe` changes (2 bytes), new SHA-256
`6b3676a95607e5b3b2ccc1ca7272aa9a8af2d0bffeb4da1e7b7f38ac7ff7a9d1`. The change affects only
the moment where the old exe crashes, so v1.1.0 players stay in sync with v1.2.0 players until
then. Update all players anyway; otherwise the crash still hits the players with the old exe.

### How to install (Windows)

1. Download **`Armada_MP_fix.exe`**.
2. Put it into your Armada game folder (where `Armada.exe` is) and **double-click it**.
   (Or drag `Armada.exe` onto `Armada_MP_fix.exe`.) Already on v1.0.0 or v1.1.0? Run the new
   version the same way.
3. **Every player in your game needs the fix.** Compare the SHA-256 that the tool prints. The
   main menu shows `v1.2s` instead of `v1.2`.

With Python 3.8+ you can run `armada_fix.py` instead (`apply`, `status`, `restore`).

### Known limits

- Not yet tested on two separate PCs, in particular Intel against AMD: the simulation uses
  x87 instructions (`fpatan`, `fsin`, `fcos`) whose last bits are not guaranteed to match
  between CPU vendors. If an out-of-sync error happens, please send the
  `Logs\SYNC__…__DUMP__…` files of both PCs.
- A patched and an unpatched `Armada.exe` must not play together.

Details and addresses: `docs/findings.md`.
