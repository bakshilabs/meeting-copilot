"""Audio capture (via bin/systap), speech segmentation and local transcription (whisper-server)."""
import asyncio
import io
import re
import struct
import wave
from pathlib import Path

import aiohttp
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RATE = 16000
FRAME = 480  # 30 ms
SOURCES = {0: "you", 1: "them"}
HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "thank you for watching", "bye", "okay", "so"}


class Segmenter:
    """Energy-based voice activity detection that cuts speech into utterances."""

    def __init__(self, source: str, on_segment, on_speech):
        self.source, self.on_segment, self.on_speech = source, on_segment, on_speech
        self.buf = np.zeros(0, dtype=np.int16)
        self.floor = -60.0
        self.pre: list[np.ndarray] = []
        self.active: list[np.ndarray] = []
        self.speech_run = self.silence_run = self.voiced = 0
        self.level = -90.0

    def feed(self, x: np.ndarray):
        self.buf = np.concatenate([self.buf, x])
        while len(self.buf) >= FRAME:
            f, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            self._frame(f)

    def _frame(self, f: np.ndarray):
        rms = float(np.sqrt(np.mean((f.astype(np.float32) / 32768) ** 2)) + 1e-9)
        db = 20 * np.log10(rms)
        self.level = max(db, self.level - 1.5)
        # noise floor follows quiet passages quickly and loud ones slowly
        self.floor = db if db < self.floor else self.floor + 0.02 * (db - self.floor)
        speech = db > max(self.floor + 9, -52)
        if not self.active:
            self.pre = (self.pre + [f])[-10:]
            self.speech_run = self.speech_run + 1 if speech else 0
            if self.speech_run >= 3:
                self.active, self.pre = list(self.pre), []
                self.voiced, self.silence_run = 3, 0
                self.on_speech(self.source)
            return
        self.active.append(f)
        if speech:
            self.voiced += 1
            self.silence_run = 0
        else:
            self.silence_run += 1
        if self.silence_run >= 24 or len(self.active) >= 500:  # 0.7 s pause or 15 s max
            audio = np.concatenate(self.active)
            voiced = self.voiced
            self.active, self.speech_run = [], 0
            if voiced >= 10:
                self.on_segment(self.source, audio)


def wav_bytes(audio: np.ndarray) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())
    return bio.getvalue()


def clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if re.sub(r"[^a-z ]", "", text.lower()).strip() in HALLUCINATIONS else text


class Transcriber:
    def __init__(self, model: str, port: int = 8178):
        self.model, self.port = model, port
        self.proc = None
        self.session: aiohttp.ClientSession | None = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            "whisper-server", "-m", self.model, "--host", "127.0.0.1", "--port", str(self.port),
            "-t", "6", "-nt", "-l", "en",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self.session = aiohttp.ClientSession()
        for _ in range(120):
            try:
                async with self.session.get(f"http://127.0.0.1:{self.port}/") as r:
                    if r.status < 500:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.25)
        raise RuntimeError("whisper-server did not start")

    async def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        form = aiohttp.FormData()
        form.add_field("file", wav_bytes(audio), filename="a.wav", content_type="audio/wav")
        form.add_field("response_format", "json")
        form.add_field("temperature", "0.0")
        if prompt:
            form.add_field("prompt", prompt[-200:])
        async with self.session.post(f"http://127.0.0.1:{self.port}/inference", data=form) as r:
            data = await r.json(content_type=None)
        return clean(data.get("text", ""))

    async def stop(self):
        if self.session:
            await self.session.close()
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()


class Capture:
    """Runs bin/systap and feeds its two streams into segmenters."""

    def __init__(self, on_segment, on_speech, use_mic: bool = True):
        self.on_segment, self.on_speech, self.use_mic = on_segment, on_speech, use_mic
        self.segs = {name: Segmenter(name, on_segment, on_speech) for name in SOURCES.values()}
        self.proc = None
        self.paused = False
        self.error = ""

    def levels(self) -> dict:
        return {k: round(s.level, 1) for k, s in self.segs.items()}

    async def run(self):
        args = [str(ROOT / "bin" / "systap")] + ([] if self.use_mic else ["--no-mic"])
        self.proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        asyncio.create_task(self._stderr())
        r = self.proc.stdout
        try:
            while True:
                head = await r.readexactly(5)
                tag, n = head[0], struct.unpack("<I", head[1:])[0]
                data = await r.readexactly(n)
                if self.paused:
                    continue
                self.segs[SOURCES[tag]].feed(np.frombuffer(data, dtype=np.int16))
        except asyncio.IncompleteReadError:
            pass
        await self.proc.wait()

    async def _stderr(self):
        async for line in self.proc.stderr:
            msg = line.decode(errors="ignore").strip()
            print(msg)
            if "failed" in msg or "stopped" in msg:
                self.error = msg

    def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
