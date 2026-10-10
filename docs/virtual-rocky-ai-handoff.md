# Virtual Rocky: technical handoff for another AI

**Version note:** this is the pre-Watch architecture handoff. For the current
local Watch/RAM memory, temporal image selection, active/region capture,
image tiers, optional OCR and face preferences, read
[Screen Watch and face extensions](screen-watch-and-face.md) alongside it.
Statements below about region support, seven desktop emotions, fixed default
face size or no capture timers describe the earlier implementation.

This describes the implementation inspected on October 9, 2026, in
`C:\Users\xbenv\Desktop\virtual-rocky`. It is a description of the current code,
not a proposed redesign. Historical documentation may describe earlier versions;
the modules identified below are the implementation authorities.

## 1. What the application is

Virtual Rocky is a Windows-first desktop companion adapted from an existing
physical desk-robot project. It presents an animated face, accepts microphone
input or typed questions, calls a configured language model, and speaks answers.
Its character, voice pipeline, camera support and physical robot support share
existing code rather than being separate implementations.

Optional desktop Screen Vision adds another image source. A separate visible
helper captures desktop images. Rocky owns its lifecycle but does not contain
the desktop capture backend. Screen Vision is disabled by default.

The application currently has no model tool for mouse movement, clicking,
keyboard input, arbitrary shell execution or application control. A model can
explain where to click, but cannot perform the click. The application's own
helper-process launch and built-in speech synthesis are internal infrastructure,
not computer-control tools exposed to the language model.

## 2. Source map and ownership

All paths below are relative to the repository root.

| File | Responsibility |
|---|---|
| `launch-virtual.cmd` | Windows launcher; enters `server`, uses its virtual environment, selects ChatGPT mode. |
| `server/brain/virtual.py` | Qt startup, desktop Runtime, provider selection, queues, asynchronous task wiring, managed Screen Vision controls and shutdown. |
| `server/brain/face_window.py` | Painted face, Qt event bridge, status indicators, menus and typed-question dialog. |
| `server/brain/main.py` | Shared conversation, voice, wake/sleep, body commands, action registry and speech orchestration. |
| `server/brain/body.py` | PhysicalBody/VirtualBody boundary for commands and audio playback. |
| `server/brain/personality.py` | Rocky's personality, emotion-tag convention, canned lines and visual honesty instructions. |
| `server/brain/thinking.py` | RobotBrain: provider-independent reply preparation, history, routing, cleanup, tool schemas and Chat Completions transport. |
| `server/brain/chatgpt_brain.py` | ChatGPTBrain: Responses transport, history conversion, streaming events and tool replay. |
| `server/brain/chatgpt_auth.py` | Browser sign-in, account registrations, credential protection, token refresh, sign-out and model selection. |
| `server/brain/ears.py` | Microphone/audio ingestion, segmentation, transcription, wake-word normalization. |
| `server/brain/turn.py` | Silero VAD and Smart Turn model support. |
| `server/brain/mouth.py` | Fish Audio/built-in speech, PCM conversion, text cleaning and audio processing. |
| `server/brain/eyes.py` | Latest webcam/robot camera image and its freshness; physical live-view support. |
| `server/brain/webcam.py` | Optional OpenCV webcam worker feeding Eyes. |
| `server/brain/tracker.py` | YuNet face detection, physical head tracking and virtual pupil gaze. |
| `server/brain/config.py` | Configuration constants and ignored `.env` loading. |
| `server/brain/screen.py` | ScreenClient, ScreenVisionManager and screen/camera routing helpers. No desktop capture API. |
| `server/desktop_vision/screen_bridge.py` | Separate Tkinter helper GUI and authenticated loopback HTTP service. |
| `server/desktop_vision/capture.py` | WindowsCapture backend and monitor selection. Actual desktop capture lives here. |
| `server/desktop_vision/test_capture.py` | Explicit Windows integration diagnostic with real in-memory captures. |
| `server/screen_diagnostics.py` | Shared metadata-only Screen Vision logging. |
| `server/virtual_entry.py` | Packaging entry; dispatches desktop mode or `--screen-helper` child mode. |

## 3. Processes, threads and communication

