"""Meeting Copilot: live transcript plus Claude's suggested replies, served at http://127.0.0.1:8765."""
import argparse
import asyncio
import json
import re
import signal
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from aiohttp import web, WSMsgType

from .audio import Capture, Transcriber
from .brain import Brain, MODEL, EFFORT, available
from .library import Library

STATIC = Path(__file__).parent / "static"
SETTINGS = Path.home() / ".meeting-copilot.json"
LOGS = Path.home() / "Documents" / "MeetingCopilot"
MODELS = Path.home() / ".cache" / "whisper-cpp" / "models"


def words(t: str) -> set[str]:
    return set(re.findall(r"[a-z']{3,}", t.lower()))


class App:
    def __init__(self, args):
        saved = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
        self.settings = {"library": args.library or saved.get("library", ""), "context": saved.get("context", ""), "auto": saved.get("auto", True), "auto_you": saved.get("auto_you", True),
                         "theme": saved.get("theme", "system"), "model": saved.get("model", MODEL)}
        self.library = Library(self.settings["library"])
        self.brain = Brain(self.library)
        self.transcriber = Transcriber(str(MODELS / f"ggml-{args.whisper}.en.bin"))
        self.capture = Capture(self.on_segment, self.on_speech, use_mic=not args.no_mic)
        self.clients: set[web.WebSocketResponse] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.pending_trigger: asyncio.Task | None = None
        self.auto_task: asyncio.Task | None = None
        self.last_saved = ""
        self.new_session()

    def new_session(self):
        self.lines: list[dict] = []
        self.cards: list[dict] = []
        self.started = time.time()
        self.last_trigger_line = 0
        self.log: Path | None = None  # created when the first line arrives

    # ---------- plumbing ----------
    def save_settings(self):
        SETTINGS.write_text(json.dumps(self.settings, indent=2))

    async def send(self, msg: dict):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def write_log(self, text: str):
        """Appends as the call goes, so nothing is lost if the app stops unexpectedly."""
        if self.log is None:
            LOGS.mkdir(parents=True, exist_ok=True)
            start = datetime.fromtimestamp(self.started)
            self.log = LOGS / f"{start:%Y-%m-%d %H%M} Meeting.md"
            self.log.write_text(f"# Meeting, {start:%d %B %Y, %H:%M}\n\n")
        with self.log.open("a") as f:
            f.write(text + "\n")

    def save_transcript(self) -> str:
        """Rewrites the session file as a clean, complete record of the call."""
        if not self.lines or self.log is None:
            return ""
        start, end = datetime.fromtimestamp(self.started), datetime.now()
        mins = max(1, round((end - start).total_seconds() / 60))
        out = [f"# Meeting, {start:%d %B %Y}", "",
               f"{start:%H:%M} to {end:%H:%M} ({mins} minute{'s' if mins != 1 else ''}).", "",
               "## Transcript", ""]
        out += [f"**{l['t']} {'You' if l['source'] == 'you' else 'Them'}:** {l['text']}  " for l in self.lines]
        replies = [c for c in self.cards if c["text"].strip() and not c["text"].strip().startswith("PASS")]
        if replies:
            out += ["", "## Suggested replies", ""]
            for c in replies:
                out += [f"### {c['t']}, after: {c['trigger'][:120]}", "", c["text"].strip(), ""]
        self.log.write_text("\n".join(out) + "\n")
        return str(self.log)

    async def end_call(self):
        for t in (self.pending_trigger, self.auto_task):
            if t and not t.done():
                t.cancel()
        path = self.save_transcript()
        if path:
            self.last_saved = path
        self.new_session()
        await self.send({"type": "reset", "saved": path})
        await self.send(self.status())

    def stamp(self, t: float) -> str:
        s = int(t - self.started)
        return f"{s // 60:02d}:{s % 60:02d}"

    def status(self) -> dict:
        return {"type": "status", "library": self.library.summary(), "settings": self.settings, "paused": self.capture.paused,
                "capture_error": self.capture.error, "claude": available(), "model": self.settings["model"], "effort": EFFORT, "log": str(self.log or ""), "last_saved": self.last_saved, "folder": str(LOGS)}

    # ---------- audio → transcript ----------
    def on_speech(self, source: str):
        if self.pending_trigger and source in self.auto_sources():
            self.pending_trigger.cancel()  # someone is still talking

    def on_segment(self, source: str, audio):
        self.queue.put_nowait((source, audio, time.time() - len(audio) / 16000))

    async def transcribe_loop(self):
        while True:
            source, audio, t = await self.queue.get()
            prior = " ".join(l["text"] for l in self.lines[-3:])
            try:
                text = await self.transcriber.transcribe(audio, prior)
            except Exception as e:
                print("transcribe error:", e)
                continue
            if not text:
                continue
            if source == "you" and self.is_echo(text, t):
                continue
            line = {"id": len(self.lines), "source": source, "text": text, "t": self.stamp(t)}
            self.lines.append(line)
            self.write_log(f"**{line['t']} {'You' if source == 'you' else 'Them'}:** {text}  ")
            await self.send({"type": "line", **line})
            if source in self.auto_sources():
                if self.pending_trigger:
                    self.pending_trigger.cancel()
                self.pending_trigger = asyncio.create_task(self.debounced_trigger())

    def is_echo(self, text: str, t: float) -> bool:
        """Without headphones the mic hears the speakers; drop mic lines that repeat what Them just said."""
        w = words(text)
        if not w:
            return False
        recent = [l for l in self.lines[-6:] if l["source"] == "them"]
        theirs = set().union(*(words(l["text"]) for l in recent)) if recent else set()
        return len(w & theirs) / len(w) > 0.6

    def auto_sources(self) -> set[str]:
        """Which speakers trigger automatic suggestions, from the two toggles."""
        return {k for k, on in (("them", self.settings["auto"]), ("you", self.settings["auto_you"])) if on}

    async def debounced_trigger(self):
        await asyncio.sleep(1.2)
        sources = self.auto_sources()
        if any(seg.active for name, seg in self.capture.segs.items() if name in sources):
            return
        new = [l for l in self.lines[self.last_trigger_line:] if l["source"] in sources]
        if sum(len(l["text"].split()) for l in new) < 4:
            return
        self.last_trigger_line = len(self.lines)
        said = "\n".join(f"{'You' if l['source'] == 'you' else 'Them'}: {l['text']}" for l in new[-6:])
        who = "The user" if new[-1]["source"] == "you" else "The other side"
        if self.auto_task and not self.auto_task.done():
            self.auto_task.cancel()
        self.auto_task = asyncio.create_task(self.make_card("auto", f"{who} spoke last. New since the previous suggestion:\n{said}", said))

    # ---------- suggestions ----------
    def transcript_text(self) -> str:
        out, size = [], 0
        for l in reversed(self.lines):
            row = f"[{l['t']}] {'You' if l['source'] == 'you' else 'Them'}: {l['text']}"
            size += len(row)
            if size > 12000:
                break
            out.append(row)
        return "\n".join(reversed(out))

    async def make_card(self, kind: str, trigger: str, query: str):
        card = {"id": len(self.cards), "kind": kind, "trigger": query, "t": self.stamp(time.time()), "text": ""}
        self.cards.append(card)
        await self.send({"type": "card_start", **card})

        async def emit(kind_, **data):
            if kind_ == "card_reset":
                card["text"] = ""
            elif kind_ == "card_delta":
                card["text"] += data["text"]
            await self.send({"type": kind_, "id": card["id"], **data})

        recent = " ".join(l["text"] for l in self.lines[-2:])
        passages = [p for p in self.library.search(f"{query} {recent}", k=3) if p["score"] > 1.5]
        try:
            sources = await self.brain.suggest(self.settings["context"], self.transcript_text(), passages, trigger, emit, self.settings["model"])
        except asyncio.CancelledError:
            await self.send({"type": "card_cancel", "id": card["id"]})
            raise
        except Exception as e:
            await self.send({"type": "card_error", "id": card["id"], "error": f"{type(e).__name__}: {e}"})
            return
        await self.send({"type": "card_done", "id": card["id"], "sources": sources})
        if not card["text"].strip().startswith("PASS"):
            self.write_log(f"\n> **Suggestion ({card['t']})**\n> " + card["text"].strip().replace("\n", "\n> ") + "\n")

    # ---------- web ----------
    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_json(self.status())
        await ws.send_json({"type": "history", "lines": self.lines, "cards": self.cards})
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            d = json.loads(msg.data)
            cmd = d.get("cmd")
            if cmd == "suggest":
                asyncio.create_task(self.make_card("manual", "The user asked for a suggestion now. Respond to the latest exchange.", "latest exchange"))
            elif cmd == "ask" and d.get("text", "").strip():
                q = d["text"].strip()
                asyncio.create_task(self.make_card("ask", f"The user typed this privately (the other side cannot see it). Answer it so the user can use it in the meeting:\n{q}", q))
            elif cmd == "settings":
                for k in ("context", "auto", "auto_you", "library", "theme", "model"):
                    if k in d:
                        self.settings[k] = d[k]
                if self.settings["model"] not in ("opus", "sonnet"):
                    self.settings["model"] = "opus"
                if self.settings["theme"] not in ("system", "light", "dark"):
                    self.settings["theme"] = "system"
                if "library" in d:
                    self.library.__init__(d["library"])
                    await asyncio.to_thread(self.library.refresh)
                self.save_settings()
                await self.send(self.status())
            elif cmd == "end":
                await self.end_call()
            elif cmd == "open_folder":
                LOGS.mkdir(parents=True, exist_ok=True)
                await asyncio.create_subprocess_exec("open", d.get("path") or str(LOGS))
            elif cmd == "pause":
                self.capture.paused = bool(d.get("paused"))
                await self.send(self.status())
        self.clients.discard(ws)
        return ws

    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    async def levels_loop(self):
        last_err = ""
        while True:
            await asyncio.sleep(0.15)
            if self.clients:
                await self.send({"type": "levels", **self.capture.levels()})
            if self.capture.error != last_err:
                last_err = self.capture.error
                await self.send(self.status())

    async def library_loop(self):
        while True:
            if await asyncio.to_thread(self.library.refresh):
                await self.send(self.status())
            await asyncio.sleep(20)


async def main(args):
    app = App(args)
    print("Starting whisper-server…")
    await app.transcriber.start()
    web_app = web.Application()
    web_app.router.add_get("/", app.index)
    web_app.router.add_get("/ws", app.ws_handler)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Meeting Copilot running at {url}\nTranscripts are saved in {LOGS}")
    if not args.no_browser:
        webbrowser.open(url)
    tasks = [asyncio.create_task(c) for c in (app.capture.run(), app.transcribe_loop(), app.levels_loop(), app.library_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        saved = app.save_transcript()
        if saved:
            print(f"Transcript saved: {saved}")
        app.capture.stop()
        await app.transcriber.stop()


def cli():
    p = argparse.ArgumentParser(description="Live meeting assistant")
    p.add_argument("--library", help="Folder of documents Claude can search")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--whisper", choices=["small", "medium"], default="small", help="Speech model: small is faster, medium is more accurate")
    p.add_argument("--no-mic", action="store_true", help="Only capture computer audio")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
