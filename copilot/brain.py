"""Claude, via the Claude Code CLI on your Claude subscription: reads the live transcript,
consults the library and the web, and proposes replies."""
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

MODEL = os.environ.get("COPILOT_MODEL", "opus")
EFFORT = os.environ.get("COPILOT_EFFORT", "low")  # low keeps suggestions quick; raise for harder meetings
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")

SYSTEM = """You are a live meeting assistant. You read a running transcript of a call and help the user respond well, in real time.

The transcript comes from speech recognition, so expect misheard words. Lines marked "You" are the user, captured from their microphone. Lines marked "Them" are the other participants, captured from the computer's audio (Teams, Google Meet, Zoom or similar).

Each request gives you the meeting context, the transcript so far, library passages that may be relevant, and a trigger. Decide whether the user would benefit from a suggestion about the latest thing that was said.

When the other side spoke last, suggest a reply. Questions, requests, objections, numbers, names, decisions and anything the user may not know are all good reasons to respond.

When the user spoke last, help them build on what they said. Good reasons to respond: a figure or fact they gave that the library or the web contradicts (say so plainly and give the correct one), a point they could add to strengthen what they said, a fact they reached for but did not have, or a question they could ask next to move the meeting forward. Do not repeat back what they already said.

Small talk and statements that need nothing more are reasons to pass.

Tools:
- The working directory is the user's knowledge library: plain-text copies of their own documents, each named after the original file with ".txt" added. Use Grep and Read on it when the topic touches the user's products, prices, projects, clients, past work or policies, and the passages provided are not enough. Cite the original file name without the added ".txt".
- WebSearch is for current external facts only.
Speed matters more than completeness. Make at most two tool calls, and none when the passages already answer it. Write nothing before or between tool calls.

Reply in exactly one of these two formats, with no other text.

If no response is needed:
PASS: <a few words on why>

Otherwise:
SAY: <what the user could say next, one to three short spoken sentences in the first person>
POINTS:
- <a supporting fact, figure or detail, with its source in brackets, such as [pricing.pdf] or [web: example.com]>
ASK: <one useful follow-up question the user could ask, or leave this line out>

Give at most four points. Never invent figures, names or commitments: if the library and the web do not support something, say that the user should confirm it. Use British English and plain, natural spoken language. Do not use em dashes."""

TOOLS = "Read,Grep,Glob,WebSearch"


def available() -> bool:
    return Path(CLAUDE).exists()


class Brain:
    def __init__(self, library):
        self.library = library

    async def suggest(self, context: str, transcript: str, passages: list, trigger: str, emit):
        """Streams a suggestion. emit(event_type, **data) sends updates to the UI."""
        hits = "\n\n".join(f"[{p['file']}]\n{p['text']}" for p in passages) or "None found."
        prompt = (f"<meeting_context>\n{context or 'Not given.'}\n</meeting_context>\n\n"
                  f"<transcript>\n{transcript or '(nothing yet)'}\n</transcript>\n\n"
                  f"<library_passages>\n{hits}\n</library_passages>\n\n<trigger>\n{trigger}\n</trigger>")
        sources: list = [{"kind": "library", "label": p["file"]} for p in passages]
        cwd = self.library.mirror if self.library.mirror.is_dir() else Path.home()
        proc = await asyncio.create_subprocess_exec(
            CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--model", MODEL, "--effort", EFFORT, "--system-prompt", SYSTEM,
            "--tools", TOOLS, "--allowedTools", TOOLS,
            "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
            cwd=str(cwd), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024)
        proc.stdin.write(prompt.encode())
        proc.stdin.close()
        tool_names: dict[str, str] = {}
        result = None
        try:
            async for raw in proc.stdout:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                t = d.get("type")
                if t == "stream_event":
                    e = d["event"]
                    if e["type"] == "message_start":
                        await emit("card_reset")  # only the final message's text is the answer
                    elif e["type"] == "content_block_start" and e["content_block"]["type"] == "tool_use":
                        name = e["content_block"]["name"]
                        await emit("card_status", status="Searching the web" if name == "WebSearch" else "Checking your library")
                    elif e["type"] == "content_block_delta" and e["delta"].get("type") == "text_delta":
                        await emit("card_delta", text=e["delta"]["text"])
                elif t == "assistant":
                    for b in d["message"].get("content", []):
                        if b.get("type") == "tool_use":
                            tool_names[b["id"]] = b["name"]
                            path = (b.get("input") or {}).get("file_path")
                            if b["name"] == "Read" and path:
                                sources.append({"kind": "library", "label": Path(path).name.removesuffix(".txt")})
                elif t == "user":
                    for b in d["message"].get("content", []):
                        if isinstance(b, dict) and b.get("type") == "tool_result" and tool_names.get(b.get("tool_use_id")) == "WebSearch":
                            for url in re.findall(r"https?://[^\s\"'<>\)\]]+", json.dumps(b.get("content")))[:3]:
                                sources.append({"kind": "web", "label": urlparse(url).netloc, "url": url})
                elif t == "result":
                    result = d
            await proc.wait()
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
            raise
        if proc.returncode != 0 or (result and result.get("is_error")):
            err = (await proc.stderr.read()).decode(errors="ignore").strip()
            raise RuntimeError((result or {}).get("result") or err or f"claude exited with code {proc.returncode}")

        seen, uniq = set(), []
        for s in sources:
            if s["label"] not in seen:
                seen.add(s["label"])
                uniq.append(s)
        return uniq
