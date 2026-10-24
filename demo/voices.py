"""Speaks each line of the demo call with macOS voices and records its level envelope for the meters."""
import json, subprocess, wave
from pathlib import Path
import numpy as np

D = Path(__file__).parent
(D / "audio").mkdir(exist_ok=True)
beats = json.loads((D / "script.json").read_text())["beats"]
env = {}
for i, b in enumerate(beats):
    if b["source"] == "ask":
        continue
    voice = "Daniel" if b["source"] == "you" else "Moira"
    aiff, wav = D / f"audio/line{i}.aiff", D / f"audio/line{i}.wav"
    subprocess.run(["say", "-v", voice, "-r", "185", "-o", str(aiff), b["text"]], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav)], check=True)
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    hop = 48000 // 60
    env[i] = [round(float(20 * np.log10(np.sqrt(np.mean(x[k:k + hop] ** 2)) + 1e-9)), 1) for k in range(0, len(x), hop)]
(D / "audio/envelopes.json").write_text(json.dumps(env))
