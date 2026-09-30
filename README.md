# Teams Transcript Scraper

> Extract meeting transcripts from MS Teams when you're **not** the organiser.

Microsoft only lets the meeting organiser download transcript files — which is awful. This script reads the transcript directly from an open Teams window using accessibility APIs and saves it as a clean Markdown file.

---

## How it works

1. Finds your open Microsoft Teams window
2. Locates the **Transcript** panel (right-hand side)
3. Walks the accessibility tree to extract speaker names, timestamps, and text
4. Scrolls through the panel automatically to capture the full transcript
5. Deduplicates entries and saves everything as `.md`

No network requests, no logins, no APIs — it reads what's already on your screen.

---



## Prerequisites

- **Python 3.9+**
- **Microsoft Teams** open with a meeting transcript visible  
(click the `⋯` menu or `Transcript` button during/after a meeting)

---



## Installation



### Windows

```powershell
# Clone the repo
git clone https://github.com/visser23/teams-transcript-scraper.git
cd teams-transcript-scraper

# Create a virtual environment (recommended)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```



### macOS

```bash
# Clone the repo
git clone https://github.com/visser23/teams-transcript-scraper.git
cd teams-transcript-scraper

# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```



#### macOS — Grant Accessibility Permission

The script uses the macOS Accessibility API, so your terminal needs permission:

1. Open **System Settings → Privacy & Security → Accessibility**
2. Click the **+** button and add your terminal app
  (Terminal, iTerm2, Warp, VS Code, etc.)
3. Restart the terminal app

The script will remind you if this step is missing.

---



## Usage



### 1. Open the transcript in Teams

In your Teams meeting window, make sure the **Transcript** panel is visible on the right-hand side. Click **Transcript** in the meeting toolbar if it isn't showing.

### 2. Run the script

```bash
python scrape_transcript.py
```

The script will find the Teams window, scroll through the transcript, and save it:

```
╔══════════════════════════════════════╗
║   Teams Transcript Scraper           ║
╚══════════════════════════════════════╝

🖥   Platform: Windows
🔍  Searching for Microsoft Teams…

📌  Found window: Frontline Productivity initial proposal
📋  Transcript panel detected
📜  Scrolling through transcript…
   ⤷ 25 entries so far…
   ⤷ 47 entries so far…

✅  Saved 47 entries → transcript_20260930_104400.md
```



### Where the output goes

- By default, output is written to the folder you run the command from.
- Default filename format: `transcript_YYYYMMDD_HHMMSS.md`
- Set a custom path with `-o`, for example:

```bash
python scrape_transcript.py -o ./output/meeting-notes.md
```

PowerShell equivalent:

```powershell
python .\scrape_transcript.py -o .\output\meeting-notes.md
```


### 3. Options


| Flag                       | Description                                                   |
| -------------------------- | ------------------------------------------------------------- |
| `-o FILE`, `--output FILE` | Custom output path (default: `transcript_YYYYMMDD_HHMMSS.md`) |
| `--debug`                  | Dump the Teams UI tree to the console for troubleshooting     |


Examples:

```bash
# Save to a specific file
python scrape_transcript.py -o meeting-notes.md

# Troubleshoot — see what the script can see in the UI tree
python scrape_transcript.py --debug
```

---



## Output format

The script produces clean Markdown:

```markdown
# Transcript: Frontline Productivity initial proposal

*Extracted on 2026-09-30 10:44:00 — 47 entries*

---

**Steve Hodgson** *[0:03]*

And what are the assumptions around the delays? Because we're not
contracting.

**Frank Smith** *[0:27]*

Unsure at this point, I'll have the team look into it asap. I think Richard is leading on this.
```

---



## Troubleshooting


| Problem                                       | Fix                                                                                                                                                       |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **"Teams window not found"**                  | Make sure Teams is running and a meeting window is open (not just the chat/calendar).                                                                     |
| **"Transcript panel not detected"**           | Click the **Transcript** button in the Teams meeting toolbar so the panel is visible.                                                                     |
| **"No transcript entries found"**             | Run `--debug` to see the UI tree. Teams may have updated its UI structure — open an issue with the debug output.                                          |
| **macOS "Accessibility permission required"** | See the macOS permission step above.                                                                                                                      |
| **Only partial transcript captured**          | The script auto-scrolls, but very long transcripts (1 hr+) may take a moment. If entries are missing, try again — the scroll timing might need adjusting. |


---



## Limitations

- Works with the **new Microsoft Teams** (Electron-based). The classic/legacy Teams app has a different UI tree and may not work.
- The script reads the accessibility tree, which depends on the Teams UI structure. Major Teams updates could break extraction — run `--debug` and open an issue if this happens.
- On macOS, the script brings Teams to the foreground during scrolling.

---



## Contributing

Found a bug or Teams changed its UI? Run `--debug`, capture the output, and open an issue. PRs welcome.

---



## Licence

See [LICENSE](LICENSE).