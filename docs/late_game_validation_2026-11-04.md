# Late-Game multiplayer validation

The earlier matches were short or used incomplete player control. They do not
establish that the reported Late-Game out-of-sync error is fixed. A long idle
match cannot pass the measured load gate below.

## Required replacement test

The user rejected the two-controlled-player/six-native-AI method. The replacement
requires **six independently controlled UI player slots, no native opponent AI**,
normal finite resources, mining/deposit/income, economy and technology, explicit
fleet movement/attack/retreat/repair, and actual researched Special Ability casts.
The earlier high-resource run does not satisfy those conditions.

The six-role training protocol is in
[`agent_player_training.md`](agent_player_training.md). Source-backed mechanics
remain distinct from completed in-game drills. Every player must show its own
mining cycle and tactical orders; a queue receipt or Special-key acknowledgement
alone is insufficient. Cast evidence includes Energy and the corresponding
effect or target-state change.

The six-client preparation uses the verified GOG files and stock `label.map`.
The launcher records actual EXE/wrapper/proxy/configuration hashes and startup
timestamps for each peer. Its lobby setup selects stock `6violins.bzn`, 5000
Dilithium, 5000 Crew, 250 Officers, Standard Units/Tech and finite Moons. A/B are
Federation, C/D Klingon, E Romulan and F Borg; A/C/E face B/D/F. These settings
require native lobby readback before a completed scenario record is written.

`launch.json` declares A..F. The observer and offline comparator require every
declared peer; an F-only divergence or a missing F cannot pass as an A/B result.
Run `agents6_2` has all six genuine Human clients in the same match. Each passed
three live/replay render checks (18 total), including a D3D9 device, 640x480
windowed canvas and a render Window owned by the corresponding Process. The
full gameplay/economy/Special training and Late-Game acceptance remain incomplete.

The runtime identity helper reads only each verified client's local Owner and
fixed Alliance row after world initialization. All six copies agreed: A6, B1,
C3, D4, E5, F2; A/C/E are Alliance0 and B/D/F Alliance1. This is recorded in
`runtime_players.json`, with explicit `player_teams` and `player_alliances` in
`launch.json`. It is not inferred from slot numbers or peer count and does not
read unit positions or issue game input. Fixed Alliances must remain unchanged
for this binding to be valid.

The stock Map starts with ten `zentity*` NPCs on Owner8. The earlier unbound
observer counted these as `wingman` fleet and could include NPC fights. Scoped
metrics must count only declared Player-Owners and hostile Alliances; NPCs remain
in the complete raw-state comparison so NPC-only divergence still fails. Legacy
unbound reports describe all non-neutral fleet and cross-Owner firing, rather
than proving Player-vs-Player combat. Do not apply a global Team8 exclusion:
Team8 can be a legitimate Player in another match.

For a fresh six-player run (test proxy Build required):

```powershell
.venv/Scripts/python.exe tools/prepare_play_test.py six_new --players 6
powershell -NoProfile -File tools/start_six_player_test.ps1 -Run six_new -Fixture six_new
.venv/Scripts/python.exe tools/watch_late_game.py six_new --minutes 240
```

The launcher verifies the lobby, render state and runtime Player binding. The
six UI controllers must then actually play; launching Processes does not satisfy
the gameplay requirement. Race plans and source limits are in the
[Race Playbook](race_playbook_2026-11-04.md) and its
[independent source audit](race_playbook_source_audit_2026-11-04.md).

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

Stock combat ships are alive objects of native kind `wingman`, restricted to
explicit Player-Owners when a binding is present.
Constructors, freighters, stations and scenery do not count toward the fleet
threshold. A hostile battle requires a shot within five simulation seconds at
another live Player's object in a different declared Alliance. Without an
Alliance binding the metric identifies cross-Owner firing only. Shooter/target
pairs and combatants within 1,000 units in
X/Z form connected battle clusters. Installed weapons are counted separately
from active firing.

## Historical two-player scenarios and reproduction

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
refuses another running Armada match to preserve the current test. Some earlier
multi-instance attempts encountered display-initialization failures with an
unresolved cause; they do not establish a two- or four-client limit. The later
six-client initialization passed all 18 render checks described above.

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

## Historical calibration results

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
| `ui_stress2` | Two screenshot-guided UI agents + six AIs | 4,261.239 s | 280 | 206 / 7 | Stopped for the replacement method; gate failed |

`late3` exposed globally shared graphics Mutex names and rendering wait ownership
defects, documented as finding 9. It did not produce a native OOS report. The
candidate includes PID isolation and failure-path cleanup. Live `ui_stress2`
inspection confirms that `CreateMutexA` and `WaitForSingleObject` imports on both
clients point into the proxy, and the actual kernel object names have different
PID suffixes. Both clients pass all three live/shim renderer checks at 640x480.
Their Windows audio sessions are muted. Firewall preflight reused verified
Private/LocalSubnet rules (`changed: false`).

`ui_stress2` compared all 280 shared captures through step 280,000 without a
dumped-state difference. Its 71.02 observed simulation minutes, 60 seconds of
sustained late fleet load and 15 seconds of overlapping late combat did not meet
the gate. Mining, resource income, Research and Special Abilities were not played
in that run. It was stopped after the user required six fully played slots.
Raw evidence remains under `work/det/ui_stress2`; this is a limited historical
result, not acceptance of the user's requested test.

## Limits

This is a two-client match on one PC/CPU. Separate PCs, heterogeneous CPU vendors,
external network conditions and fan mods require more runs. A passing stress gate
would increase coverage; it cannot prove every possible out-of-sync cause is gone.
