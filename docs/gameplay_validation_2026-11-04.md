# Active multiplayer validation, 2026-11-04

Run `play10` used two independently controlled human slots, Borg (A, team 1) and
Klingon (B, team 3), in a TCP/IP LAN match on one Windows PC. There were no AI
slots and no `CommandAllShips` simulation injections. Both players built ships,
issued attack orders, moved into combat, dealt damage and lost units.

The final comparator passed **460 complete dump pairs through simulation step
46,000**. Synchronized RNG state was `0e75a15c`, table index 230 on both peers;
their local RNG states differed. Only presentation visibility and local RNG fields
are excluded by the existing comparator. One additional A dump at step 46,100
has no B partner during shutdown and is outside the verified interval.

## Observed gameplay

| Event | First observed step | Evidence |
|---|---:|---|
| Klingon shipyard completed | 5,700 | New `kyard9`, object `-2147417815`, full health 2,000 |
| Three Klingon destroyers completed | 10,600 / 12,200 / 13,800 | New `kdestroy10`, `kdestroy11`, `kdestroy12`, each with full health 135 |
| Borg construction ship completed | 17,900 | New `bconst13`, object `-2147450576`, full health 700 |
| Scout and destroyer exchanged fire | 17,300 / 17,400 | Both lost health; their `last_enemy_to_hit_me` fields identify each other |
| Borg scout killed | 18,700 | Health fell below zero, then object disappeared |
| First destroyer killed at Borg base | 25,800 | Destroyer health fell below zero; base also took damage |
| Two more destroyers killed | 37,700 / 38,400 | Starbase recorded as enemy attacker; both health values fell below zero |
| New Borg construction ship damaged | 37,700 | `kdestroy12` recorded as enemy attacker; health fell from 700 to 672.892578 |

These are object-state observations, rather than successful-command acknowledgements.
The original scout and three new destroyers were removed after combat. The base and
new construction ship survived. Both game processes remained running until they were
closed deliberately after the verified interval. No exception or watchdog alert was
recorded during the run. Docking and the lost-target fix counters stayed zero here;
their dedicated regression checks and earlier runs remain the evidence for those paths.

## Control path

The test-only proxy accepts a command on the owning client's window during its
normal command-collection message pump, with `[0x6787c4] != NULL`. It calls the
original queue builders; the game sends and executes the resulting records normally:

| Action | Original queue builder | Native record |
|---|---|---|
| Build a ship | `0x470d20` | Opcode 7, order 28, actor ID and eight-byte ODF basename |
| Place a station | `0x470da0` | Opcode 8, order 28, actor ID, ODF basename and world XYZ |
| Attack a target | `0x470bf0` | Opcode 9, order 5, actor and target IDs |

The receiver handlers `0x4c36a0`, `0x4c3740` and `0x4c37e0` resolve the IDs/classes
and validate that the sender owns the actor. The controller also checks local ownership.
Commands are submitted once on the owning client; they are not mirrored into both
simulations. No resources, build timers, health or simulation RNG values are changed
by the controller. Successful construction and combat are checked in subsequent dumps.

`tools/play_input.py` also supplies a virtual mouse/keyboard device for UI diagnostics.
Gameplay in this run used the native queue commands above. A native screenshot attempt
with the GOG wrapper produced black frames apart from the cursor; screenshots were
therefore not used as proof of visible UI operation.

## GOG fixtures and Windows defaults

- The installer reconstruction helper previously missed continuation rows in the GOG
  manifest. `animations/STIntro.bik` was truncated to its first 8 MiB. The repaired helper
  validates each expanded chunk's length/MD5 and the complete file MD5 before writing it.
  All **4,498 files** of the fresh baseline matched the supplied GOG manifest. This was a
  test-fixture defect, not a new game patch or a defect in the normal GOG installer.
- Both fresh game copies use the released v1.2.0 patch, whose executable SHA-256 remains
  `6b3676a95607e5b3b2ccc1ca7272aa9a8af2d0bffeb4da1e7b7f38ac7ff7a9d1`.
  They start with `-nointro -window`; native window mode avoided the earlier display-init
  failures in the background test setup.
- Future gameplay runs reuse `work/play_clients/live/A` and `B`. This preserves the
  executable paths used by Windows mixer preferences and firewall rules; dumps and PID
  files still have distinct run directories.
- The test proxy mutes its Windows audio session **before the first DirectSound create
  call**, outside `DllMain`. Armada imports DirectSound by ordinal 1, so the checked GOG
  IAT slot is intercepted explicitly. Both clients logged HRESULT `00000000` and Windows
  mixer inspection confirmed `Mute=True` without an external mute call in `play10`.
- Program-specific inbound allow rules cover Private/LocalSubnet only. Six rules were
  verified for the fixed A/B paths, the then-running `play8` paths and the two existing
  Armada II test paths. No matching enabled Private block rules were found. Subsequent
  preflights returned `changed=false` without elevation. The helper detects conflicting
  explicit game block rules instead of reporting a false pass.
- The scoped mouse watchdog reported no game focus or cursor confinement. A Windows
  work-area clip was ignored. It exited normally 60 seconds after both clients closed.

## Reproduction and checks

After reconstructing the supplied installer into `work/gog_repaired`:

```powershell
python tools/prepare_play_test.py live
src\strlkup_proxy\build.cmd test
powershell -NoProfile -File tools/start_play_test.ps1 -Run <new-run-name>
```

The launcher verifies the persistent firewall rules before starting either game; only
first-time setup or changed rules require Windows UAC. It refuses an existing run name
or running fixed fixture. Read the new run's dumps to obtain live actor IDs, then issue
commands with `play_input.py <run> <A|B> build|construct|attack ...`. IDs are per-match;
the IDs in this report must not be reused in another match.

Final acceptance command:

```powershell
python tools/cmpdumps.py work/det/play10/A work/det/play10/B --min-step 45000 --min-pairs 450 --state work/det/play10/verified_steps.txt
```

Result: exit 0, `compared 460 steps; first difference: None`. Raw captures remain in
the ignored `work/det/play10` directory; the compact evidence record is
[`validation/play10.json`](validation/play10.json).

A fresh repeat start, `play11`, exercised the final launcher with `ExitAfter=2000`:
both clients started with Windows mixer mute, the firewall preflight again returned
`changed=false`, the launcher confirmed actual simulation dumps from both clients,
and 20 complete dump pairs through step 2,000 matched. Both clients reached the
configured exit step. This startup regression is separate from the active combat run.

Checks also passed: four GOG reconstruction regressions, three sync instruction
replays, two lost-target instruction replays, eight comparator checks, seven Python
patcher integration checks and the native production mouse/focus guard check.
Both DLL variants build with `/W4`; the rebuilt production `.text` and exports match
the embedded release proxy. Runtime command/mute hooks are test-only. The downloadable
v1.2.0 game patch has no new simulation change from this validation work.

## Remaining coverage

- The Borg yard placement attempts did not produce a station, despite sufficient
  inspected resources. Site/placement and prerequisite handling were not fully traced.
  Those attempts are excluded from the successful build count; no speculative game
  patch was applied for them. The independently completed Borg ship is the build proof.
- Foreground mouse/keyboard gameplay and the screenshot/rendering limitation still
  need interactive validation. This test does not establish every UI flow.
- Separate PCs, mixed Intel/AMD CPUs, mods and the user's exact original failing match
  remain untested. This successful match does not prove all out-of-sync causes absent.
