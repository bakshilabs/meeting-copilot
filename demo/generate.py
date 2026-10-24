"""Runs the demo call through the real suggestion pipeline and saves Claude's output to demo/script.json."""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot.library import Library
from copilot.brain import Brain

CONTEXT = "I run DeltaOps Training, which delivers AI workshops for companies. I'm talking to Northgate Group's head of learning about training for their staff."
BEATS = [
    ("them", "Thanks for making the time. We're planning AI training for about forty staff in the spring, mostly in our finance and HR teams."),
    ("them", "What would a full day cost for a group that size? And would you come up to our Leeds office?"),
    ("you", "For a group of forty, we'd run two days at two thousand pounds each."),
    ("ask", "What results did Harbour Housing get?"),
    ("them", "That sounds really useful. Could you send a proposal over by Friday?"),
]

async def main():
    lib = Library(str(Path(__file__).parent / "library")); lib.refresh()
    brain = Brain(lib)
    lines, out = [], []
    for i, (src, text) in enumerate(BEATS):
        if src == "ask":
            trigger = f"The user typed this privately (the other side cannot see it). Answer it so the user can use it in the meeting:\n{text}"
        else:
            lines.append((src, text))
            who = "The user" if src == "you" else "The other side"
            trigger = f"{who} spoke last. New since the previous suggestion:\n{'You' if src == 'you' else 'Them'}: {text}"
        transcript = "\n".join(f"[00:{10*j:02d}] {'You' if s == 'you' else 'Them'}: {t}" for j, (s, t) in enumerate(lines))
        recent = " ".join(t for _, t in lines[-2:])
        passages = [p for p in lib.search(f"{text} {recent}", k=3) if p["score"] > 1.5]
        chunks = []
        async def emit(k, **d):
            if k == "card_reset": chunks.clear()
            if k == "card_delta": chunks.append(d["text"])
        sources = await brain.suggest(CONTEXT, transcript, passages, trigger, emit)
        out.append({"source": src, "text": text, "card": "".join(chunks).strip(), "sources": sources})
        print(f"--- {src}: {text}\n{out[-1]['card']}\n{sources}\n")
    (Path(__file__).parent / "script.json").write_text(json.dumps({"context": CONTEXT, "beats": out}, indent=2, ensure_ascii=False))

asyncio.run(main())
