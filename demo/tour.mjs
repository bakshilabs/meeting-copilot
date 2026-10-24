// Demo video of Meeting Copilot: plays a scripted call through the real interface.
// Suggestions in script.json were produced by the real pipeline (demo/generate.py).
// Run:  DRY=1 SNAP=1 THEME=light node demo/tour.mjs     (preview)
//       THEME=light node demo/tour.mjs && python3 demo/mux.py   (render, then add the voices)
import { createRecorder } from '/Users/atlasm2/.claude/skills/web-demo-video/scripts/recorder.mjs';
import fs from 'node:fs';
import path from 'node:path';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const ROOT = path.dirname(HERE);
const { context, beats } = JSON.parse(fs.readFileSync(path.join(HERE, 'script.json'), 'utf8'));
const env = JSON.parse(fs.readFileSync(path.join(HERE, 'audio/envelopes.json'), 'utf8'));
fs.mkdirSync(path.join(HERE, 'out'), { recursive: true });

const r = await createRecorder({
  url: `file://${ROOT}/copilot/static/index.html?demo`,
  out: path.join(HERE, 'out/Meeting-Copilot-demo'),
  waitFor: '#transcript',
  outDir: path.join(HERE, 'out'),
  width: 1280, height: 720, scale: 3,
});
const page = r.page;
const emit = (m) => page.evaluate((m) => handle(m), m);
const cues = [];
let callStart = 0, cardId = 0;
const stamp = () => { const s = Math.max(0, Math.round(r.time - callStart)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const quiet = () => -68 + Math.random() * 4;

await emit({ type: 'status', library: { folder: '~/Documents/DeltaOps Library', files: 3, chunks: 3 }, settings: { library: '~/Documents/DeltaOps Library', context, auto: true, auto_you: true },
  paused: false, capture_error: '', claude: true, model: 'opus', effort: 'low', log: '', last_saved: '', folder: '~/Documents/MeetingCopilot' });
await emit({ type: 'history', lines: [], cards: [] });

async function idle(sec) {
  for (let i = 0; i < Math.round(sec * 60); i++) { await emit({ type: 'levels', you: quiet(), them: quiet() }); await r.hold(1 / 60); }
}

// Plays one spoken line: meters follow the real audio, then the transcript line appears.
async function speak(i) {
  const b = beats[i], db = env[i];
  cues.push({ file: `audio/line${i}.wav`, at: r.time });
  for (const v of db) {
    const lv = Math.max(v + 6, quiet());
    await emit({ type: 'levels', you: b.source === 'you' ? lv : quiet(), them: b.source === 'them' ? lv : quiet() });
    await r.hold(1 / 60);
  }
  await idle(0.8);  // transcription
  await emit({ type: 'line', id: i, source: b.source, text: b.text, t: stamp() });
}

// Streams a suggestion card the way the app does: status first, then text arriving.
async function card(i, kind, trigger, { library = true } = {}) {
  const id = cardId++, b = beats[i];
  await emit({ type: 'card_start', id, kind, trigger, t: stamp(), text: '' });
  await idle(0.9);
  if (library) { await emit({ type: 'card_status', id, status: 'Checking your library' }); await idle(1.1); }
  const text = b.card;
  for (let k = 0; k < text.length; k += 4) {
    await emit({ type: 'card_delta', id, text: text.slice(k, k + 4) });
    await emit({ type: 'levels', you: quiet(), them: quiet() });
    await r.hold(1 / 60);
  }
  await emit({ type: 'card_done', id, sources: b.sources });
}

// ================= SCRIPT =================
await r.titleCard(`<div><div class="k">Meeting Copilot</div><h1>Suggested replies, live in your calls</h1><p>It listens to both sides of a call and suggests what to say,<br>using your own documents.</p></div>`, 3.6);

await r.caption('Set up', 'Point it at a folder of your documents and describe the meeting.');
await idle(0.6);
await r.click('Settings', 0.4);
await idle(3.2);
await r.click('Save', 0.3);
await idle(0.6);

callStart = r.time;
await r.caption('Listening', 'It transcribes both sides of the call, from your microphone and from the call audio.');
await r.moveTo(r.W * 0.5, r.H * 0.86, 0.6);
await speak(0);
await r.caption('Suggested reply', 'When the other side finishes speaking, it suggests what you could say next.');
await card(0, 'auto', `Them: ${beats[0].text}`);
await idle(5.5);

await r.caption('Your library', 'It looks up prices and details in your own files, and shows where each point came from.');
await speak(1);
await card(1, 'auto', `Them: ${beats[1].text}`);
await idle(6.5);

await r.caption('After you speak', 'It checks what you say too. Here it notices a price that was quoted wrongly.');
await speak(2);
await card(2, 'auto', `You: ${beats[2].text}`);
await idle(6.5);

await r.caption('Private questions', 'You can ask a question during the call. Only you see the answer.');
await idle(2.2);
await r.hideCaption();
const box = await r.find('css', '#askq');
await r.moveTo(box.x - 120, box.y, 0.6); await r.press(); await page.focus('#askq');
for (const ch of beats[3].text) { await page.keyboard.type(ch); await idle(0.05); }
await idle(0.4);
await page.keyboard.press('Enter');
await card(3, 'ask', beats[3].text);
await idle(6);

await r.caption('Next steps', 'Each suggestion ends with a question you could ask to move the conversation on.');
await speak(4);
await card(4, 'auto', `Them: ${beats[4].text}`);
await idle(5);

await r.caption('End call', 'At the end of the call, the transcript and the suggestions are saved to a file.');
await idle(1.2);
await r.click('End call', 0.3);
await emit({ type: 'reset', saved: '~/Documents/MeetingCopilot/2026-10-24 1500 Meeting.md' });
await idle(4.5);
await r.hideCaption();

await r.titleCard(`<div><div class="k">Meeting Copilot</div><h1>Transcribed on your computer</h1><p>Your documents stay in your folder. Each call is saved when it ends.</p></div>`, 3.2);
// ================= END SCRIPT =================
fs.writeFileSync(path.join(HERE, 'out/cues.json'), JSON.stringify(cues, null, 2));
await r.finish();
