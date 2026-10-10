# Local Screen Watch, efficient vision and scalable face

Screen Vision, Screen Watch and model vision are different operations:

| Operation | Meaning | Model traffic |
|---|---|---|
| Enable Screen Vision | Launch/authenticate the visible helper; allow capture. | None. |
| Watch Screen | Periodically capture and compare locally; retain useful recent images in helper RAM. | None automatically. |
| Ask a screen question | Acquire a fresh image and supply a minimal selected image set to the configured provider. | Selected images may be uploaded. |

## Using the feature

Enable Screen Vision in Rocky's right-click menu first. Then choose **Watch Screen
(local only)** or **Watch Monitor...**. Spoken or typed commands also work:

- “Rocky, watch my game.” — primary monitor with the higher game change threshold.
- “Watch monitor two.” — local observation of monitor 2.
- “Keep an eye on this.” — primary-monitor local observation.
- “What just happened?” — fresh current image plus at most three useful older images.
- “Why did my health drop?” — the same bounded temporal selection.
- “Did that enemy move?” — one earlier changed image plus current.
- “What is happening right now?” — current image only.
- “What is on monitor two?” — fresh monitor-2 image only.
- “Look closer at that warning.” — the model can request a detail crop after an overview.
- “Stop watching my screen.” / “Stop watching.” after desktop context — clear Watch RAM.

Watch commands are handled locally without an LLM request. They require Screen
Vision to be enabled and unpaused; they do not silently enable desktop access.
The face shows **Watching**, and the helper explicitly says observation is local
with no automatic cloud uploads. Pause stops Watch and clears memory. Resume
restores on-demand access; Watch must be started again. Disable, helper exit and
Rocky exit clear Watch memory and retain the existing shutdown/security behavior.

## Local pipeline and defaults

Defaults are centralized in `server/desktop_vision/settings.py`:

| Setting | Default |
|---|---|
| Capture interval | 2 seconds; API accepts 0.5–60 seconds. |
| Maximum retained frames | 6. |
| Maximum frame age | 12 seconds. |
| Comparison size | 128×72 grayscale. |
| Normal change threshold | 0.04 normalized mean absolute difference. |
| Game change threshold | 0.07. |
| History image | At most 1280×720, JPEG quality 75. |
| Current overview | At most 1600×900, JPEG quality 75. |
| Current detail | At most 3840×2160, JPEG quality 90. |
| Local OCR | Disabled. |

`ScreenWatch` runs only in the separate helper. It captures visible pixels with
MSS, downsizes the local observation, compares a grayscale signature with the
last accepted frame, and JPEG-encodes only meaningful retained frames. There is
no OpenAI/provider client in the Watch worker. MSS still acquires native pixels
before downscaling; this is not a hardware-level low-resolution capture backend.

`VisualMemory` is a locked bounded deque. Each record has a timestamp, compressed
image, selection/window metadata, dimensions, source, change score and signature.
Expired frames are removed before observation, selection and status reporting.
When all frames expire, the signature resets, allowing a new baseline even on a
static desktop. This does not accumulate six identical screenshots. Stop clears
both frames and the baseline. Generations prevent late captures from restoring
RAM after Stop. Foreground-window changes clear the prior observation context.

The comparison is deterministic and inexpensive, not semantic recognition. Small
HUD updates, similarly bright colors and very short events may be missed. The
higher game threshold reduces constant-motion storage but is not an enemy/health
event detector. Adjust thresholds for the intended game; bounded snapshots cannot
prove everything that happened between captures.

## Question-aware model input

`temporal_count()` uses simple rules, not an extra model. Static questions use
zero previous frames, comparison questions use one, and recent-event/health-drop
questions use up to three. The current image is always newly captured, even
when Watch RAM is available. Matching history must belong to the same selection
and foreground-window handle. Historical images indistinguishable from the fresh
current image are omitted. Different-monitor history is not substituted.

The maximum payload is three historical images plus current. Images are labeled
oldest to newest with seconds-ago metadata and a separate current label. A
temporal request with no matching history explicitly says earlier events cannot
be established. The prompt instructs the model to describe visible changes,
separate observation from uncertain causes, and avoid inventing unseen combat.

Both Chat Completions and Responses support this ordered image payload. Images
are removed from ordinary conversation history at turn completion, error or
interruption. The independent helper RAM buffer remains only while Watch is
active and within its limits. Each model reply permits at most three screenshot
tool attempts, inside the existing bounded model/tool loop.

## Foreground windows, region coordinates and zoom

The Windows-only metadata adapter uses GetForegroundWindow/GetWindowRect and
GetWindowText to report a window handle, title, bounds and the monitor with the
largest overlap. Metadata remains local during Watch/status polling. Relevant
metadata is supplied alongside selected images for an actual screen question.
No executable inspection, keyboard/mouse control or UI Automation is added.

The extended tool supports:

