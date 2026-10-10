# Changelog

Each version of the robot is a git tag and a GitHub Release. `main` is the
latest work. A video matches the tagged version it was made with.

## Unreleased (V2, in progress)

- Separate personality, voice, and virtual face theme selection with independent persistence and safe reload/fallback.
- Migrate bundled Rocky Fish settings into a voice profile; ignore legacy character voice fields with a warning.
- Add explicit system TTS, voice testing, six OLED themes, folder controls, local selection commands, and Companion Setup.
- Keep shared prompts, wake behavior, animations, physical PCM playback, and console speaker tuning.
- Validation: 108 tests passed, six themes rendered offscreen, Windows system TTS generated valid PCM; live Fish/account/hardware checks remain untested.

- New 3D-printed pan/tilt neck: geared 360° pan, unrestricted tilt, flat
  head plate. Replaces the off-the-shelf SG90-style bracket.

## v1.0 - 2026-09-22

The robot in the videos: XIAO ESP32S3 Sense, OLED face, off-the-shelf
pan/tilt bracket with SG90 servos, camera, PDM mic, MAX98357A amp and
speaker; Python brain on your computer with wake word, speech-to-text,
a language model, and a cloned voice.

- Fixed: the voice was crackly on the robot's speaker since the release
  prep on 2026-09-17. Back to the original (2026-09-06) voice pipeline:
  the original loudness and gain cap, and a limiter that turns loud
  chunks down instead of clipping them. The bass-cut and presence
  sliders are still on the console, off by default.


### Personality profiles

- Editable JSON characters with shared core capability and honesty rules.
- Live menu switching/reload, dynamic wake/name settings, history clearing, persisted selection and safe Rocky recovery.
- Original Nova, Gizmo, Pixel and Echo examples with regression tests.
