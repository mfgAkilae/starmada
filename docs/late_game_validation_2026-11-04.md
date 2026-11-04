# Late-Game multiplayer validation

The earlier active-player matches were short and contained small fleets. They do
not establish that the reported Late-Game out-of-sync error is fixed. This work
adds a measured load gate; a long idle match cannot pass it.

## Acceptance criteria

Every complete shared peer capture must match after ignoring only the documented
local presentation fields (`isVisible`, `seen`, `local_rng`). The default gate
also requires:

- at least 90 minutes of observed simulation time;
- after the first hour, at least 200 simultaneously alive stock combat ships for
  10 consecutive minutes;
- during that late phase and with that large fleet still present, at least three
  spatially separated active battles for five minutes in total.

Durations count only adjacent matching captures at most 60 seconds apart, with
the condition met at both endpoints. Default captures are 15 simulation seconds
apart. These are sampled observations, not proof about every intermediate frame.
An early peak or early combat followed by a long idle period cannot pass.

`simulation_seconds` comes from the original simulation-millisecond accumulator
at `0x67dcb8`; it is not inferred from wall time or Hook count. Original code
`0x502660` advances it; `0x502740` returns the corresponding float seconds at
`0x67dcb4`. The test-only Hook prints the integer accumulator without touching
the x87 state.

Stock combat ships are alive non-neutral objects of native kind `wingman`.
Constructors, freighters, stations and scenery do not count toward the fleet
threshold. A battle requires a shot within five simulation seconds at another
live player's object. Shooter/target pairs and combatants within 1,000 units in
X/Z form connected battle clusters. Installed weapons are counted separately
from active firing.

## Scenario and reproduction

The trusted GOG 1.2 fixtures use the v1.2.0 simulation fixes and the v1.3.0 runtime
candidate. Two independently controlled Federation players and six stock Hard
AIs play `8open.bzn` on distinct Teams, with 99,999 Crew, 999 Officers and Infinite
Moons. Standard Units and Standard Tech remain enabled.

`late2` and `late3` used the stock maximum starting 10,000 Dilithium. The later
resource stress variant changes only `label.map`'s `sd_value_5` from 10,000 to
1,000,000, byte-identically on both peers, using `prepare_stress_test.py`. It keeps
a backup and records before/after hashes in `stress_fixture.json`. Ship stats,
combat, costs, construction times and the simulation engine remain stock apart
from the released bug fixes. No resource, ship, damage or RNG memory writes are
used. Extra starting resources do not replace the age/load requirements.

```powershell
# Choose a new, absent fixture name. This verifies the GOG source files first.
.venv/Scripts/python.exe tools/prepare_stress_test.py late_ui --dilithium 1000000
powershell -NoProfile -File tools/start_play_test.ps1 -Run late_new -Fixture late_ui -LateGame
.venv/Scripts/python.exe tools/watch_late_game.py late_new --minutes 190
.venv/Scripts/python.exe tools/late_game_metrics.py work/det/late_new --output work/det/late_new/final_summary.json --timeline work/det/late_new/final_samples.jsonl
```

Use a new Run name. `-LateGame` defaults to one dump per 1,000 Hook steps, an
800,000-step exit limit and a 240-minute scoped mouse/focus watchdog. The observer
has a separate wall timeout. Fixed process paths retain Windows audio-session
mute and persistent Private/LocalSubnet firewall rules. Both live native-window
render checks must pass. Input goes only to owned game windows/dialogs. The launcher
refuses another running Armada match: four concurrent GOG clients encountered
display-initialization failures even after the Mutex isolation fix.

Host names are unique per Run. The join helper checks the exact waiting session
name and native GUID before selecting its visible row, preventing a test client
from accidentally joining an older match.

The lower three player-slot dropdowns open upward. Setup checks all six actual
Hard-AI selections, all eight Team selections and the replicated Infinite Moons
flag (`lobby data+0x56 == 1`) on both clients. A native `CB_SETCURSEL` notification
does not apply these custom UI rules; their normal handler runs on mouse release.

The earlier scripted controllers submit build/construction/attack commands through their own client's
original multiplayer output queue. A receipt proves submission, not completion;
native captures must show new objects and damage. Constructors retain their
travel/build order, and their resources stay reserved until native construction
starts. Mining precedes further economy/fleet spending. Controllers inspect state
for planning, so that method is a scripted gameplay stress test.

### Screenshot-guided UI gameplay

`ui_stress2` uses Main for client A (Team 7) and an independent agent for client B
(Team 5). Both inspect rendered frames and use the stock Build menus, green
placement footprints, ship queues, normal selection, Groups, Rally Points and
movement/attack UI. The six other players use the native Hard AI. No direct
build/construction/attack Command-IPC is used in this Run. `watch_late_game.py`
only reads peer captures and does not play.

The virtual test mouse/keyboard feeds the owned client's ordinary UI path; it
does not activate a desktop window or use OS-wide input. The stock Right-Button
mask is 4 (Left 1, Middle 2), corrected in the test proxy and checked natively.
Diagnostic frame readback is normalized with `shot(..., flip_y=True)` for the
known vertical BMP orientation; the actual game renderer is unchanged.

The UI records include unsuccessful placements, incorrect selection attempts,
subsequent corrections and combat losses. A queue receipt or resource charge is
not treated as a completed ship: independent captures verify completed buildings,
new ship objects, health and deaths. B's first bounded UI check verified two
completed Shipyards and six full-health Defiants at step 47,000 / 707.792 seconds.
A subsequently completed two Shipyards and queued Defiants; both players defended
against native attacks. Local evidence lives in `work/det/ui_stress2`, including
`A_ui_actions.jsonl`, `B_ui_actions.jsonl`, screenshots and peer dumps.

## Calibration and pending result

`late2`, the calibration run, captured 68 matching pairs through step 68,000:
1,005 observed simulation seconds, peak 135 combat ships and six battle clusters.
It did **not** pass the Late-Game gate. It exposed controller issues in construction
order ownership and resource reservation, which have regression checks. Both
players completed shipyards and ships; no game fix is inferred from bot mistakes.

| Run | Controls | Observed simulation | Matching pairs | Peak ships / battle clusters | Result |
|---|---|---:|---:|---:|---|
| `late2` | Two scripted command controllers + six AIs | 1,005 s | 68 | 135 / 6 | Below Late-Game duration/load |
| `late3` | Two scripted command controllers + six AIs | 2,343.753 s | 157 | 113 / 7 | Graphics stall; below gate |
| `stress4` | Six AIs; UI exploration without a completed player build | 2,070.776 s | 139 | 105 / 6 | Calibration only; below gate |
| `ui_stress2` | Two screenshot-guided UI agents + six AIs | In progress | In progress | In progress | Gate pending |

`late3` exposed globally shared graphics Mutex names and rendering wait ownership
defects, documented as finding 9. It did not produce a native OOS report. The
candidate includes PID isolation and failure-path cleanup. Live `ui_stress2`
inspection confirms that `CreateMutexA` and `WaitForSingleObject` imports on both
clients point into the proxy, and the actual kernel object names have different
PID suffixes. Both clients pass all three live/shim renderer checks at 640x480.
Their Windows audio sessions are muted. Firewall preflight reused verified
Private/LocalSubnet rules (`changed: false`).

Final measured duration/load and any divergence will be recorded after the UI
Run. This report does not currently claim a passing Late-Game test.

## Limits

This is a two-client match on one PC/CPU. Separate PCs, heterogeneous CPU vendors,
external network conditions and fan mods require more runs. A passing stress gate
would increase coverage; it cannot prove every possible out-of-sync cause is gone.
