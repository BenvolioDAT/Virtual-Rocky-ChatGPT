# Screen Vision diagnosis and validation — October 9, 2026

This records the earlier managed-capture baseline. For the subsequent local
Watch, temporal memory, crop tiers and scalable-face validation, see
[Screen Watch and face extensions](screen-watch-and-face.md).

## Reproduced failure

The original helper was tested before changing its capture implementation.
One authenticated localhost session completed 25 consecutive real Windows
captures: primary twice, monitor 2, primary again, all monitors, then primary
20 times. Pause denied capture; resume allowed it again. No image was saved or
uploaded. This did not reproduce a single-use token, MSS resource leak or helper
capture failure on this machine.

A separate failure was reproduced in the original Rocky request gate:

- `Can you see the YouTube video I pulled up?` → `wants_screen=False`.
- `Can you see it now?` → `wants_screen=False`.
- Calling the desktop tool then returned no image before contacting the helper.
- Generic “see” wording could simultaneously select the webcam path, producing
  “camera has no fresh frame” during a desktop conversation.

The defect was in application turn routing: a small keyword list controlled a
thread-local capture permission that was recalculated without visual follow-up
context. Successful desktop use did not authorize the next legitimate screen
follow-up. These are proven failure paths, not evidence that every previously
observed failure had the same cause; the old implementation did not keep useful
capture/session diagnostics.

The fix extends desktop vocabulary, preserves the source of short visual
follow-ups, and scopes permission to the shared brain reply generator with
cleanup in `finally`. Explicit webcam questions switch sources. Desktop turns
discard webcam input, block webcam tools, and request a fresh desktop image.
Normal conversation does not authorize capture. Both model transports share
this routing and cleanup policy. Metadata logs now distinguish gate rejection,
invalid authentication, timeout, capture errors and connection loss.

## Managed helper

Explicit Enable launches one visible child process with a fresh environment
token, waits for its readiness message and dynamic loopback port, authenticates
and discovers monitors. The helper contains the capture backend; Rocky contains
the client and lifecycle manager. Pause/resume retain the same session. Disable
revokes local access immediately, discards late responses, requests graceful
exit and falls back to termination. A Windows parent-process handle closes the
helper after abrupt Rocky exit. No automatic process restart or persistence is
added. Desktop access still defaults to disabled.

## Results

- Full automated suite: **70 tests passed**, covering both mocked model
  transports, physical/virtual body behavior, webcam, TTS flow, face rendering,
  managed lifecycle, repeated capture, auth, pause/resume, reconnect limits,
  in-flight revocation and independent screen-control handling.
- Real Windows managed-helper diagnostic: **passed** with one uninterrupted
  helper session. All three individual monitors and the virtual desktop were
  captured; **20/20** repeated primary captures passed; pause denial,
  resume, same-session reconnect, graceful shutdown, credential cleanup and
  disabled capture denial passed. JPEGs were decoded/verified in memory.
- Display geometry: three 1920×1080 monitors at `(0,0)` (primary), `(1920,1)`
  and `(0,-1080)`. The all-monitor image was resized to 3838×2160.
- Separate process test: abrupt parent exit caused its real owned helper to
  exit; no capture was requested in that test.
- Rocky face-window smoke check, source compilation and `git diff --check`:
  passed.

The Windows diagnostic does not send screenshots to any model. Provider replay
and image cleanup are tested using mocked model responses. Real cloud-model
answers, speech recognition of the new phrases, and a rebuilt packaged
executable were not exercised during this validation.
