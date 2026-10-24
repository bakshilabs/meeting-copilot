"""Adds the spoken lines to the rendered video at the times the tour recorded."""
import json, subprocess
from pathlib import Path
D = Path(__file__).parent
cues = json.loads((D / "out/cues.json").read_text())
for name in ["Meeting-Copilot-demo", "Meeting-Copilot-demo-4K"]:
    video = D / f"out/{name}.mp4"
    args = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(video)]
    for c in cues:
        args += ["-i", str(D / c["file"])]
    parts = [f"[{i + 1}:a]adelay={int(c['at'] * 1000)}:all=1[a{i}]" for i, c in enumerate(cues)]
    mix = "".join(f"[a{i}]" for i in range(len(cues))) + f"amix=inputs={len(cues)}:normalize=0,apad[aout]"
    args += ["-filter_complex", ";".join(parts + [mix]), "-map", "0:v", "-map", "[aout]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
             str(D / f"out/{name}-audio.mp4")]
    subprocess.run(args, check=True)
    video.unlink()
    (D / f"out/{name}-audio.mp4").rename(video)
    print("added voices to", video)
