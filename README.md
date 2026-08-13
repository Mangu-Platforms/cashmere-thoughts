# SkillVoice Studio

**Local-first narration production pipeline for house voice models.**

Piper TTS synthesis → deterministic chunking → resumable jobs → ffmpeg mastering → chaptered M4B / MP3 / WAV export.

Built so production staff who are not developers can ship distribution-ready audiobooks with one command.

```
skillvoice generate --skill eve-raspy --text-file ch01.txt --format m4b
```

---

## Why it exists

- House-owned actor voices (no third-party licensing friction)
- Offline, deterministic, bit-stable where codecs allow
- Resume after a crash without re-synthesizing hours of work
- Platform-aware mastering profiles (house / distribution-safe / storefront)
- Chapter markers that actually work in Apple Books & Audiobookshelf

See the full production document pack in `docs/` (or the numbered files at repo root).

---

## Requirements

| Item | Notes |
|------|-------|
| Python | 3.11.x (production) |
| ffmpeg + ffprobe | On `PATH`, with `loudnorm` + `sidechaincompress` |
| piper-tts | Exactly `1.6.0` (pinned) |
| Voice assets | House `.onnx` + adjacent `.onnx.json` on the backed-up share |

---

## Quick start

```bash
# 1. Install
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e .

# or simply:
make install

# 2. Initialize data dir (~/.skillvoice by default)
skillvoice init
skillvoice doctor          # hard-fail checks — fix anything red

# 3. Register a voice
skillvoice voice add eve /voices/eve/eve-actor-medium.onnx \
  --actor "Actor Name" \
  --approved-uses "All house titles, ads"

# 4. Create a skill (voice + attributes + defaults)
skillvoice skill create eve-raspy \
  --voice eve \
  --profile house \
  --pace 1.0 \
  --energy normal

# 5. Generate a chapter
skillvoice generate \
  --skill eve-raspy \
  --text-file ch01.txt \
  --format m4b \
  --title "Chapter One" \
  --author "Author Name"

# Resume if interrupted
skillvoice generate --skill eve-raspy --text-file ch01.txt --resume JOB_ID
```

---

## Book mode (full titles)

```bash
skillvoice book init                 # creates book.json
# edit book.json → ordered chapters + titles + skill + profile
skillvoice book generate book.json   # chaptered M4B + metadata
skillvoice book generate book.json --split   # also keep per-chapter files
```

---

## Everyday commands

| Command | Purpose |
|---------|---------|
| `skillvoice doctor` | Environment + registry hard checks |
| `skillvoice voice list` | Registered voices |
| `skillvoice skill list` | Available skills |
| `skillvoice profile list` | Mastering profiles |
| `skillvoice job list` | Past / running jobs |
| `skillvoice qc FILE --profile NAME` | Loudness / peak QC (do not ship failures) |

All errors are actionable: they name the stage, the job, and the exact fix.

---

## Look & feel

- Rich tables, panels, and color throughout
- Clear success / failure panels with remedies
- Consistent command structure (`voice`, `skill`, `book`, `job`…)
- Machine-readable `--json` on doctor when needed

---

## Development

```bash
make test          # full suite + coverage
make doctor        # environment check
make clean         # remove caches
```

Coverage target: ≥ 85 %. CI runs on every push.

---

## Repository layout

```text
skillvoice/              application package
tests/                   unit + regression tests
docs/                    production document pack (PRD, ADRs, SOP, runbook…)
.github/workflows/       CI + nightly Piper contract probe
requirements.lock        exact production pins
Makefile                 operator & developer targets
```

---

## Status

**v0.2.0** — Greenfield production baseline implementing the v1 document pack.

Pinning, maintenance, and platform output specs live in docs 08–10. Treat them as living.

Do not ship a deliverable that fails `skillvoice qc`.