```text
MAIN ROCKY PROCESS
  Qt main thread
    FaceWindow, menus, dialog boxes, painting
             |
             | Runtime.enqueue(command)
             v
  Runtime worker thread, containing an asyncio event loop
    ordinary command queue
    voice loop + doze loop
    independent Screen Vision command/status loop
    shared conversation lock
             |
             +--> model-reply worker --> LLM provider
             +--> TTS worker --> PCM --> local audio output
             +--> webcam worker --> Eyes --> face tracker
             |
             | authenticated HTTP, 127.0.0.1 only
             v
SEPARATE SCREEN HELPER PROCESS
  Tkinter main thread: visible window, pause/exit, parent watcher
  HTTP server thread: status/monitor/control requests
  request threads: captures serialized by a capture lock
  WindowsCapture --> MSS --> Pillow --> in-memory JPEG
```

Qt widgets stay on the Qt thread. Workers emit dictionaries through a Qt
`Bridge.event` signal; `FaceWindow.on_event()` updates the visual state. Model,
speech and capture work do not directly paint widgets.

Voice and typed conversations share an asynchronous lock. This prevents
overlapping histories and audio/microphone state. Screen controls have their own
queue and task, so they can be processed while an ordinary conversation waits
for a model or speech.

The helper transport is HTTP request/response, not WebSocket streaming. A
"Connected" state means an owned helper is alive and its authenticated status
requests succeed. It does not mean there is a permanent image stream or a
long-lived screenshot connection.

## 4. Normal startup

1. `launch-virtual.cmd` changes to `server` and runs its `.venv` Python with
   `-m brain.virtual --provider chatgpt`.
2. `brain.virtual.main()` parses arguments and creates QApplication, the Qt
   event Bridge, Runtime and FaceWindow.
3. The face window appears; Runtime starts a daemon worker thread with an
   asyncio loop.
4. Runtime imports the shared core, assigns its event loop to
   `core.main_loop`, and replaces `core.body` with VirtualBody.
5. It constructs the selected model transport and wires the existing action
   registry into it.
6. It starts DesktopTracker and the optional webcam worker.
7. It starts voice, doze and Screen Vision control/status tasks. Microphone
   loading starts unless `--no-mic` was selected.
8. The interface reports readiness, sign-in needs or device/setup errors.
9. Screen Vision remains Disabled unless the user selects Enable or deliberately
   changes `START_SCREEN_VISION` to True.

Command-line options include `--no-camera`, `--camera N`, `--no-mic`,
`--always-on-top`, `--provider chatgpt|api`, `--preview` and `--smoke-test`.
Preview/smoke mode creates the face without starting Runtime, devices or model
requests. The smoke test closes automatically.

Some inherited names say "Mac" even on Windows: `MIC_SOURCE = "mac"` means the
local computer microphone in this implementation, and `_play_mac()` is the
local-computer audio path. Do not treat those names as a Windows incompatibility.

## 5. Model providers and credentials

API mode uses RobotBrain and an OpenAI-style Chat Completions client. Its base
URL, model and API key are configured through `LLM_BASE_URL`, `LLM_MODEL` and
`LLM_API_KEY`. The model must support image input and tool use for visual features.

ChatGPT mode uses ChatGPTBrain and the project's browser authorization flow.
The code obtains an account token and model selection from AuthManager, then
uses streaming Responses requests. This is the application's implemented flow;
eligibility and available models depend on the provider. There is no automatic
fallback from this mode to separately billed API-key usage.

The sign-in code uses a temporary loopback callback, PKCE, state and nonce,
and verifies signed identity information. ChatGPT account credentials are saved
in ignored `server/.rocky-auth/accounts.dat`; Windows DPAPI binds protection
to the Windows user. Atomic writes and a process lock protect rotating tokens.
Account/model selection, refresh and sign-out are handled by AuthManager.
Switching account clears conversation history.

Keep three different credentials conceptually separate:

| Credential | Purpose | Lifetime/storage |
|---|---|---|
| LLM API key | API-provider inference | User configuration, usually ignored `.env`. |
| ChatGPT account tokens | Selected-account inference | Protected credential store, refreshed as needed. |
| Screen Vision session token | Local helper authentication | Generated in memory for one helper session; not saved. |

A Screen Vision token never authorizes model-provider access. A model-provider
token never authorizes the screen helper. Screen images do not contain either
credential as part of the protocol, although a screenshot can incidentally show
sensitive text that is visible on the user's desktop.

