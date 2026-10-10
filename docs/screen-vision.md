# Optional Screen Vision

The current implementation also supports explicit local **Screen Watch**, RAM
visual history, active-window/region capture and overview/detail tiers. See
[Screen Watch and face details](screen-watch-and-face.md) for these extensions.

Start Virtual Rocky normally. Desktop access is **Disabled** by default, and
Rocky works without the helper or its optional dependencies.

## Install and use

From the project directory:

```powershell
server\.venv\Scripts\python.exe -m pip install -r server\requirements-screen.txt
```

1. Launch `launch-virtual.cmd`.
2. Right-click Rocky and open **Screen Vision**.
3. Choose **Enable Screen Vision**. A separate, visible helper window opens.
4. Wait for **Connected**, then ask a desktop question.
5. Choose **Disable Screen Vision** when finished.

No token, address, or port needs to be entered. Rocky creates a random token in
memory, passes it through the child process environment, and authenticates after
the helper announces its randomly allocated loopback port. Tokens are never
shown, logged, written to `.env`, or saved. Every helper launch creates a new
session. The public session ID in diagnostics is not an authentication token.

The menu also provides:

- **Pause Screen Access**: keep the helper alive but deny screenshots.
- **Resume Screen Access**: permit captures again in the same session.
- **Monitor List**: display monitor IDs, positions, resolutions and primary flag.
- **Status**: display state, child PID, monitor count, last request/capture and
  connection age. No credentials or images are included.
- **Test Screen Vision**: explicitly take one fresh primary-monitor screenshot,
  validate it, report dimensions/metadata, and discard it. No model upload.

The helper window has its own Pause, monitor-list and Exit controls. Closing it
changes Rocky to Offline; it is never automatically relaunched. Enable explicitly
starts a new session. A live helper with a dropped connection gets at most three
status/reconnect attempts using its existing credentials, about one second apart
with a five-second timeout per request. After failure Rocky shows Error and stops
retrying until an explicit reconnect or Enable action. Captures themselves are
not retried automatically. Status checks never capture images.

Disable immediately revokes local access, discards in-flight capture responses,
asks the owned helper to exit, waits briefly, then terminates it if necessary.
Rocky also shuts down the child on exit. On Windows the child watches the parent
process handle and exits if Rocky disappears. No service, scheduled task, Windows
startup entry or automatic restart is installed.

`START_SCREEN_VISION = False` in `server/brain/config.py` is the default. Changing
it to True deliberately enables managed helper startup when Rocky starts. This
still does not register Rocky or the helper with Windows startup.

## Monitors and questions

Monitor IDs follow Windows/MSS enumeration for the current display configuration,
and may differ from Windows Settings labels. Check Monitor List after display
changes. The primary display has origin `(0,0)`. Negative coordinates, vertical
arrangements, gaps and mixed resolutions are supported.

Examples:

- “Look at my main monitor.” → primary.
- “Rocky, what is on my second monitor?” → monitor 2.
- “What is on my left screen?” → the model uses monitor positions.
- “Look across all my monitors.” → all.
- “What am I doing?” → primary by default.
- “Can you see the YouTube video I pulled up?” → desktop.
- “Can you see it now?” after a screen question → fresh desktop capture.
- “What am I holding?” / “Look at me.” / clothing questions → webcam.

Desktop questions never attach webcam frames, even if a webcam is available.
Short visual follow-ups retain the previous source; ordinary conversation does
not authorize screenshots. Explicit webcam questions switch back to the camera.
The model uses `look_at_screen` with `monitor: "primary"`, `"all"`, or a positive
integer. `list_screen_monitors` supplies geometry without capturing. The desktop
tools are withheld when the actual connection is unavailable, and the model gets
an explicit current status for screen questions. No failed request reuses an image.

All-monitor capture covers the virtual desktop bounding rectangle. Images fit
within 3840×2160 while preserving aspect ratio. Request one monitor for better
text detail. Region and active-window capture are now supported; coordinates and
tiers are described in the extension guide. The capture backend stays in the helper; Rocky has only its
client/process lifecycle. Optional image decoding is used by the explicit test.

## Privacy

Screen Vision is view-only. Rocky cannot click, type or control applications.
The helper binds only to `127.0.0.1`, requires session authentication, rejects
browser Origin requests, and enables no CORS. Dynamic ports avoid collisions.
Local software that can inspect another process's memory/environment may obtain
its token; this is not a security boundary against other privileged local apps.

Screenshots are on demand by default, held in memory, and never written to disk.
Explicit Watch adds a local capture timer and a bounded 12-second RAM buffer,
without automatic model uploads or a permanent screenshot archive. Desktop images are
removed from local model history when a turn ends, fails or is interrupted, and
when access is paused/disabled. Old image payloads are removed before a new
screen tool capture. Answer text and capture metadata may remain in history.
Python does not guarantee secure erasure of freed memory.

When Rocky answers a screen question, its image goes to the configured
vision-capable provider, including cloud providers or ChatGPT when selected.
Provider retention rules apply. Screens may contain sensitive information;
Pause or Disable before exposing content you do not want sent. Closing access
cannot recall an image already submitted to a provider. Diagnostic tests do not
upload images.

The standalone `launch-screen-vision.cmd` is now a Windows integration diagnostic
launcher. Normal use always starts from Rocky's Enable menu, not manual pairing.
Python mode is the validated target. The PyInstaller entry supports child-helper
mode, but rebuilding and testing a packaged executable is a separate check; the
optional capture dependencies must be installed before packaging.

## Diagnostics and tests

Metadata-only console logs identify helper startup, authentication, public
session ID, request ID, monitor, capture start/success, dimensions, duration,
byte size, failures, pauses, disconnects and reconnects. Raw tokens and image
content are never logged.

`ScreenVisionManager.diagnostics()` is the internal equivalent of
`screenvision status`; `ScreenVisionManager.test()` implements `screenvision test`.
The same operations are available in Rocky's menu. The runtime's command queue
accepts `screenvision status`, `screenvision test`, and `screenvision reconnect`.
These commands can also be entered in Rocky's Type a question dialog.
Screen controls run separately from conversation handling so Disable can be
processed while an answer is in progress.

From `server`:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m desktop_vision.test_capture
```

The automated suite uses synthetic geometry, fake images/processes/models, and
actual authenticated loopback HTTP requests. It covers 20 sequential captures,
automatic environment-token handoff, shutdown fallback, crash detection,
bounded reconnect, pause/resume, invalid monitors, source routing, in-flight
image revocation, cleanup, and normal Rocky operation without desktop vision.

The Windows integration command opens one visible managed helper, enumerates
and captures each display and all monitors, verifies JPEGs in memory, repeats
primary capture 20 times, checks pause/resume and same-session reconnect, then
shuts down the helper and confirms disabled capture is denied. It exits nonzero
on failure. It saves no screenshots and calls no model.

See [diagnosis and validation results](screen-vision-validation.md) for the
reproduced routing failure, the 70-test result and real Windows capture checks.
