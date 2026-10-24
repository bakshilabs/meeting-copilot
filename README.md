# Meeting Copilot

Listens to your microphone and to your computer's audio (Teams, Google Meet, Zoom or any other app), transcribes both on this Mac with whisper.cpp, and asks Claude to propose replies as the meeting happens. Claude can search a folder of your documents and the web.

## Requirements

- macOS 15 or later, with Xcode command line tools (`xcode-select --install`)
- [Homebrew](https://brew.sh) packages: `brew install whisper-cpp uv`
- A whisper model: `mkdir -p ~/.cache/whisper-cpp/models && curl -L -o ~/.cache/whisper-cpp/models/ggml-small.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin`
- Claude Code, logged in to a Claude subscription (`claude` once to log in)

Build the dock app with `app/build.sh`. It is installed in ~/Applications.

## Run

Click Meeting Copilot in the dock. To rebuild the app after changing the launcher or icon, run `app/build.sh`.

From a terminal instead:

    ./run.sh --library ~/path/to/folder

Claude runs through the Claude Code CLI on your Claude subscription, so no API key is needed. Run `claude` once and log in if you have not already.

The page opens at http://127.0.0.1:8765. Options: `--whisper medium` (more accurate, slower), `--no-mic`, `--port`.
Set `COPILOT_EFFORT=medium` for more considered (slower) suggestions, or `COPILOT_MODEL=sonnet` to use Sonnet.

## First run

Give Meeting Copilot Screen Recording and Microphone permission in System Settings > Privacy & Security, then quit and reopen it. (If you run it from a terminal, the terminal app needs these permissions instead.) Rebuilding the app can reset the permissions.

## Notes

- Headphones give the cleanest transcript. Without them the mic hears the call too; lines that repeat what the other side just said are dropped.
- Library formats: PDF, Word, PowerPoint, Markdown, text, CSV, HTML. The folder is re-indexed every 20 seconds.
- Each session's transcript and suggestions are saved in ~/Documents/MeetingCopilot.
- Only the transcript and library passages are sent to Claude. Audio stays on this Mac.