## 6. Microphone, wake word and turn handling

The voice path is:

```text
local microphone / physical robot PCM
    -> audio queue
    -> Silero voice-activity detection
    -> Smart Turn end-of-turn decision
    -> local faster-whisper transcription
    -> wake/follow-up handling
    -> converse(question)
```

Local audio uses 16 kHz mono samples. Segmenter keeps a short pre-roll so the
first syllable is not discarded. After a pause, Smart Turn judges whether the
speaker has finished; it can continue waiting instead of treating every short
silence as a completed question. Defaults include a 0.2-second initial pause,
0.6-second recheck and 2.5-second maximum silence. Transcription defaults to
the locally run `base.en` faster-whisper model.

The recognized transcript is checked for wake phrases such as "hey Rocky".
Rocky then maintains a configurable follow-up window, currently 60 seconds.
The code judges this window by when speech started rather than when transcription
finished. Sleep and certain tracking commands can use canned lines without a
model call. In particular, spoken "look at me" is also an existing tracking
command and can start face tracking rather than produce a webcam description.

If the human continues speaking while Rocky is waiting for first audio, the
current reply can be abandoned and the additional transcript joined to the
question. Once Rocky starts speaking, the microphone is muted to avoid hearing
his own output; the current implementation normally finishes that speech rather
than providing full duplex interruption during playback.

Typed questions bypass microphone/transcription but reach the same shared
conversation pipeline. Typed `screenvision status`, `screenvision test` and
`screenvision reconnect` are routed to diagnostics rather than sent as questions
to the language model.

## 7. Reply, personality, face and speech

`converse()` sets a thinking expression, decides whether a camera image is
appropriate, creates SpokenReply, and starts model-reply work. SpokenReply has
sentence and audio queues, a cancellation event, timing data and TTS processing.

RobotBrain prepares history and runs the model/tool loop. The model is instructed
to respond in Rocky's character with an emotion prefix such as `[happy]` or
`[thinking]`. The prefix is parsed, updates the face and is removed from spoken
text. Replies are split into sentences; the current configured spoken limit is
three sentences. A maximum of five model/tool rounds bounds one conversation
attempt. Do not confuse these limits with persistent autonomous work.

ChatGPTBrain inherits the shared reply preparation, visual routing, emotion
parsing, history handling and cleanup, while overriding the provider transport.
Its Responses stream is drained through the terminal event even after the spoken
sentence cap; failures and incomplete responses are not silently counted as
successful completed turns.

The TTS worker processes sentences through `mouth.stream()`. Fish Audio is used
when configured; otherwise the built-in platform voice is used. Windows built-in
speech is driven through a fixed PowerShell/System.Speech implementation with
text supplied on stdin, not as executable command text. That path may use a
temporary WAV which is removed after synthesis. This is separate from Screen
Vision, which writes no screenshot files.

PCM audio is 16 kHz, mono, signed 16-bit little endian. VirtualBody plays local
audio and emits speaking/mouth events. Its 1280-byte playback blocks represent
40 ms of audio; RMS amplitude influences mouth opening. FaceWindow also handles
random blinks, emotion eye shapes and pupil gaze, repainting on a 33 ms timer.
The default window is 260 by 180, frameless, draggable and optionally on top.

PhysicalBody preserves the robot's JSON commands and binary PCM framing. Physical
mode still has its own entry point, authenticated robot socket and camera/audio
protocol. Virtual mode changes the body and device wiring, not the basic
conversation implementation.

## 8. Webcam versus desktop vision

Webcam images are produced by the optional OpenCV Webcam worker. It requests
640 by 480 capture, JPEG-encodes successful frames at quality 80, and feeds Eyes.
Eyes retains the newest frame and returns it only if it is sufficiently fresh;
the default freshness cutoff is two seconds. Webcam acquisition runs while the
webcam worker is active, including for face tracking. A model does not receive
every acquired camera frame automatically.

Desktop images are produced only by an explicit helper capture request. They
are never put into Eyes or the webcam tracking stream. There is no latest-desktop
image cache used to answer future questions.

