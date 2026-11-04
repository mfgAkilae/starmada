# GOG wrapper render-target crash

The real six-Human-slot match `agents6_2` stopped producing captures at step
688250, simulation time 10368.213 seconds. Its 2753 complete six-peer capture sets
matched, including NPC state. The sustained large-fleet gate did not pass: the
peak was 145 player combat Ships, below the required 200. Four spatial battle
clusters occurred, but the combined large-fleet/concurrent-combat criterion was
not met. This is not evidence that all late-game OOS problems are fixed.

All six recorded clients exited. Four Windows crash dumps and their WER Reports
were preserved locally under `work/det/agents6_2/crash_20261104_201031/`, together
with module copies, SHA-256 hashes and the last observer result. The reason for
the two exits without preserved dumps is unknown.

## Observed crash path

The installed GOG DirectX 1-7 wrapper reports Product Version `1.1.0.3494`, PE
timestamp `0x61dd5c00`, and Image Size `0x561000`. The on-disk wrapper, including
the previous shared-memory-name fix, had SHA-256
`6c05d0be22b6ab7982797a5d1dc1a5a0bcd69346acac5a0a7072cf37cc5fe69a`.

| Client | Exception | Location | Observed invalid access |
|---|---|---|---|
| F | `0xc0000005` | `ddraw.dll+0x398c1` | Read through `0x3f800000` |
| D | `0xc0000005` | `ddraw.dll+0x398c1` | Read through NULL |
| C | `0xc0000005` | `ddraw.dll+0x398c3` | Read through a NULL VTable at `+8` |
| B | `0xc0000005` | `Armada.exe+0x183dbd` | Invalid virtual call from the same wrapper `Release` site; return address `ddraw.dll+0x398c6` |

At wrapper RVA `0x398b6`, the Surface color-fill path calls D3D9
`GetRenderTarget(0, &local)`. It ignores HRESULT and immediately invokes
`local->Release()`. The local was not initialized. It then temporarily changes
the render target, performs a GPU clear, restores the previous target and
continues through its existing CPU fill.

The dump Contexts identify the bad output use. They do not retain the earlier
HRESULT or all Surface heap data.

## Trigger: the display was switched off

The Windows System log shows the trigger. `Microsoft-Windows-Kernel-Power` event 566
("The system session has transitioned from 64 to 66") was logged at 21:10:19 local
time, with `PreviousSessionType` 1 and `NextSessionType` 0: Windows switched the
display off. The four Application Error events (1000) of the clients follow at
21:10:27. All evening these screen-off transitions alternate with screen-on
transitions whose reason is `SessionUnlock`, so the session was locked while the
display was off. When the display goes off (locked PC, power plan timeout), Direct3D 9
loses the device, `GetRenderTarget` fails, and the wrapper uses its uninitialized
output. All six clients were hit at once because this affects every process of the
session.

So a player whose screen turns off during a windowed match (Win+L with the display
timeout, or the power plan) crashes. Windows' audit and Winlogon logs on this PC hold
no lock events for the evening, so lock and display-off are not separated here. The wrapper itself handles a lost device elsewhere: its present path
checks `TestCooperativeLevel` (`D3DERR_DEVICELOST` waits, `D3DERR_DEVICENOTRESET`
releases its resources and resets the device, around RVA `0x20545`), so after the
unlock it can render again once the color-fill path no longer crashes.

The failed restart `agents6_3` followed another display-off event at 21:53:11,
and the clients started at 21:59 reported
`hr=8876024e` (`DDERR_UNSUPPORTEDMODE`) for the test-only native-window mode switch,
followed by four crashes at `Armada.exe+0x18207e`. That path exists only in the test
proxy (`ARMADA_TEST_NATIVE_MODE_INIT`). A later restart, `agents6_4`, reproduced
four initialization failures after the user confirmed an active display while two
clients initialized successfully. The cause of those startup failures is still
open; see the [renderer follow-ups](gog_renderer_followups_2026-11-04.md).
Microsoft documents failure returns for
[GetRenderTarget](https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-idirect3ddevice9-getrendertarget)
and requires the reference returned on success to be released.

## Runtime change

`Strlkup.dll` installs a small x86 thunk when the known GOG wrapper loads.
Admission requires the PE architecture, timestamp, Image Size, complete call-site
signature and the existing continuation signature. Unsupported builds are not
modified. The installed Hook is idempotent and uses relative code addresses.

The thunk initializes the output to NULL, calls the original method once, and
checks both HRESULT and the output. On failure it takes the wrapper's existing
no-GPU-clear path at RVA `0x39915`. On success it resumes the original sequence,
including its single Release.

The same unchecked block exists in five color-fill routines, one per surface slot
of the surface context (`+0x898` … `+0x8a8`): RVAs `0x27bab`, `0x2e3de`, `0x3104e`,
`0x33d1e` and `0x398b6`. The crash dumps only reached `0x398b6`, but a lost device
fails all of them. Each site gets its own thunk; its failure target is the
destination of the wrapper's own `test ah,0x10; jne` right before the block
(`0x27c6c`, `0x2e49f`, `0x3110f`, `0x33ddf`, `0x39915`), which the installer checks
byte for byte. All five sites must match before any is changed.

Two other `GetRenderTarget` uses (`0x2b736`, `0x36d3f`) follow a different pattern
without a preceding skip branch. They are not changed; no dump reached them. The existing CPU fill is retained. No simulation,
ODF, save format or network-protocol change is made; Armada.exe remains byte
identical to v1.2.0.

## Verification

`tools/test_ddraw_render_target.cmd <owned GOG DDRAW.DLL>` maps the actual wrapper
without running its DllMain, supplies a controlled D3D9 interface, and executes
its original GPU-clear instructions. It does not use a GPU, change a display
mode, start a game, or provide desktop input.

- At each of the five sites the original instructions produce three Access
  Violations for invalid outputs.
- The Guard rejects a different build, a modified call signature, a modified skip
  branch and a modified continuation (no site changed), and repeated installation
  reuses the same thunks.
- At each site four failed HRESULTs and a success with no output skip Release,
  target changes and Clear, retaining the stdcall stack and nonvolatile registers.
- Successful calls preserve the original call sequence, arguments and one
  Release; the original successful path also runs as a baseline.
- The checks also pass with the wrapper relocated to another base address.
- In a running two-instance match (`mp10`) all five sites of both clients carried
  the thunk call (`e8 … 90`, read with `ReadProcessMemory`).
- Not tested here: an actual display-off/lock and unlock during a match, because it
  needs the PC's user. That is the decisive manual check (Win+L, wait until the
  screen is off, unlock, the match must go on).
- The existing native Graphics-Mutex and background Mouse/Focus suites pass.

The new long six-player run is separate evidence. Native regression success does
not prove recovery from every graphics-device failure or complete late-game
multiplayer correctness. Third-party renderer replacements and fan projects
still need their own compatibility matches. Game binaries and dumps are not
included in the Repository or release assets.
