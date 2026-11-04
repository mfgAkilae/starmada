## Star Trek: Armada multiplayer fix v1.3.0

For the GOG 1.2 RDNA-fix release. Install by putting `Armada_MP_fix.exe` beside
`Armada.exe` and double-clicking it. Existing installations can apply the new
version directly; original backups remain available for `restore`.

### Crash when the screen turns off during a match

When Windows switches the display off (locked PC with display timeout, or the
power plan), Direct3D 9 loses the graphics device. GOG's DirectX wrapper then
calls `GetRenderTarget`, ignores the failure and releases an uninitialized
pointer: every Armada window of the PC crashes at once. In a six-client test
match all clients crashed 8 seconds after Windows logged the display switching
off (crash dumps at `ddraw.dll+0x398c1`/`+0x398c3` and `Armada.exe+0x183dbd`).

The runtime proxy now checks the result at all five color-fill routines of the
known GOG wrapper build and takes the wrapper's own "no GPU clear" path on
failure. The wrapper already resets a lost device in its present path, so the
match can go on after the screen comes back. Other wrapper builds are left
unchanged.

Not yet verified on a real lock: please test Win+L during a match, wait until
the screen is off, unlock, and check that the game continues.

### Graphics stalls

Armada gives two graphics Mutexes fixed names. Multiple instances in the same
Windows Session consequently share Locks despite having separate render state.
The runtime proxy now gives these two names a PID suffix. Other Mutex names and
creation attributes retain their original behavior.

The GOG cursor renderer also keeps its Offscreen Lock when a second acquire
fails. An abandoned Mutex is acquired by Windows, but the original renderer
returns without releasing it. A signature-checked runtime Hook releases the
ownership that these failure paths acquired, preserving the original failure
return and `GetLastError()`.

This fixes independently reproduced graphics ownership defects. The observed
multiplayer stall is documented separately from an out-of-sync error; this
release does not claim that every multiplayer failure has been eliminated.

### Verification

- Native Windows tests reproduce the original cross-process collision and Lock
  leaks, then pass with the production helpers and actual Wait wrapper. Coverage
  includes recursive ownership, abrupt Thread/Process exit, timeout, abandonment,
  `WAIT_FAILED`, LastError preservation and unrelated Mutexes.
- `tools/test_ddraw_render_target.cmd` maps the original GOG wrapper without
  running it: at each of the five color-fill sites the original code crashes on
  a failed `GetRenderTarget`, the guarded code skips the GPU clear with the stack
  and registers intact, and successful calls keep the original sequence (also
  with the wrapper relocated). A two-instance test match ran with the guard
  installed at all five sites in both clients.
- Python and packaged-EXE installation checks pass, including apply/reapply,
  restore, unsupported builds and mod-library collisions. An actual v1.2.0 to
  v1.3.0 EXE upgrade replaces the proxy while preserving original backups; restore
  recovers original GOG bytes.
- Existing sync instruction replays, lost-target crash replays, comparator and
  production mouse/focus guard checks pass.
- The required six-player UI validation includes real mining/economy, fleet
  movement/combat and Special Abilities; it remains pending. The earlier
  two-controlled-player/six-native-AI run is a limited historical result. Methods,
  measured duration, load requirements and limits are recorded in
  [the Late-Game report](https://github.com/mfgAkilae/starmada/blob/v1.3.0/docs/late_game_validation_2026-11-04.md).

### Compatibility and limits

`Armada.exe` and the multiplayer protocol are unchanged from v1.2.0. Its SHA-256
remains `6b3676a95607e5b3b2ccc1ca7272aa9a8af2d0bffeb4da1e7b7f38ac7ff7a9d1`;
the menu therefore still shows `v1.2s`. The patcher and proxy identify themselves
as v1.3.0. Update every player to retain the same runtime fixes.

The failed-wait Hook requires the exact GOG code signature. Data-only mods retain
their file formats and simulation behavior; no fan project has been validated
in a long match. Mods that replace the renderer, reopen its Mutexes through
additional Handles, or rely on cross-process graphics Locks need separate
testing. Separate-PC and mixed-CPU multiplayer remain unverified.

Earlier multi-instance attempts encountered device-creation failures; the last one
(`agents6_3`) started while the display was off, and they do not establish a
two-client limit. The later six-client
initialization passed 18 render checks, including per-Process Window ownership.
The full six-player gameplay and sustained Late-Game load acceptance remain open.