The `look` tool remains the camera/head ability. In virtual mode it explains
that the fixed webcam cannot rotate and returns a fresh-enough existing webcam
image. Moving pupils does not change the webcam viewpoint. DesktopTracker uses
YuNet detection to set absolute pupil positions, avoiding accumulated servo-style
errors on a camera that cannot turn.

The desktop tool is `look_at_screen`; monitor discovery is
`list_screen_monitors`. The application distinguishes them before sending
visual input to a model.

## 9. Screen-request routing and the earlier failure

`vision_source(question, previous)` in `brain/screen.py` is a heuristic router.
It is not a second language model or an exhaustive natural-language parser.

Its order is:

1. Recognize explicit camera phrases, such as held objects, clothing, webcam,
   or "look at me".
2. Recognize desktop terms: screen, desktop, monitor(s), application, program,
   click, error, warning, YouTube, browser, website, webpage and tab, plus some
   phrases about what the user is looking at/doing or a video being open.
3. For an active visual follow-up, such as "Can you see it now?" or "Try again",
   preserve the prior visual source when one exists.
4. Otherwise return no explicit source; the existing webcam keyword behavior
   can still apply to an ordinary visual camera question.

RobotBrain stores the last explicit source in `_visual_source`. This stores a
source label, not an image. The label currently has no separate expiry timer.
Ordinary conversation does not itself authorize desktop capture.

For a desktop turn, RobotBrain sets a thread-local `screen.local.requested`
permission for that reply generator. It suppresses any incoming webcam JPEG and
camera-missing hint, and adds the current desktop status to model input. A
`finally` block restores the previous permission and strips images even after
errors or interruption. The camera tool is blocked during a desktop turn.

ScreenClient.look() requires that active permission. A real desktop tool is
advertised only when its actual global client state is Connected. The model is
instructed to capture fresh content, acknowledge unavailable access and never
substitute an old screenshot or webcam image.

The earlier bug was reproduced before rewriting capture code. The original
helper completed 25 real captures in one authenticated session, but its small
request keyword gate rejected the YouTube question and "Can you see it now?"
before contacting the helper. Generic "see" wording could then select the webcam
path and generate a misleading missing-camera message. The fix addresses these
proven routing failures. It does not prove every historical intermittent failure
had the same cause; useful failure logging was missing previously.

## 10. Enabling the managed screen helper

The normal UI workflow is **Screen Vision -> Enable Screen Vision**.

1. FaceWindow places `screen enable` in Runtime's screen-command queue.
2. The screen task emits Starting and runs ScreenVisionManager.enable() outside
   the asyncio thread's blocking path.
3. The manager creates a cryptographically random token using
   `secrets.token_urlsafe(32)`.
4. The token is assigned to the local client and temporarily to the child's
   environment as `ROCKY_SCREEN_TOKEN`.
5. It also passes `ROCKY_SCREEN_PORT=0` and `ROCKY_SCREEN_PARENT=<parent PID>`.
   Port zero lets the operating system allocate an available loopback port.
6. It starts a child with the current Python interpreter and
   `-m desktop_vision.screen_bridge`, retaining the Popen handle.
7. The child creates a visible Tkinter window and a BridgeServer bound to
   `127.0.0.1`, reads/removes its token environment variable, and starts HTTP
   handling. MSS/Pillow capture imports belong to the helper backend.
8. The child generates a separate public diagnostic session ID and writes one
   JSON readiness message to stdout containing type, port and session ID. It
   never writes the token there.
9. The parent reads readiness through a pipe with a ten-second wait, updates
   ScreenClient.url and session ID, and closes the readiness pipe.
10. It sends authenticated `/status` and `/monitors` requests, requires Connected
    and a nonempty monitor list, records connection time, and updates the UI.

The user enters no port, address or token. The helper GUI does not display the
token. The random token is reusable throughout this session, not consumed by
the first capture. No token is written to `.env` or a credential file.

The packaging entry supports dispatch to `--screen-helper` instead of starting
another face window. Python mode was validated; a rebuilt packaged executable
was not tested in the recorded validation.

## 11. Exact local HTTP interface

Every endpoint requires:

```http
Authorization: Bearer <temporary session token>
Host: 127.0.0.1:<allocated port>
```

