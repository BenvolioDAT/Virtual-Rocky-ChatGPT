# desk-robot

A small desk robot with a face, a voice, and a camera. Say "hey Rocky" and it
turns its head, looks at you, and answers out loud in character. The body is
a $24 microcontroller with an OLED screen on a pan-tilt neck. The brain is a
Python program on your computer that does speech-to-text, asks a language model,
and speaks the reply through the robot's speaker.

<!-- photo or short clip goes here: docs/rocky.jpg -->

## Versions

**V1 is the robot in the videos.** It is frozen as the
[v1.0 release](https://github.com/cgro00/desk-robot/releases/tag/v1.0), a
permanent snapshot of the code, wiring, and parts list as built. `main` is
always the latest version and may be ahead of what an older video shows.
[CHANGELOG.md](CHANGELOG.md) lists what changed between versions.

Out of the box it is **Rocky**, the Eridian engineer from *Project Hail
Mary*: short sentences, "question" and "answer", "amaze", and constant
worry about whether you have slept. Everything about him is yours to change.
See [Make it your own](#make-it-your-own).

**What it can do**

- Wake on its name, listen, and answer with a spoken reply in a cloned voice.
- Show seven expressions on its face, blink, and doze off when ignored.
- Turn and nod its head, follow your face, and look where you ask.
- See through its camera and tell you what is there, honestly.
- Decide when you have finished talking, the way a person does, instead of
  waiting for a fixed pause.

**How it is put together**

```
┌──────────────── the robot (XIAO ESP32S3 Sense) ───────────────┐
│  OLED face · pan/tilt servos · camera · mic · amp + speaker   │
└───────────────────────────┬───────────────────────────────────┘
                            │ WiFi (WebSocket)
┌───────────────────────────┴───────────────────────────────────┐
│  brain server (Python, on your computer)                      │
│  wake word → speech-to-text → language model → text-to-speech │
│  plus face tracking, emotions, and head movements             │
└───────────────────────────────────────────────────────────────┘
```

The firmware is deliberately simple: it draws the face, moves the servos,
and streams audio and camera frames. All the judgement lives in `server/`.
Nothing is billed while the robot is idle.

## Contents

1. [What you need](#what-you-need)
2. [Build the body](#build-the-body)
3. [Flash the firmware and test over USB](#flash-the-firmware-and-test-over-usb)
4. [Set up the brain on your computer](#set-up-the-brain-on-your-computer)
5. [Connect the robot to the brain](#connect-the-robot-to-the-brain)
6. [Living with Rocky](#living-with-rocky)
7. [Make it your own](#make-it-your-own)
8. [Troubleshooting](#troubleshooting)
9. [How it works](#how-it-works)
10. [Privacy and security](#privacy-and-security)
11. [Credits and license](#credits-and-license)

## What you need

**Parts.** Roughly $100 in total, plus a soldering iron if you do not have
one. Everything is a common Amazon or Adafruit item.

| Part | Notes |
| --- | --- |
| Seeed XIAO ESP32S3 **Sense** | The Sense version has the camera and microphone built in. Get it with headers pre-soldered if you can. The little U.FL antenna in the box is required for WiFi. |
| 1.3" SH1106 I2C OLED, 128x64 | The face. The 0.96" SSD1306 also works with a one-line firmware change. |
| Adafruit Mini Pan-Tilt kit, assembled | The neck. It ships with two SG90 servos, which work. MG90S metal-gear servos are a drop-in upgrade for smoother motion. |
| MAX98357A I2S amplifier board | Turns digital audio into speaker power. The $3 clones work. |
| Small 4 Ω 3 W speaker | Enclosed ones with a JST lead are easiest to mount. |
| 470 to 1000 µF electrolytic capacitor | Keeps the servos from browning out the board. Not optional. |
| Breadboard, jumper wires, M2/M2.5 nylon standoffs | For wiring and mounting the screen. |
| 5 V, 2 A or better USB-C power supply | A laptop port is fine for flashing, not for running servos and speaker. |

**On the computer side.**

- A Mac, Windows PC, or Linux machine on the same WiFi as the robot. It was
  built and tested on an Apple Silicon Mac. Windows and Linux use the same
  code except for the built-in fallback voice and speaker playback, which
  have their own paths that nobody has run yet. If you're the first, say how
  it went. On Linux, install `espeak-ng` for the fallback voice.
- Python 3.13, which is what this was built and tested with.
- PlatformIO for flashing the firmware (installed below).
- A language-model API key. Any one of these works:
  - **OpenRouter** (the default): one key, any model, easy to switch.
  - **Anthropic**: use a Claude model directly.
  - **OpenAI**: use a GPT model directly.
- Optionally a **Fish Audio** key for the cloned voice. Without it Rocky
  speaks with your computer's built-in voice, which is fine for getting
  started.

**Skills.** Basic soldering (about 27 joints, all through-hole), and the
patience to read the wiring guide before powering anything on.

## Build the body

Follow [`docs/wiring.md`](docs/wiring.md) with the parts in hand. The short
version:

1. Everything shares a ground rail.
2. Servos and the amplifier run from the XIAO's **5 V** pin, never 3.3 V.
3. The big capacitor goes across 5 V and ground, striped leg to ground.
4. The OLED is on I2C (D4/D5), the servos on D3 (pan) and D6 (tilt), the
   amplifier on D0, D1, D2.
5. The camera and microphone are on the Sense board already. No wiring.

Only the OLED and the XIAO ride on the pan-tilt head. The amplifier,
speaker, breadboard, and capacitor stay on the desk. There is no printed
shell yet, so mount the screen on a small plate on the tilt platform with
standoffs or foam tape, with the camera peeking over the top edge.

## Flash the firmware and test over USB

Do this before WiFi. It proves the face and the neck work.

1. Install PlatformIO, either as the VS Code extension or from the terminal:

   ```bash
   brew install platformio
   ```

2. Plug the XIAO in over USB-C, then build and flash:

   ```bash
   cd firmware
   pio run -t upload
   pio device monitor        # serial console at 115200
   ```

3. The eyes should open, blink, and look around on their own. In the serial
   console, try:

   ```
   help                 list commands
   emo happy            change the face: neutral/happy/sad/angry/surprised/sleepy/thinking
   pan -30              turn the head, -60..60, 0 = center
   tilt -20             nod the head, -60 (down)..0 (level)
   blink                blink once
   demo off             stop the idle behaviour
   raw tilt 20          calibration move that ignores the limits (watch it!)
   ```

4. Check the head's manners. If `tilt -20` looks up instead of down, flip
   `TILT_INVERT` in `firmware/include/config.h`. If the head is not straight
   or level at 0, adjust `PAN_TRIM_DEG` and `TILT_TRIM_DEG` a few degrees at
   a time. If the tilt bracket strains at the end of its travel, pull the
   `TILT_MIN_DEG` and `TILT_MAX_DEG` limits in. Re-flash after each change.

Without a `secrets.h` file the firmware stays in this USB-only mode, which
is useful whenever you want to test the body alone.

## Set up the brain on your computer

The brain works without the robot: it uses your computer's microphone and
speaker until the robot connects. Get it talking first.

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Open `server/.env` and fill in:

- `LLM_API_KEY`: your OpenRouter key. (For Anthropic or OpenAI instead, see
  [Change the model or provider](#change-the-model-or-provider).)
- `HUMAN_NAME`: what Rocky should call you.
- `ROBOT_TOKEN`: any random string. The robot will need the same one. Make
  one with `python3 -c "import secrets; print(secrets.token_hex(16))"`.
- `FISH_AUDIO_API_KEY`: optional, for the cloned voice.

Then start it, from the `server` folder with the venv active:

```bash
python -m brain.main
```

The first run downloads about 160 MB of speech models into `~/.cache`
(Whisper from Hugging Face, the two turn-detection models from GitHub and
Hugging Face, all pinned to a fixed version). macOS will ask once to let
your terminal use the microphone; on Windows, check that microphone access
for desktop apps is on in Privacy settings. Say **"hey Rocky, what is a
weekend?"** and he should answer through your computer's speaker. You can
also type `ask what is a weekend?` into the server console.

The live view at <http://localhost:8766/> is Rocky's console: what he sees,
what he hears, the last exchange, and controls for his head, face, voice,
sleep, and listening. It only answers this computer.

## Connect the robot to the brain

1. Find your computer's address on your WiFi:

   ```bash
   ipconfig getifaddr en0     # macOS
   ipconfig                   # Windows: the IPv4 address of your WiFi adapter
   hostname -I                # Linux
   ```

   Your router can usually pin the computer to a fixed address so this does
   not change.

2. Copy `firmware/include/secrets.h.example` to `secrets.h` in the same
   folder and fill in your WiFi name and password, that address, and
   the same `ROBOT_TOKEN` you put in `server/.env`. The ESP32 only sees
   **2.4 GHz** networks.

3. Flash again with `pio run -t upload`. The serial console shows
   `wifi: connected` and then `brain: connected` once the server is running.

From then on the server listens through the robot's microphone and speaks
through the robot's speaker whenever the robot is connected, and falls back
to your computer when it is not. The robot can now live on a wall supply
away from the computer.

## Living with Rocky

| Say | What happens |
| --- | --- |
| "hey Rocky" | He wakes, looks up, and waits for your question. His name alone, without "hey", does not wake him. |
| anything, while he is awake | He answers. No need to repeat his name for about a minute. |
| "Rocky, look left" / "look at the door" | He turns his head, takes a fresh picture, and tells you what he sees. |
| "what do you see?" | He describes the current camera frame, and only what is actually in it. |
| "track me" / "stop tracking" | His head follows your face, or stops. |
| "Rocky, sleep" / "goodnight" | He says goodnight and stops listening until you say his name. |

He decides you are finished the way a person does. A small model listens to
how your sentence ends; if you sound done he answers about a third of a
second later, and if you trail off he waits. His first sentence is spoken
while the rest is still being written. If you start talking again before he
speaks, he drops the reply and answers the whole thing once. Once he is
speaking he finishes the line, because his microphone is muted while his
own voice plays.

Server console commands, for when talking is inconvenient:

```
ask <question>       talk to Rocky from the keyboard
say <text>           speak exactly this
volume 0.5           speaker volume, 0 to 1
listen               toggle the microphone
mic                  three-second level meter
track on|off         face tracking
emo surprised        push a face
pan 20 / tilt -20    move the head
status               what is connected
```

Every reply prints a `timing` line so you can see where the seconds go.

## Make it your own

Everything below is a one-file edit. None of it needs the robot plugged in,
so you can tune the character with `ask` in the server console before the
body is even built.

### Rename the robot

`ROBOT_NAME` in `server/brain/config.py`. The wake word becomes "hey
<name>" and the sleep phrases and speech-to-text hint follow automatically.
Update `WAKE_PHRASES` in the same file with the ways speech-to-text tends
to mishear the new name (say it a few times and watch the console). The
character file still introduces itself as Rocky, so edit
`server/brain/personality.py` too, or you have a robot called Bolt who
insists he is Rocky.

### Change the character

`server/brain/personality.py` is the whole personality: one system prompt
that pins down who he is and how he talks, plus a few canned lines for
waking, sleeping, and tracking. To make a different character, rewrite the
prompt. The parts worth keeping are the rules about being honest with the
camera, the emotion tag at the start of every reply, and the sentence
limit, because the face, the voice, and the cost all depend on them. Add
real exchanges that came out well to the examples at the bottom; they do
more than the rules do.

`REPLY_MAX_SENTENCES` in `config.py` caps how much he says per turn. The
server cuts anything past it before it is spoken.

### Change the voice

Rocky's voice is a community-uploaded fan clone on
[Fish Audio](https://fish.audio), not something this project owns. It may
disappear one day, and it is for personal use. Open any voice's page there,
copy the 32-character ID from the URL into `TTS_VOICE_ID` in `config.py`,
and put your Fish key in `server/.env`.
`TTS_TEMPERATURE` and `TTS_TOP_P` trade steadiness for expressiveness.
Without a Fish key he uses the computer's built-in voice: on macOS,
`TTS_FALLBACK_VOICE` picks one (`say -v ?` lists them); Windows uses its
default voice; Linux uses `espeak-ng` if installed.

The robot's speaker is tiny, so a deep voice turns into rattle. Three knobs
in `config.py` shape the audio before it reaches the speaker: `TTS_LEVEL`
(loudness he is held to), `TTS_HIGHPASS_HZ` (bass cut, try 250 to 350 for a
deep voice), and `TTS_PRESENCE_DB` (lift for a muffled voice). The console
page has sliders for all three so you can dial them in while he talks, then
copy the winners into config. If a voice keeps misbehaving, `DEBUG_SAVE_TTS`
in `config.py` keeps the last 30 spoken clips and their text in
`server/debug/tts/` (git-ignored) so you can listen back.

### Change the model or provider

The brain speaks the OpenAI-style chat API, which OpenRouter, Anthropic, and
OpenAI all serve. Pick one in `config.py`:

| Provider | `LLM_BASE_URL` | `MODEL` example | Key in `.env` |
| --- | --- | --- | --- |
| OpenRouter (default) | `https://openrouter.ai/api/v1` | `anthropic/claude-haiku-4.5` | OpenRouter key |
| Anthropic | `https://api.anthropic.com/v1/` | `claude-haiku-4-5` | Anthropic key |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` | OpenAI key |

Whichever you choose, the key goes in `LLM_API_KEY` in `server/.env`. The
model must accept images (Rocky sends camera frames) and tool calls (he
moves his head with them). A small, fast model is the right choice here:
replies are three sentences, and character matters more than reasoning.
Haiku has been the best at staying in character; a few dollars a month
covers a lot of chatting. The project was built and tested through
OpenRouter. Anthropic documents streaming, tool calls, and image input on
its OpenAI-compatible endpoint, which is everything this project uses, but
describes it as a compatibility layer rather than the main road.

### Change how he listens

Also in `config.py`: `VAD_THRESHOLD` (how loud counts as speech),
`TURN_THRESHOLD` and `TURN_MAX_SILENCE` (how sure he needs to be that you
are done, and how long he will wait), `AWAKE_SECONDS` (how long he stays
awake after you speak), `STT_MODEL` (`base.en` is fast; `small.en` hears
better and takes about a second longer), and `MIC_DEVICE` in `.env` if the
computer should use a specific microphone. The console page has sliders for the
listening knobs; changes apply immediately and last until restart.

### Change the body

`firmware/include/config.h` has the pin map, the head's range and speed
limits, servo trims, speaker volume, microphone gain, and camera flips. The
OLED driver line is near the top of `firmware/src/main.cpp` if you use a
different panel. The expressions themselves are drawn in `face.cpp`.

## Troubleshooting

- **The OLED stays black.** SDA and SCL are swapped, or a jumper is loose.
- **The board reboots when the head moves.** The servos are on 3.3 V, or the
  capacitor is missing, or you are on a laptop USB port. Use a 5 V 2 A supply.
- **`wifi: joining` forever.** The network is 5 GHz only, or the antenna is
  not clipped on. Make a 2.4 GHz network or band.
- **The robot prints `brain: connected` then `brain: disconnected, will
  retry` every few seconds.** `ROBOT_TOKEN` differs between `server/.env`
  and `secrets.h`. The server console shows the refusal. If it never gets
  to `brain: connected`, the computer's address changed or the server is
  not running.
- **He never hears you on the computer.** On macOS, check System Settings,
  Privacy & Security, Microphone for your terminal; on Windows, the
  microphone privacy setting for desktop apps. Run `mic` in the server console
  for a level meter. If you have several inputs, set `MIC_DEVICE` in `.env`.
- **"Brain has no key."** `LLM_API_KEY` is empty, or belongs to a different
  provider than `LLM_BASE_URL`.
- **He answers in the computer's voice.** `FISH_AUDIO_API_KEY` is missing
  or the voice ID is wrong. Fine for testing; set it when you want the real
  voice.
- **"cannot speak: no built-in voice on this system."** Linux without
  `espeak-ng`. Install it, or set a Fish key.
- **The voice rattles or sounds muffled.** Use the speaker-tuning sliders on
  the console page, then copy the values into `config.py`.
- **He cuts you off, or waits too long.** Raise `TURN_THRESHOLD` if he jumps
  in early, lower it if he waits. `TURN_MAX_SILENCE` is his patience limit.
- **First start is slow.** It is downloading the speech models. Only once.

## How it works

- **Firmware** (`firmware/src/`): `face.cpp` draws the eyes and mouth at 30
  fps, `servo_neck.cpp` eases the head with speed limits, `camera.cpp`
  keeps the latest JPEG in memory, `mic.cpp` streams 16 kHz audio, and
  `speaker.cpp` plays whatever the brain sends. `link.cpp` is the WebSocket
  client. The USB serial console and the brain drive the same commands.
- **Brain** (`server/brain/`): `ears.py` turns audio into text with
  faster-whisper, using Silero VAD to find speech and Smart Turn
  (`turn.py`) to decide when you have finished. `thinking.py` talks to the
  model, streams the reply sentence by sentence, and gives the model two
  tools: `look` (move the head, take a picture) and `track_face`.
  `mouth.py` turns text into audio with Fish Audio and levels it for the
  small speaker. `tracker.py` follows faces with OpenCV. `eyes.py` serves
  the console page. `main.py` ties it together.
- **Protocol** between the two is in [`docs/protocol.md`](docs/protocol.md):
  JSON commands one way, audio and JPEG frames the other.

Tests run with no hardware and no downloads:

```bash
cd server && python -m unittest tests/test_personality.py tests/test_segmenter.py
```

## Privacy and security

- **Secrets stay in two git-ignored files**: `server/.env` and
  `firmware/include/secrets.h`. Never commit them, and do not share
  `firmware/.pio/` build output either: the compiled binary contains your
  WiFi password.
- **Only your robot can talk to the brain.** The WebSocket port is open on
  your LAN, but the first message must carry `ROBOT_TOKEN`. One robot at a
  time.
- **The camera console is this computer only** and rejects requests from other
  hosts. Opening it to the LAN would let anyone on your WiFi watch the
  camera and read transcripts.
- **Voice is unauthenticated by design.** Anyone in earshot can say "hey
  Rocky". All he can do is move his head and spend a fraction of a cent.
- **What leaves your computer:** each question sends the transcript, the recent
  conversation, your name from `HUMAN_NAME`, and the newest camera frame
  (only for visual questions) to your model provider, and each reply's text
  to Fish Audio if configured. Speech-to-text and face tracking run
  locally. The first run downloads speech models from Hugging Face and
  GitHub, pinned to fixed versions. The console page loads nothing from the
  internet.
- **What is stored:** the in-memory conversation, and nothing else unless
  you turn on `DEBUG_SAVE_TTS` or `DEBUG_SAVE_UTTERANCE` in `config.py`,
  which keep recent spoken replies or the last thing heard in
  `server/debug/` (git-ignored).
- **Known limitation:** robot-to-computer traffic is a plain WebSocket on
  your home network. Someone already on your WiFi who spoofs the computer's address
  could command the robot and receive its streams. Mutual authentication or
  TLS is the fix if that matters to you.

## Credits and license

- Face detection is [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
  (`server/models/`), Apache 2.0, by Shiqi Yu and the OpenCV Zoo
  contributors.
- Speech detection is [Silero VAD](https://github.com/snakers4/silero-vad)
  (MIT) and end-of-turn detection is
  [Smart Turn](https://github.com/pipecat-ai/smart-turn) (BSD-2-Clause).
  Both download on first run. `server/brain/whisper_features.py` is
  vendored from Smart Turn (Daily, BSD-2-Clause), itself derived from
  HuggingFace transformers (Apache 2.0).
- Rocky and his voice are fan work. *Project Hail Mary* belongs to Andy Weir.

MIT licensed. See [`LICENSE`](LICENSE). Build one, change everything, tell
me what it turned into.

## Virtual Rocky — Windows desktop companion

This working copy adds a hardware-free mode to [cgro00/desk-robot](https://github.com/cgro00/desk-robot), based on commit `34614769c1211fc6943c18bc37ca7ddf850a7cc6`. The original MIT license and firmware remain included. Virtual mode reuses the brain, personality, wake phrases, faster-whisper, Silero, Smart Turn, streaming LLM replies and Fish/built-in speech synthesis.

### Windows setup (PowerShell)

Install **64-bit Python 3.13** from python.org. Open PowerShell in this project's folder:

```powershell
cd server
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-virtual.txt
```

**ChatGPT Plus/Pro: no API key or `.env` is required.** Launch Rocky, click **Continue with ChatGPT**, sign in to your account in the browser, and approve using your ChatGPT plan. Return to Rocky; he displays **Using ChatGPT plan**. Your Plus plan's usage allowance applies, and is shared with other apps using that plan. Manage usage and access from the face's right-click menu. Sign-in does not give Rocky access to your existing ChatGPT conversations.

The app handles microphone input and Windows speech output locally. Optional webcam images go to the selected ChatGPT model when a question needs vision. ChatGPT plan sign-in supplies the conversational brain, not the ChatGPT app's Voice Mode. No Fish key is required for Windows speech.

The right-click menu includes **ChatGPT accounts**, **ChatGPT model**, **Manage ChatGPT usage**, and **Sign out of ChatGPT**. Available models come from the signed-in account; the first available one is selected initially. You can renew the login with **Continue with ChatGPT**. If you decline plan permission, sign in again and enable it. Quota/connection errors give an actionable message; Rocky does not silently switch to separately billed API usage.

For the original API-key provider instead, create an optional `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` for an OpenAI-compatible provider. Run `python -m brain.virtual --provider api` (using the environment's Python), or `launch-virtual.cmd --provider api`. `VIRTUAL_LLM_AUTH=api` selects this mode when launching the Python module directly. Physical mode keeps the existing API-key configuration. Never commit `.env`.

Fish Audio is optional: leave `FISH_AUDIO_API_KEY` blank to use Windows' installed System.Speech voice. A failed voice provider falls back to that voice; if speech synthesis or speakers fail, replies remain in the console and the face stays usable. No robot token or ESP32 is needed in virtual mode.

Windows 11: **Settings > Privacy & security > Microphone**, enable microphone access and **Let desktop apps access your microphone**. Repeat under **Camera** if using a webcam. Windows 10 uses **Settings > Privacy > Microphone / Camera**. Choose the desired default input/output in **Settings > System > Sound**. List device names with:

```powershell
.\.venv\Scripts\python.exe -m sounddevice
```

Set `MIC_DEVICE` in `.env` to an input device name if the default is wrong. Prefer a microphone that accepts 16 kHz input. First launch downloads speech/turn models; allow several minutes and keep the console open. Model download failures leave the face and typed-question control available; correct connectivity and restart to retry. Install the Microsoft Visual C++ x64 Redistributable if Windows reports missing native DLLs.

### Launch

From the project root, double-click **launch-virtual.cmd**, or from `server`:

```powershell
.\.venv\Scripts\python.exe -m brain.virtual
```

A 260×180 face appears. Drag it with the left mouse button. Right-click for always-on-top, a typed question, microphone toggle, face tracking toggle, expression previews, and Quit. Say **“hey Rocky”**, wait for his acknowledgment, then ask your question; or say the wake phrase and question together. Follow-up questions work during the existing 60-second awake window. “Go to sleep” returns to wake-phrase-only behavior. The microphone is muted during playback to avoid hearing Rocky's own voice.

```powershell
.\.venv\Scripts\python.exe -m brain.virtual --no-camera
.\.venv\Scripts\python.exe -m brain.virtual --camera 1 --always-on-top
.\.venv\Scripts\python.exe -m brain.virtual --preview
.\.venv\Scripts\python.exe -m brain.virtual --no-mic --no-camera
```

`--preview` draws only the face: no microphone, webcam, speech model downloads or API calls. Camera 0 is the default; try 1 for another connected webcam. An absent or disconnected webcam does not stop conversation. Tracking starts enabled in virtual mode; “stop tracking” / “track me” also control it. Vision questions use a fresh webcam JPEG with an image-capable model. A webcam cannot physically turn, and the `look` tool reports that limitation rather than claiming the camera moved.

The UI opens **no persistent HTTP or WebSocket listener**. Browser sign-in briefly opens a callback on `127.0.0.1`, then closes it on completion/cancel/timeout. Speech recognition runs locally. Questions and relevant webcam images go to the configured LLM provider; Fish TTS sends reply text when configured. This is not fully offline unless the configured services are local. Microphone/model startup and errors are visible in the launcher console. Close the face or select Quit to stop.

### Original physical mode

Continue to run `python -m brain.main` from `server`, with the original firmware and token setup documented above. The physical WebSocket protocol, robot microphone, JPEG camera stream, head movement and PCM speaker behavior remain intact. The shared body boundary is in `brain/body.py`; Qt is imported only by desktop modules, so physical installations do not require PySide6.

### Tests and optional executable

From `server`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m brain.virtual --smoke-test
```

Tests use fake devices/providers and offscreen Qt; they do not establish real microphone, webcam or paid-provider performance. See `docs/virtual-architecture.md` and `docs/virtual-validation.md` for decisions and verified limitations.

Optional packaging, from the project root after installing virtual requirements:

```powershell
server\.venv\Scripts\python.exe -m pip install pyinstaller
.\build-virtual.cmd
```

Run `server\dist\VirtualRocky\VirtualRocky.exe`. Use **Continue with ChatGPT** for your eligible plan. For API-provider mode, copy `.env.example` to `.env` beside the executable and configure it. Keep the entire distribution folder together. Models still download on first use. This is an initial packaging recipe, not a signed installer; Python mode is the supported first milestone.

## Optional desktop Screen Vision

Install the optional dependencies, then right-click Rocky and choose **Screen
Vision → Enable Screen Vision**. Rocky opens and authenticates a separate visible
helper automatically; no token copying is needed. Use Pause/Resume, Monitor List,
Status, Test, or Disable from the same menu. Desktop access starts disabled, and
closing Rocky or disabling the feature closes its helper. Screenshots are taken
only on demand and may be sent to your configured model provider for screen
questions. See [Screen Vision setup, diagnostics and privacy](docs/screen-vision.md).

**Screen Watch** adds optional local observation every two seconds, lightweight
change detection and at most six recent images in temporary RAM. Watching alone
makes no model requests. Ask “what just happened?” to supply a few relevant old
images plus a fresh current image; static questions use current only. Stop,
Pause or Disable clears the buffer. Active-window/detail crops and resizable face
presets are also available. See [Screen Watch and face details](docs/screen-watch-and-face.md).


## Personalities

Right-click the face -> **Personality** -> select a character. Rocky remains the
initial default. Original starters are Friendly Companion (Nova), Engineer
(Gizmo), Gamer Buddy (Pixel), and Custom Example (Echo). The selected item is checked.
Switching needs no restart: the current spoken turn finishes, old conversation
and temporary visual-source context clear, the face sleeps, and name, wake words,
voice, canned lines and window title update. Say the new character's wake phrase.
Interrupted network streams may briefly delay switching while they finish closing.
Screen Watch's local buffer stays available. All characters share the existing
emotions, tool availability, Screen Vision privacy controls and visual honesty rules.

Use **Open Personality Folder** to find profiles: `server/personalities/` in source
installs, or `personalities/` beside the executable in packaged builds. Copy
`example.json`, choose a unique ID, edit it, save as UTF-8 JSON, then select
**Reload Personalities**. No Python edits are needed. JSON has no comments or trailing
commas. Reload clears conversation history so edited instructions take effect.
Invalid files are skipped and reported in the console/status. Missing or invalid
selected profiles fall back to Rocky; a built-in recovery copy survives deletion
of Rocky's file. For duplicate IDs the first valid file in filename order wins,
and the duplicate is reported.

Only the active profile ID is saved in the existing UI preferences alongside
window settings (`%LOCALAPPDATA%/VirtualRocky/ui.json`), never in `.env`.
Physical robot brains support these profiles too, without firmware changes.
Local console commands: `personality`, `personality list`, `personality gamer`,
`personality rocky`, `personality reload`, `personality folder`.

| Field | Meaning |
| --- | --- |
| `id` | Required unique lowercase ID; starts with a letter, uses letters/digits/underscore/hyphen, at most 64 characters. |
| `display_name` | Required menu label. |
| `robot_name` | Required name for title, spoken identity and transcription hint. |
| `description` | Optional description. |
| `character_prompt` | Required character/style text; cannot grant tools or override shared honesty/privacy rules. |
| `example_replies` | Optional list of spoken examples with emotion tags. |
| `wake_phrases` | Required nonempty list, including any desired transcription aliases. |
| `canned_lines` | Required nonempty `wake`, `sleep`, `track_on`, `track_off` strings. |
| `voice` | Optional `fish_voice_id`, `temperature`, `top_p`; numbers range 0-1, defaults 0.4/0.6. |
| `reply_max_sentences` | Optional integer 1-10, default 3; enforced by both providers. |

`{human_name}` in character text/examples/canned lines uses the existing private
HUMAN_NAME setting. `{reply_max_sentences}` in character text uses the profile limit.
The active name updates the speech-recognition hint for each transcription and
name-based sleep commands. Only configured aliases wake the character: Nova won't
wake to "Hey Rocky" unless that alias is explicitly in Nova's profile.

Fish Audio uses the existing `FISH_AUDIO_API_KEY` secret configuration.
**Never store API keys in profile files.** Unknown fields (including credentials)
are rejected. Empty or omitted Fish voice ID uses the existing operating-system
voice fallback. Rocky retains the project's existing voice; original starters
have no commercial character voice IDs. Add an ID you have permission to use for
custom voices. Speaker EQ and loudness remain shared controls.

Complete example (copy and change its ID, name, wake phrases and character prompt):

```json
{
  "id": "example",
  "display_name": "Custom Example",
  "robot_name": "Echo",
  "description": "A curious, calm original desktop companion. Speak clear English and help with everyday questions.",
  "character_prompt": "You are Echo. A curious, calm original desktop companion. Speak clear English and help with everyday questions.",
  "example_replies": [
    "[happy] Ready when you are."
  ],
  "wake_phrases": [
    "hey echo",
    "hi echo"
  ],
  "canned_lines": {
    "wake": "What would you like to do?",
    "sleep": "Goodnight. Call my name when you need me.",
    "track_on": "Face tracking on.",
    "track_off": "Face tracking off."
  },
  "voice": {
    "fish_voice_id": "",
    "temperature": 0.4,
    "top_p": 0.6
  },
  "reply_max_sentences": 3
}
```
