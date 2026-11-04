# GOG renderer follow-ups, 2026-11-04

The v1.3.0 color-fill fix covers five unchecked `GetRenderTarget` calls. It does
not establish that every renderer crash or multiplayer out-of-sync cause is fixed.

## Two more reproducible unchecked outputs

The two calls unchanged in v1.3.0 at GOG DDRAW RVAs `0x2b736` and `0x36d3f` also use the
output of a failed `GetRenderTarget` without checking its HRESULT. They occur in
Surface Lock/depth-readback routines, rather than the optional color fill.

`tools\probe_ddraw_depth_readback.cmd <path-to-GOG-DDRAW.DLL>` maps the actual DLL
without resolving imports or running DllMain. It first installs the five v1.3.0
color-fill Guards, then executes each unchanged GetRenderTarget/Release prefix
against a controlled COM device. At both sites, a failed call with each of three
stale outputs (NULL, `0x3f800000`, object with NULL VTable) causes an AccessViolation.
A successful call returns the expected Surface and executes exactly one Release.
The probe confirms a defect; exit 0 means the expected defect was reproduced.
It does not exercise the whole Lock routine or establish a field occurrence.

REA evidence for the enclosing routines:

- `0x1802ae30`: `ev_000d5074c164bdce58da50485eb6fb54d80c4125e6f0ea7ac3ae542f26584ad9`.
- `0x18036510`: `ev_3b1ba5b37a9a3e280eabf0bafcadefbfb7b4dde7ceef467e16fde3b96cb0e494`.

v1.3.1 adds a separate Guard for both sites. It restores the previously known
dirty state, releases the wrapper's Critical Section exactly once when this call
acquired it, restores the original nonvolatile Registers and Stack, and returns
`DDERR_SURFACELOST` (`0x887601c2`). Locked/Lockflags stay unchanged. The five
color-fill Guards are retained.

The native regression (`tools/test_ddraw_depth_readback.cmd`) first reproduces
the original AccessViolations, then passes 144 cases per mapped address, repeated
at an ASLR-relocated address. Cases cover failed HRESULTs, successful NULL output,
stale outputs, internal skip-CS flags, and pre-existing recursive CS ownership.
The complete 0x8b0-byte Surface Context is compared: only Dirty may change to1.
Success-prefix tests preserve original GetRT/Release and reference counts; they do
not execute a full GPU readback. Independent cleanup and Payload reviews found
no blocking issue. Caller-Recovery and actual lost-device GPU recovery remain open.

The internal CS mask is `flags & 0x10000000`; it is not the public
`DDLOCK_NOSYSLOCK` flag. The optional earlier callback was independently resolved
to `ResetWriteWatch`; it creates no outstanding Release/Unlock requirement.
[Microsoft documents SurfaceLost as a Lock failure](https://learn.microsoft.com/en-us/windows/win32/api/ddraw/nf-ddraw-idirectdrawsurface7-lock).

## Six-client startup failure remains separate

In `agents6_4`, started after the user confirmed an unlocked PC and active display,
clients A and D initialized a 640x480 windowed D3D9 device successfully. B/C/E/F
returned `DDERR_UNSUPPORTEDMODE` (`0x8876024e`) with a NULL D3D9 device and later
crashed at `Armada.exe+0x18207e`. Four minidumps, diagnostics and the two surviving
renderer states are retained locally. The scoped mouse watchdog reported no alert.

Earlier display-off events are relevant to the original late-game crashes, but
their timestamps alone do not establish the cause of this new startup failure.
The GOG SetDisplayMode implementation maps a nonzero CreateDevice result to the
same DirectDraw error. The `agents6_6` trace recorded the original HRESULT as
`D3DERR_NOTAVAILABLE` (`0x8876086a`) for four clients, with valid client Size and
matching Window/Caller Threads; two CreateDevice calls succeeded.

The test proxy now supports opt-in `ARMADA_TEST_D3D_INIT_TRACE=1`. For the known
GOG wrapper, it observes the four CreateDevice call-sites and records their original
HRESULT, Arguments, Window owner/Thread and client Size. It does not change their
Arguments, returned HRESULT, comparison flags, COM interfaces or GPU policy.
Admission requires the PE identity and all four complete instruction signatures;
the default test path is unchanged, and the trace is excluded from production.

`tools\test_ddraw_device_trace.cmd <path-to-GOG-DDRAW.DLL>` verifies disabled and
mismatched-signature admission, then executes the actual GOG retry graph with16
Success/Failure sequences across all four real Call-Sites. It checks Arguments,
HRESULT, retry counts, original comparison/branch targets and Stack balance.
No GPU, Window creation, focus or input is used.

The first experimental COM-interface trace caused its own startup failure in
`agents6_5` and was removed. An initial Call-Site version in `agents6_6` also
overwrote a comparison entered by earlier branches; the full retry-graph test now
covers that failure, and the corrected trace leaves comparisons untouched.
`agents6_7` was interrupted before World initialization and is not gameplay proof.

A separate hidden-window D3D9 program reproduces availability failures across
six Processes without Armada. Serializing creation, other VP modes,
NOWINDOWCHANGES, NULL focus, back-buffer/interval changes and a message pump did
not resolve the failure. VRAM was not exhausted. RTSSHooks was observed; a scoped
diagnostic-only Profile did not resolve it and was removed again. No global RTSS
setting or Armada Profile changed. An AppHelp interceptor delegates unchanged for
windowed calls and is not a proven cause. x86/x64 and LAA probes sometimes succeed
without any change, so those comparisons are temporally confounded.

The six-player Late-Game Gate remains open; failed or interrupted initialization
is not counted as gameplay. No new OOS-elimination claim is made by v1.3.1.

A final isolated backend diagnostic used the official DXVK3.1.1 x86 D3D9 DLL
only beside the probe executable, with its upstream asset digest verified.
It also failed initialization (`VK_ERROR_INITIALIZATION_FAILED` beneath the
Direct3D error), including with implicit Vulkan Layers disabled just for the
probe Processes. No Game installation received this backend. The startup problem
therefore remains a blocker for a new real six-player test; a Windows restart is
the next system-state comparison, not a proven fix.