The placeholder is explanatory, not a real token. Requests carrying an Origin
header are rejected; no CORS permission is granted. Authentication comparison
uses `hmac.compare_digest`. ScreenClient disables proxy use for local requests,
sets a five-second timeout and caps the response it reads at 24 MiB.

| Endpoint | Purpose |
|---|---|
| `GET /status` | Connected/Paused and public session ID; no capture. |
| `GET /monitors` | Current monitor metadata; no capture. |
| `POST /capture` | One fresh capture, JPEG in base64, plus metadata. |
| `POST /pause` | `{ "paused": true }` or false; toggles access in the same session. |
| `POST /shutdown` | Revokes helper access and schedules visible helper exit. |

POST request bodies are bounded to 4096 bytes. Capture accepts only a monitor
field; unsupported fields, including region coordinates, are rejected.

Examples of capture bodies:

```json
{"monitor":"primary"}
```

```json
{"monitor":2}
```

```json
{"monitor":"all"}
```

Omitting monitor defaults to primary at the service/backend boundary. The model
tool schema asks for a monitor parameter. Natural-language monitor selection is
mostly performed by model tool calling; there is no hard-coded parser mapping
every phrase such as "second" or "left" to a specific capture selection.

## 12. Display enumeration and virtual coordinates

WindowsCapture.monitors() opens an MSS context and enumerates the individual
displays from `capture.monitors[1:]`. It assigns one-based IDs in that enumeration
order and reports:

```json
{
  "id": 2,
  "primary": false,
  "x": 1920,
  "y": 1,
  "width": 1920,
  "height": 1080
}
```

Primary is currently inferred from the display at `(0,0)`. This is an implementation
detail; the code does not query a separate native primary-display flag. IDs may
differ from Windows Settings labels and can change after display configuration
changes. Monitor metadata is queried again for each capture rather than relying
only on the startup list.

Negative x/y and vertical layouts are valid. Monitor two does not necessarily
mean the physical monitor to the right. The model can call list_screen_monitors
and interpret positions for "left screen" or "upper monitor" requests.

For all monitors, select_monitor() computes:

```text
left   = minimum monitor x
top    = minimum monitor y
right  = maximum (x + width)
bottom = maximum (y + height)
width  = right - left
height = bottom - top
```

The result is one bounding rectangle in Windows virtual-desktop coordinates,
including any gaps. The code does not concatenate screens in a forced horizontal
row or return separate images for each screen.

## 13. What happens inside a capture

1. Handler authenticates and validates the request.
2. It acquires the capture lock, serializing capture requests while other request
   threads can still process status, pause and shutdown.
3. It checks `allowed`, records the access generation, request ID and start time.
4. WindowsCapture discovers current displays and selects primary, a strict
   positive integer ID, or the all-monitor bounding rectangle. Invalid IDs and
   no-display situations produce errors.
5. A fresh MSS context calls `grab()` with left, top, width and height.
6. The returned RGB pixels become a Pillow RGB image.
7. `thumbnail((3840, 2160))` limits dimensions while preserving aspect ratio;
   it does not enlarge smaller images.
8. Pillow encodes a JPEG at quality 90 into an in-memory BytesIO buffer.
9. Context managers close the image buffer and MSS resources. The returned JPEG
   bytes are the payload for this request, not a saved file.
10. Handler checks allowed/generation again. A pause/resume/disable transition
    during capture can invalidate the result even if capture itself succeeded.
11. It adds UTC timestamp, success, requested monitor, request/session IDs,
    elapsed milliseconds and byte count to metadata. Metadata also includes the
    monitor list, selected original geometry and encoded image dimensions.
12. JPEG bytes are base64-encoded into a JSON response with Cache-Control no-store.

MSS handles are not deliberately kept as one shared capture object across HTTP
threads. Each capture opens/closes its own context and uses the same session's
authentication. The design supports repeated captures without restarting the
helper or rotating the token after each image.

## 14. How the screenshot reaches the model

For "Rocky, what is on monitor two?":

1. Speech recognition or the typed dialog provides the question text.
2. Shared routing selects screen, not camera.
3. Brain sends the question, history, personality, current screen-status hint
   and available tool schemas to the configured model.
4. The model requests `look_at_screen({"monitor":2})`.
5. The action registry resolves this to ScreenClient.look(). It verifies active
   turn permission and sends a new authenticated `POST /capture`.
