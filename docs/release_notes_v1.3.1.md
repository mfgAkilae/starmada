# Armada multiplayer fix v1.3.1

Two more GOG renderer paths used an unchecked `GetRenderTarget` output during
depth readback. A failed lookup could call Release through a stale Pointer.
The runtime proxy now guards both paths, restores Dirty/CS ownership correctly,
and returns `DDERR_SURFACELOST` instead of reporting stale readback data as success.

Reapply the patch to upgrade. Only the runtime proxy changes from v1.3.0;
`Armada.exe`, its SHA256, `v1.2s` menu label, assets and network protocol stay the same.
Original backups remain available for Restore.

Validation:

- Original crashes reproduced against the actual GOG DLL; 144 native cases pass
  at each of two module addresses, including ASLR relocation and recursive CS ownership.
- Existing five color-fill Guards, mouse/focus Guard and graphics Mutex checks pass.
- Python and packaged EXE each pass eight installer checks, including direct
  v1.3.0 upgrade with every file except the proxy preserved byte for byte.
- Independent native cleanup and Payload review found no blocking issue.

Full GPU readback/Caller-Recovery, display-off recovery in a real match, the
six-player Late-Game Gate and separate-PC Intel/AMD validation remain open.
The current multi-Process D3D9 initialization failure also reproduces outside
Armada and is not claimed fixed. These changes do not prove that every OOS cause
has been removed. [Evidence and limits](gog_renderer_followups_2026-11-04.md).