```json
{"monitor":"active","tier":"overview"}
```

```json
{"monitor":2,"tier":"detail","region":{"x":400,"y":200,"width":600,"height":300}}
```

Monitor can be primary, all, active, or a positive integer. With no monitor, the
client defaults to the Watch target or primary. Region x/y are relative to the
original selected monitor/window rectangle, not the resized overview image.
Use selected/image dimensions in metadata to convert preview coordinates.
Regions must have integer dimensions, positive width/height and remain entirely
within bounds; invalid regions are rejected rather than silently shifted.

Active-window capture crops visible desktop pixels. It does not inject into a
game, call PrintWindow, move focus or recover obscured window pixels. Missing,
minimized or wholly offscreen foreground windows fall back to primary-monitor
capture. Fullscreen/borderless bounds generally capture the visible game, but
GPU-protected content or a capture-incompatible game can still show black pixels;
this is not solved by the current MSS backend. Request its monitor when bounds
are unsuitable. Region requests currently use current detail only, not crops
of historical images.

Overview is the default. Reading small text/error warnings or requesting a
region defaults to detail unless the tool explicitly selects a tier. These are
pixel/quality limits, not a claim about a provider's exact token accounting.

## Optional OCR

OCR is behind `SCREEN_OCR_ENABLED = False`. If desired, install a local Tesseract
executable on PATH, then enable the flag in settings. No additional Python OCR
package is required. The executable is not installed or required for core vision.
When enabled, relevant text/error/read questions may request OCR on the selected
current image. It runs locally with a three-second limit and caps extracted text
at 1200 characters. Image bytes and returned text use stdin/stdout directly,
following Tesseract's [command-line interface](https://github.com/tesseract-ocr/tesseract/wiki/Command-Line-Usage/ff05e909053c9e2a57c434c2f33fbf8044f2beba);
the app creates no temporary screenshot files. It never runs on the periodic
Watch timer. Missing binaries or OCR failure leave screenshot vision working.

## Face, expressions and saved preferences

Right-click **Face Size** provides Tiny 160×100, Small 240×150, Normal 320×200,
Large 480×300 and Huge 640×400. Drag the indicated bottom-right corner for custom
aspect-preserving resizing. The existing design canvas is uniformly scaled and
centered, preventing distorted eyes; status text and the sign-in button scale too.

Twelve semantic emotions are available: neutral, happy, excited, sad, angry,
surprised, confused, curious, worried, skeptical, sleepy and thinking. Unknown
tags fall back to neutral. Visual variants, winks, double blinks and idle glances
are chosen locally. Listening, talking, thinking activity, watching_screen,
camera_looking, wake_up and dozing are local activity states; they do not add
conversation turns or model tokens. PhysicalBody maps the five new emotions to
the original firmware's supported emotions rather than changing its protocol.

Normal desktop mode saves only window coordinates, dimensions, preset and
always-on-top in `%LOCALAPPDATA%\VirtualRocky\ui.json` on close. Invalid values
are ignored, and coordinates are recovered to a visible display after monitor
removal. No screen images, memory, tokens or Watch-on state are saved. Preview
and smoke tests do not write normal user preferences.

## Status and measured behavior

The complete suite passed **86 tests** after the phased changes. Source
compilation, the face smoke test and whitespace checks passed. To repeat real
Windows capture plus local Watch checks without provider uploads, run from server:

```powershell
.venv\Scripts\python.exe -m desktop_vision.test_capture --watch-seconds 26
```

Status now includes Watch target, interval, threshold, active-window metadata,
stored-frame count/limit, oldest age, last change age, compressed/signature RAM
bytes, ignored/accepted samples, capture/compare-encode timing and process CPU
milliseconds per sample. These are sample averages, not whole-machine CPU usage.
`automatic_cloud_uploads` remains zero by construction. The main client separately
counts images supplied for model tools and the last such request time; this is
not a provider billing or confirmed network-upload counter.

Normal logs suppress per-request success noise; the `screenvision` logger's DEBUG
level enables detailed capture/request logging. No image payloads or session
tokens are logged.

Windows measurement on October 9, 2026: 26 seconds of primary game-threshold
Watch produced 13 samples, ignored 10, and held one frame at the end (118,742
compressed/signature bytes). Mean capture was 75.67 ms, comparison/retained
encoding 4.07 ms, and process CPU 60.1 ms per sample. No model images were
supplied. All three monitors, active bounds, a 300×200 detail region, pause,
Stop and shutdown passed. In that desktop sample, all-monitor overview was
1599×900 / 121,304 bytes versus detail 3838×2160 / 712,409 bytes. Content varied
between captures; these numbers are not a controlled token-cost benchmark.

Tests use synthetic changes for temporal reasoning and mocked model transports.
Real cloud-model explanations of live games, game-specific capture reliability,
live OCR accuracy and a rebuilt packaged executable remain unverified.