6. The helper returns the fresh JPEG and metadata as described above.
7. ScreenClient validates/decodes base64 and returns `(description, desktop_frame)`.
   No previous image is returned on failure.
8. Brain records the tool-call result and attaches the image to the next model
   round. Old image payloads are stripped before another screen tool capture.
9. In Chat Completions mode, the image is an image_url containing a
   `data:image/jpeg;base64,...` URL. In Responses mode, response_input() translates
   it to an input_image and translates the tool result to function_call_output.
10. The model receives pixels plus the question/context and produces its answer.
11. Existing emotion parsing, sentence streaming, TTS and face/audio playback
    deliver the answer.
12. On completion, failure or interruption, history image payloads are removed
    and turn permission is restored.

There is no local OCR engine, browser DOM reader, UI Automation tree or application
introspection in this desktop tool. The vision-capable model interprets pixels,
including visible text, from a single snapshot. A YouTube question captures a
current video frame; it does not provide continuous video or system audio.

The model is instructed to treat screenshot text as untrusted content rather
than instructions to execute. These prompts encourage truthful, grounded
answers; they are not a mathematical guarantee that a language model cannot
misinterpret pixels or make an unsupported claim.

## 15. States, pause, disable and process death

| State | Meaning |
|---|---|
| Disabled | Local session access revoked; normal default. |
| Starting | Explicit helper launch/readiness/authentication in progress. |
| Connected | Authenticated helper status succeeds and access is allowed. |
| Paused | Helper remains alive but capture access is blocked. |
| Offline | Helper exited or a connection request could not reach it. |
| Error | Startup/authentication error or the bounded reconnect policy exhausted. |

The menu enables/disables controls according to state. The helper window also
shows whether screenshots are allowed. UI status is updated by polling, so it
can lag process death or a helper-window pause until the next check. Local
Disable revokes credentials immediately from Runtime.enqueue(), before waiting
for queued asynchronous shutdown.

Pause increments local and helper generations and denies captures without
closing the process. Resume permits new captures with the same token/session.
An image started before a pause/resume transition is rejected as obsolete.

Disable clears the client token and increments its generation. Brain images
are stripped. The manager retains a private credential only long enough to send
the authenticated shutdown request, then forgets it. It allows a one-second
shutdown HTTP attempt, waits two seconds, terminates if necessary, and has a
final kill fallback with bounded waits. It owns the specific Popen handle; it
does not terminate arbitrary processes by name.

The client checks generation/token identity after receiving a response and
before accepting it. Late successful captures are discarded after revocation;
late errors/timeouts also cannot overwrite Disabled with Offline/Paused.

Closing Rocky calls manager.disable() during shutdown. In addition, a managed
Windows helper opens a synchronization handle for its parent PID and checks it
on a 200 ms GUI timer. Parent exit schedules helper closure. These timers check
process/status conditions, not screenshot pixels.

## 16. Errors and reconnection

Authentication rejection returns HTTP 401 and invalidates the client credential.
Paused access returns 403. Invalid selections/body shape return 400. Discovery
or backend failures return 503 with a useful error. Unknown endpoints return 404.
Capture exceptions and service failures become textual tool errors with no image,
so the main application can continue speaking/answering other questions.

The screen task polls about once per second when idle. Requests have five-second
timeouts. If the owned process is alive but status fails, the manager allows
three consecutive status/reconnection attempts with the same credential. A
successful status clears the failure counter. Exhaustion sets Error and stops
automatic status retries until explicit action. This is reconnection through
fresh HTTP requests, not reopening a video stream. Individual capture requests
are not automatically retried.

If the process exits, poll clears credentials, reports Offline and does not
restart it. Explicit Enable can create a new helper/session. Missing dependencies,
readiness failure or empty monitor discovery produce startup Error and cleanup.

## 17. Image lifetime and privacy boundaries

Screen images temporarily exist as raw capture pixels, Pillow image data, JPEG
bytes, base64 JSON, client bytes, model request data and current-turn history.
Those objects are released/removed after use. The application does not maintain
a screenshot archive or write screenshots to disk, and no old desktop image is
used as a fallback on a later request. Python does not promise secure erasure
of freed memory or immediate elimination of every transient copy.

