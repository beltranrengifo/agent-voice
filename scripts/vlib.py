"""Shared helpers for agent-voice: config, transcript parsing, text cleaning."""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _default_home():
    """Where models and config live.

    VOICE_HOME wins. CLAUDE_VOICE_HOME is still honoured for installs that
    predate multi-agent support, as is an existing ~/.claude/voice directory —
    nobody should have to re-download 170 MB of models because the tool grew
    beyond Claude Code.
    """
    for var in ("VOICE_HOME", "CLAUDE_VOICE_HOME"):
        if os.environ.get(var):
            return Path(os.environ[var])
    legacy = Path.home() / ".claude" / "voice"
    if legacy.is_dir():
        return legacy
    return Path.home() / ".config" / "agent-voice"


HOME = _default_home()
CONFIG_PATH = HOME / "config.json"
VOICES_DIR = HOME / "voices"
RUN_DIR = HOME / "run"
PID_FILE = RUN_DIR / "current.pid"   # legacy marker, still cleared by `stop`


def pid_file(session=None):
    """One playback marker per session, so sessions cannot cut each other off."""
    safe = "".join(c for c in str(session or "default") if c.isalnum() or c in "-_")[:64]
    return RUN_DIR / f"pid-{safe or 'default'}"
PIPER = HOME / "venv" / "bin" / "python"

DEFAULTS = {
    "enabled": False,      # opt in with `voice on`; nobody wants a surprise voice
    "paused_until": 0,      # 0 = active, -1 = paused indefinitely, >0 = epoch to resume
    "voice_es": "es_ES-sharvard-medium",
    "voice_en": "en_US-lessac-high",
    "speaker_es": 0,        # multi-speaker models only; sharvard: 0 = M, 1 = F
    "speaker_en": 0,
    "speed": 1.0,           # >1 faster, <1 slower
    "volume": 1.0,
    "max_chars": 1200,      # truncate very long answers
    "sentence_silence": 0.25,
}


def load_config():
    """Read the stored config over the defaults.

    `enabled` defaults to False so a fresh install never starts talking on its
    own. But that default must not reach an install that already exists: when a
    config file is present without the key, the setting predates opt-in and
    silently disabling it would look exactly like the tool breaking — which is
    how it was found.
    """
    cfg = dict(DEFAULTS)
    try:
        stored = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return cfg
    if "enabled" not in stored:
        cfg["enabled"] = True
    cfg.update(stored)
    return cfg


def save_config(cfg):
    """Persist the config, recording who changed what.

    Speech silently turning itself off is indistinguishable from the tool
    breaking, and tracking down which process wrote the change after the fact
    proved impossible. So every write leaves an audit line behind.
    """
    before = {}
    try:
        before = json.loads(CONFIG_PATH.read_text())
    except Exception:
        pass

    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(CONFIG_PATH)

    changed = {k: (before.get(k), v) for k, v in cfg.items() if before.get(k) != v}
    if not changed:
        return
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        line = "{} {} {}\n".format(
            time.strftime("%Y-%m-%d %H:%M:%S"),
            " ".join(sys.argv) or "?",
            json.dumps(changed, ensure_ascii=False),
        )
        with open(RUN_DIR / "config-changes.log", "a") as fh:
            fh.write(line)
    except Exception:
        pass


def is_silenced(cfg):
    """Return a reason string if we should stay quiet, else None."""
    if not cfg.get("enabled", False):
        return "disabled"
    pu = cfg.get("paused_until", 0)
    if pu == -1:
        return "paused"
    if pu and time.time() < pu:
        return "paused"
    return None


# --------------------------------------------------------------------------
# Transcript
# --------------------------------------------------------------------------

def _is_real_user_turn(entry):
    """True for something the human actually typed, not a tool result."""
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def last_assistant_text(transcript_path):
    """Return the last prose the assistant emitted in the current turn.

    Walking back only one entry is not enough: a turn often ends with tool
    calls, while the sentence worth hearing came a few entries earlier. So we
    scan backwards for the newest text block, stopping at the previous real
    user message so we never re-read something already spoken.
    """
    try:
        lines = Path(transcript_path).read_text(errors="replace").splitlines()
    except Exception:
        return ""

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue

        if _is_real_user_turn(entry):
            return ""  # reached the start of this turn without finding prose

        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue

        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                return content
            continue
        if not isinstance(content, list):
            continue
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p.strip())
        if text.strip():
            return text
    return ""


