# Virtual body decisions

Later extensions preserve this body/conversation boundary and add a resizable
face with 12 desktop emotions (mapped to the seven physical emotions), saved
window preferences, and optional local Screen Watch. See
[Screen Watch and face details](screen-watch-and-face.md) for current behavior.

- Source: cgro00/desk-robot, MIT, commit 34614769c1211fc6943c18bc37ca7ddf850a7cc6. A local branch (`virtual-desktop`) is the forked working copy; no GitHub fork or publication was made.
- `brain/body.py` defines command/PCM behavior. PhysicalBody sends the original JSON commands through the existing authenticated socket. PhysicalBody also owns existing PCM framing/acknowledgment; offline physical mode keeps its local speaker fallback. VirtualBody emits queued Qt signals and plays local PCM using sounddevice.
- Qt runs on the main thread. The existing asyncio brain runs on a daemon worker; STT/TTS and OpenCV remain workers. Signals isolate widget changes from those workers. Typed/voice turns share a lock to avoid overlapping histories or playback.
- Runtime in `brain/virtual.py` wires the same RobotBrain, ABILITIES, Ears, voice/doze loops and SpokenReply pipeline to the virtual body. No parallel replacement speech/LLM pipeline. No database; upstream in-process bounded conversation history stays.
- Webcam pushes JPEGs into existing Eyes. DesktopTracker reuses YuNet detection but sets absolute pupil coordinates, because the webcam is fixed and a servo controller would accumulate error. Tracking defaults on for desktop only. Tracking failures disable detection without stopping camera capture or speech.
- Desktop `look` reports that its camera cannot pan. It returns the current fresh image and does not invent a changed viewpoint.
- Window: 260x180, frameless, drag anywhere, 30fps simple painted monochrome eyes/mouth. Right-click exposes local controls. All seven upstream emotions, random blinking, speech-detection listening and speaking states. Mouth amplitude comes from 40ms playback blocks; OS buffering can add a small timing offset. Built-in TTS waits for a whole sentence; Fish streams synthesis, with the existing local sentence buffering retained.
- Virtual mode binds no server ports. Upstream physical mode retains its original LAN WebSocket and loopback console settings. Secrets remain in ignored .env; executable mode loads .env beside the executable.
- Camera loss is nonfatal and stale frames expire after two seconds. Replugging a disconnected webcam requires restart. Missing microphone/model downloads permit typed questions; no-key LLM calls cannot answer until configured. Replies print in the console if audio fails.
- Shutdown cancels asyncio tasks and stops mic/camera/tracker. Native/model calls already running cannot be forcibly canceled; workers are daemonized and normal device cleanup is best effort with bounded waits. First-run model download and real hardware/provider behavior need user-machine acceptance testing.
- Optional PyInstaller onedir recipe includes native libraries and YuNet. Distribution must retain MIT license notices; no signing, installer or memory database is included.

ChatGPT sign-in update: see [chatgpt-signin.md](chatgpt-signin.md). The Windows launcher now selects the ChatGPT plan option; no API key is required for eligible accounts. The temporary loopback OAuth callback is the only listener in virtual mode. Windows-protected credential files in .rocky-auth are ignored. Original physical API-provider behavior is preserved.