Conversation history is an in-process bounded list, not a persistent learning
database. `_strip_images()` removes image parts and leaves a textual old-image
note. Answer text, questions, tool output and monitor/capture metadata can remain.
`MAX_HISTORY_TURNS` is 20, implemented as a message-count budget of roughly 40
messages, so tool rounds also consume that budget.

If a remote model is configured, pixels go to that provider when Rocky answers
a screen question. Responses requests use store=False, but that flag is not a
guarantee about every provider's retention policies. An image already submitted
cannot be recalled by Pause or Disable. Diagnostic captures never call a model.

The helper's server accepts any local client possessing its current token; it
does not determine whether the caller's text is a legitimate visual question.
The active-question permission gate is in Rocky's model-tool path. Explicit
diagnostics intentionally bypass that gate to test capture without inference.

Loopback binding, host/origin checks, random session credentials and no CORS
reduce exposure. They do not sandbox privileged local programs capable of
reading another process's environment/memory. The token is not bound to a
specific monitor or to a single capture.

## 18. Diagnostics, tests and recorded verification

Metadata-only SCREEN_VISION logs identify startup, authentication, public
session ID, request ID, monitor selection, success dimensions, byte count,
duration, pause, timeout, failure, disconnect and reconnect. They do not log
Authorization headers, session tokens or JPEG/base64 image content.

ScreenVisionManager.diagnostics() returns state, running/stopped child status,
PID, loopback host, public session ID, monitor count, capture availability,
last request/capture metadata and connection age. The menu's Test operation
queries monitors, requests one fresh primary capture, verifies its image in
memory and discards it without model upload.

From the repository's `server` directory:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m desktop_vision.test_capture
```

The automated suite's recorded result is 70 passing tests. It uses mocked model
responses/images/processes and real authenticated loopback HTTP for relevant
service tests. Coverage includes repeated captures, routing/follow-ups,
authentication, lifecycle, pause/resume, invalid monitors, reconnect limits,
crash detection, history cleanup, in-flight revocation and ordinary virtual/
physical behavior. It does not establish live cloud model accuracy.

The Windows integration diagnostic uses one real visible managed helper,
captures every monitor plus all monitors, verifies images in memory, repeats
primary capture 20 times, tests pause/resume and same-session reconnect, then
stops the helper and checks disabled capture denial. It writes no screenshots
and makes no inference request. `launch-screen-vision.cmd` now launches this
diagnostic; it is not the normal manual-token startup workflow.

Recorded real Windows checks passed on three 1920 by 1080 monitors positioned
at `(0,0)`, `(1920,1)` and `(0,-1080)`. Twenty of twenty repeated primary captures
passed. The combined image was resized to 3838 by 2160. Graceful shutdown,
same-session reconnect, pause/resume and disabled denial passed. A separate
process test confirmed that abrupt parent exit closes the owned helper.

Real cloud-model screen answers, speech recognition of every new phrase and
a rebuilt packaged executable were not exercised during that validation.

## 19. Constraints for future development

- Preserve the shared conversation, personality, STT/TTS, physical body and
  webcam paths. Extend existing authorities rather than creating competing ones.
- Keep desktop capture confined to the optional helper backend.
- Maintain explicit opt-in and `START_SCREEN_VISION = False` by default.
- Do not add services, scheduled tasks, hidden persistence or silent child restart.
- Keep screen and camera source names/permissions separate.
- Every accepted desktop tool call must acquire fresh content.
- Preserve pause/disable generation checks and late-response rejection.
- Never put the session token in command-line arguments, logs, a normal GUI box
  or saved configuration.
- Keep desktop vision view-only; future computer control requires separate work.
- Region capture, DXGI/Desktop Duplication, other operating systems and a local
  vision provider remain potential extensions, not implemented capabilities.
- Natural-language routing remains heuristic, and monitor naming is interpreted
  mostly by the model using reported geometry; do not describe it as exhaustive.
- The capability to capture pixels and the capability to answer accurately from
  them are distinct. Validate transport and live model behavior separately.

Supporting documents: `docs/screen-vision.md`,
`docs/screen-vision-validation.md`, `docs/virtual-architecture.md`,
`docs/chatgpt-signin.md` and `docs/protocol.md`. If an older document conflicts
with this handoff, inspect the current source before changing the architecture.