# --------------------------------------------------------------------------
# Text cleaning — strip everything that is unpleasant to hear
# --------------------------------------------------------------------------

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF←-⇿⬀-⯿️]"
)


GAP = "\x00"  # marks where something unspeakable (code, path, URL) was removed

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _drop_gutted_sentences(text):
    """Remove sentences left meaningless by excisions, instead of speaking stumps.

    A sentence that lost two or more fragments, or lost one and has little left,
    reads as broken ("la comprobacion usa en vez de , mira el fichero"). Better
    silence than nonsense.
    """
    out_lines = []
    for line in text.split("\n"):
        if GAP not in line:
            out_lines.append(line)
            continue
        kept = []
        for sent in _SENT_SPLIT.split(line):
            gaps = sent.count(GAP)
            if gaps == 0:
                kept.append(sent)
                continue
            words = len(re.findall(r"[^\W\d_]{2,}", sent.replace(GAP, " ")))
            if gaps >= 2 or words < 6:
                continue  # too mutilated to be worth hearing
            kept.append(sent.replace(GAP, " "))
        out_lines.append(" ".join(s for s in kept if s.strip()))

    t = "\n".join(out_lines).replace(GAP, " ")
    # Tidy the punctuation the excisions stranded.
    t = re.sub(r"\s+([,;:.!?…])", r"\1", t)
    t = re.sub(r"([,;:])\s*(?=[,;:.])", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return "\n".join(ln.strip() for ln in t.splitlines()).strip()


def clean_for_speech(text, max_chars=1200):
    t = text

    # Fenced code blocks (``` and ~~~), including unterminated trailing ones.
    t = re.sub(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", " ", t, flags=re.S | re.M)
    t = re.sub(r"^[ \t]*(```|~~~).*\Z", " ", t, flags=re.S | re.M)

    # Indented code blocks (4+ spaces) that follow a blank line.
    t = re.sub(r"(?m)^(?: {4,}|\t)\S.*$", " ", t)

    # Markdown tables — whole block.
    t = re.sub(r"(?m)^\s*\|.*$", " ", t)

    # HTML-ish tags and system-reminder noise.
    t = re.sub(r"<[^>\n]{1,200}>", " ", t)

    # From here on, excisions leave a sentinel so we can later drop any
    # sentence that was gutted rather than speak the mangled remains.
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", GAP, t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)

    # Bare URLs.
    t = re.sub(r"\b(?:https?://|www\.)\S+", GAP, t)

    # Inline code — drop content entirely (identifiers read terribly).
    t = re.sub(r"`{1,3}[^`\n]*`{1,3}", GAP, t)

    # Absolute/relative file paths and dotted filenames.
    t = re.sub(r"(?:^|\s)~?/[\w.\-/]{2,}", GAP, t)
    t = re.sub(r"\b[\w\-]+\.(?:py|js|ts|tsx|jsx|json|md|sh|toml|yaml|yml|onnx|wav|txt|rs|go|java|css|html)\b", GAP, t)

    # Headings: keep text, drop hashes. Blockquote and list markers.
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s{0,3}>\s?", "", t)
    t = re.sub(r"(?m)^\s{0,3}[-*+]\s+", "", t)
    t = re.sub(r"(?m)^\s{0,3}\d+[.)]\s+", "", t)

    # Horizontal rules.
    t = re.sub(r"(?m)^\s{0,3}(?:[-*_]\s?){3,}$", " ", t)

    # Emphasis markers and stray markdown punctuation.
    t = re.sub(r"(\*\*|__|\*|_|~~)", "", t)

    t = _EMOJI.sub(" ", t)

    # Collapse whitespace.
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    t = "\n".join(ln.strip() for ln in t.splitlines())

    t = _drop_gutted_sentences(t)

    # Drop leftover lines that are pure punctuation/symbols.
    keep = [ln for ln in t.splitlines() if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", ln)]
    t = "\n".join(keep).strip()

    if max_chars and len(t) > max_chars:
        cut = t[:max_chars]
        m = re.search(r"(?s)^.*[.!?…](?=\s|$)", cut)
        t = (m.group(0) if m and m.end() > max_chars * 0.5 else cut).strip()

    return t


# --------------------------------------------------------------------------
# Language detection: Spanish vs English, stopword vote
# --------------------------------------------------------------------------

_ES = set("el la los las un una unos unas de del al y o pero que porque como cuando "
          "donde quien cual esto esta este eso esa ese con sin por para sobre entre "
          "hasta desde muy mas menos ya no si se le lo su sus mi tu nos es son era "
          "ser estar tiene hacer puede hay aqui alli tambien pues vale".split())
_EN = set("the a an of to and or but that because as when where which this that these "
          "those with without for on in at from until since very more less already not "
          "if it its his her their is are was were be being have has had do does can "
          "could should would will there here also then than you your we they".split())


def detect_lang(text):
    words = re.findall(r"[a-záéíóúüñ]+", text.lower())
    if not words:
        return "es"
    es = sum(1 for w in words if w in _ES)
    en = sum(1 for w in words if w in _EN)
    # Accented characters are a strong Spanish signal.
    if re.search(r"[áéíóúñ¿¡]", text.lower()):
        es += 3
    return "en" if en > es else "es"


# --------------------------------------------------------------------------
# Playback process control
# --------------------------------------------------------------------------

def _kill_marker(path):
    try:
        pid = int(path.read_text().strip())
    except Exception:
        return False
    killed = False
    for attempt in (lambda: os.killpg(pid, signal.SIGTERM),
                    lambda: os.kill(pid, signal.SIGTERM)):
        try:
            attempt()
            killed = True
            break
        except Exception:
            continue
    try:
        path.unlink()
    except Exception:
        pass
    return killed


def stop_playback(session=None, everywhere=False):
    """Kill in-flight playback. Returns True if something died.

    Given a session, only that session's audio stops. A single global marker
    meant every session cut off every other one: finishing a turn in one window
    killed the answer you were listening to in another, mid-sentence, and
    replaced it with an unrelated one. `everywhere` is the explicit "be quiet
    now" of `voice stop`.
    """
    if everywhere:
        markers = list(RUN_DIR.glob("pid-*")) if RUN_DIR.is_dir() else []
        markers.append(PID_FILE)
        return any(_kill_marker(m) for m in markers)
    return _kill_marker(pid_file(session))


def voice_path(name):
    return VOICES_DIR / f"{name}.onnx"


def installed_voices():
    if not VOICES_DIR.is_dir():
        return []
    return sorted(p.stem for p in VOICES_DIR.glob("*.onnx"))


DEDUPE_WINDOW = 8.0  # seconds


def _is_repeat(clean_text):
    """True if this exact text was already queued moments ago."""
    stamp = RUN_DIR / "last-spoken"
    digest = hashlib.sha256(clean_text.encode()).hexdigest()
    now = time.time()
    try:
        prev_digest, prev_time = stamp.read_text().split(None, 1)
        if prev_digest == digest and now - float(prev_time) < DEDUPE_WINDOW:
            return True
    except Exception:
        pass
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        stamp.write_text(f"{digest} {now}")
    except Exception:
        pass
    return False


def speak_async(text, cfg=None, max_chars=None, session=None):
    """Clean `text` and play it in a detached process. Returns a reason string
    if nothing was spoken, or None on success.

    This is the one entry point every agent adapter uses: Claude Code, Codex,
    OpenCode and anything else that can pipe its final message into `voice
    speak`. Adapters only have to extract the text; everything after that —
    silencing rules, cleaning, voice choice, playback — happens here.
    """
    cfg = cfg or load_config()
    reason = is_silenced(cfg)
    if reason:
        return reason

    clean = clean_for_speech(text, max_chars or int(cfg.get("max_chars", 1200)))
    if len(clean) < 2:
        return "nothing speakable left after cleaning"

    # A host may deliver the same answer twice — OpenCode loads the plugin once
    # per entrypoint, so both copies ask for the same text. Speaking it twice,
    # with the second cutting off the first, is worse than dropping the repeat.
    if _is_repeat(clean):
        return "duplicate request, already speaking this"

    lang = detect_lang(clean)
    voice = cfg.get("voice_en" if lang == "en" else "voice_es")
    speaker = cfg.get("speaker_en" if lang == "en" else "speaker_es", 0)
    if not voice_path(voice).exists():
        return f"voice model missing: {voice} (run: voice setup)"
    if find_player() is None:
        return "no audio player found"

    stop_playback(session)  # this session's previous answer is now stale

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(RUN_DIR), suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump({"text": clean, "cfg": cfg, "voice": voice,
                   "speaker": speaker, "session": session}, fh)

    worker = Path(__file__).resolve().parent / "voicectl.py"
    subprocess.Popen(
        [sys.executable, str(worker), "--worker", tmp],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    return None


def run_worker(text_file):
    """Detached: synthesize the queued payload and play it to completion."""
    try:
        if os.getpid() != os.getsid(0):
            os.setsid()
    except OSError:
        pass
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    marker = PID_FILE
    try:
        payload = json.loads(Path(text_file).read_text())
        marker = pid_file(payload.get("session"))
        marker.write_text(str(os.getpid()))
        # Per session: two sessions sharing one file would overwrite each
        # other's audio mid-playback.
        wav = RUN_DIR / (marker.name.replace("pid-", "out-") + ".wav")
        cmd = piper_cmd(payload["voice"], payload["cfg"], wav,
                        payload.get("speaker", 0))
        proc = subprocess.run(
            cmd, input=payload["text"].encode(),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0 or not wav.exists():
            (RUN_DIR / "last-error.log").write_bytes(proc.stderr[-4000:])
            return
        player = find_player()
        if not player:
            (RUN_DIR / "last-error.log").write_text("No audio player found.")
            return
        subprocess.run(player + [str(wav)])
    except Exception as exc:
        try:
            (RUN_DIR / "last-error.log").write_text(repr(exc))
        except Exception:
            pass
    finally:
        try:
            Path(text_file).unlink()
        except Exception:
            pass
        try:
            if marker.read_text().strip() == str(os.getpid()):
                marker.unlink()
        except Exception:
            pass


def find_player():
    """Return the command to play a WAV file, or None if nothing is installed.

    macOS ships afplay; elsewhere we fall back to whatever is around. Override
    with the `player` config key if the guess is wrong for your setup.
    """
    cfg_player = load_config().get("player")
    if cfg_player:
        return cfg_player.split() if isinstance(cfg_player, str) else list(cfg_player)
    for cand in (
        ["/usr/bin/afplay"],
        ["afplay"],
        ["paplay"],
        ["aplay", "-q"],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ):
        exe = cand[0]
        if os.path.isabs(exe):
            if os.access(exe, os.X_OK):
                return cand
        elif shutil.which(exe):
            return cand
    return None


def is_ready():
    """Has `voice setup` been run? Returns (ok, list of problems)."""
    problems = []
    if not PIPER.exists():
        problems.append(f"Piper virtualenv missing at {PIPER.parent.parent}")
    if not installed_voices():
        problems.append(f"No voice models in {VOICES_DIR}")
    if find_player() is None:
        problems.append("No audio player found (afplay/paplay/aplay/ffplay)")
    return (not problems), problems


def speaker_map(name):
    """Return {label: id} for a multi-speaker model, or {} if single-speaker."""
    try:
        meta = json.loads((VOICES_DIR / f"{name}.onnx.json").read_text())
    except Exception:
        return {}
    if int(meta.get("num_speakers", 1)) <= 1:
        return {}
    return meta.get("speaker_id_map") or {}


def piper_cmd(voice, cfg, wav, speaker=0):
    """Build the piper synthesis command line."""
    speed = float(cfg.get("speed", 1.0)) or 1.0
    cmd = [
        str(PIPER), "-m", "piper",
        "--model", str(voice_path(voice)),
        "--output-file", str(wav),
        "--length-scale", f"{1.0 / speed:.4f}",
        "--volume", str(cfg.get("volume", 1.0)),
        "--sentence-silence", str(cfg.get("sentence_silence", 0.25)),
    ]
    if speaker_map(voice):
        cmd += ["--speaker", str(int(speaker))]
    return cmd
