# Validation — virtual desktop milestone

Environment: Windows x64, Python 3.13, source commit 34614769c1211fc6943c18bc37ca7ddf850a7cc6.

Verified:

- Installed original pinned requirements plus PySide6 6.12.0 in server/.venv. The delivery requirements use only PySide6-Essentials 6.12.0 to avoid unused browser/PDF modules.
- 22 unittest tests pass: upstream personality/speaker/segmentation tests, physical command and PCM framing/acknowledgment, disconnected physical body, virtual commands, output amplitude and failure reset, absent camera/release, stale image rejection, wake routing, all seven expressions, frameless/topmost flags, gaze and a mocked full camera/LLM/emotion/TTS/mic-muting reply.
- Offscreen and native Windows `--smoke-test` create the face, render and exit successfully.
- Real desktop runtime starts/stops with --no-mic/--no-camera, without an ESP32 or API key; worker exits cleanly.
- Windows System.Speech synthesizes 80,320 bytes of PCM for a test line. Fixed upstream's empty output-path bug; speech text is passed on stdin, output path in a child-only environment variable, and native subprocess errors become a graceful missing-voice result.
- Pinned Silero and Smart Turn models download, pass upstream SHA256 checks and run. faster-whisper downloads its pinned base.en revision and transcribes synthetic Windows speech as “Hey Rocky, what do you see?”; wake detection is true. Smart Turn completion probability was 0.917. A streamed synthetic test reaches Silero probability 0.9999977 and yields two speech turns (the punctuation pause splits the greeting from the question), with the first transcribed “Hey Rocky.”
- Bundled YuNet loads and detects no face in an all-black frame. The fixed-camera gaze test proves repeated detections do not accumulate servo error.
- Syntax compilation, git diff whitespace checks and pip dependency consistency checks pass.

Limits:

- No real microphone recording, speaker playback listening check, webcam face tracking, paid LLM/Fish request, or physical ESP32 session was performed. The complete live conversation/vision acceptance flow still requires a configured .env and the user's devices. API credentials were not available and no secrets were added.
- Offscreen preview is docs/virtual-face-preview.png; actual rendering can vary by display scaling/font.
- PyInstaller recipe provided but executable not built or verified; no signed installer.
- Speech model download caches used for validation live in the chat's work/ directory; the normal launcher uses the upstream user cache unless configured otherwise. First normal launch may therefore download models again.

Acceptance on the user machine: configure .env; launch; say wake phrase; ask a question; confirm expression and speech; ask what the camera sees; move left/right and verify gaze; repeat with --no-camera; quit during idle and playback. Run the physical path separately with existing ESP32/token configuration when hardware is available.

## ChatGPT sign-in update

42 tests now pass, including simulated OAuth, verified JWT signatures and rejection cases, Windows DPAPI, token renewal, revocation/local sign-out, account separation, loopback browser callback, login/cancel UI, Responses vision/tools, and streamed usage failures. Actual OpenAI public discovery metadata was verified. Desktop sign-in screen startup/render/shutdown passes. Live Plus authorization/inference awaits the user's browser approval; no account tokens were used or obtained. See [chatgpt-signin.md](chatgpt-signin.md).
