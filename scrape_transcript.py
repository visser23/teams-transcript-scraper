#!/usr/bin/env python3
"""
Teams Transcript Scraper
========================
Extracts meeting transcripts from an open MS Teams transcript panel
and saves them as a clean Markdown file.

Works on Windows 10/11 and macOS.

Usage:
    python scrape_transcript.py                     # auto-named output
    python scrape_transcript.py -o meeting.md       # custom output path
    python scrape_transcript.py --debug             # dump UI tree for troubleshooting
"""

import argparse
import io
import platform
import sys
import time
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Ensure stdout can handle unicode (Windows terminals default to cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )

# ── Configuration ─────────────────────────────────────────────────

SCROLL_PAUSE = 0.5
MAX_SCROLLS = 300
TREE_DEPTH = 50
DEBUG_TREE_DEPTH = 12
STALE_SCROLL_LIMIT = 5

# Spoken timestamps from the Teams accessibility tree
#   "0 minutes 3 seconds", "1 hour 2 minutes 30 seconds", "25 minutes", etc.
SPOKEN_TS_RE = re.compile(
    r"(?:(\d+)\s+hours?\s+)?(\d+)\s+minutes?(?:\s+(\d+)\s+seconds?)?"
)

SYSTEM = platform.system()

# Text fragments to ignore during extraction
NOISE_FRAGMENTS = frozenset([
    "started transcription", "stopped transcription",
    "is this transcript useful", "ai-generated content",
    "arrow keys to navigate", "request a licence",
    "speaker info isn't available",
    "sync to video",
])


# ── Data ──────────────────────────────────────────────────────────

@dataclass
class TranscriptEntry:
    speaker: str
    timestamp: str
    text: str


# ── Shared helpers ────────────────────────────────────────────────

def fail(msg: str):
    print(f"\n❌  {msg}")
    sys.exit(1)


def parse_spoken_timestamp(text: str) -> Optional[str]:
    """Convert 'N minutes N seconds' → 'M:SS' or 'H:MM:SS'."""
    m = SPOKEN_TS_RE.search(text)
    if not m:
        return None
    hrs = int(m.group(1) or 0)
    mins = int(m.group(2))
    secs = int(m.group(3) or 0)
    if hrs:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def is_noise(text: str) -> bool:
    low = text.lower()
    return any(frag in low for frag in NOISE_FRAGMENTS)


def is_pure_timestamp(text: str) -> bool:
    """True if the entire string is just a spoken timestamp."""
    stripped = text.strip()
    m = SPOKEN_TS_RE.match(stripped)
    return m is not None and m.end() == len(stripped)


# ══════════════════════════════════════════════════════════════════
#  CROSS-PLATFORM TRANSCRIPT PARSER  (from flat tree walk)
# ══════════════════════════════════════════════════════════════════

def parse_tree_items(items: List[Tuple[int, str, str]]) -> List[TranscriptEntry]:
    """
    Parse transcript entries from a flat tree walk.

    Each item is (depth, controlType, name).

    Teams transcript tree pattern (observed):
        [GroupControl]     "Transcript. Use arrow keys …"     ← MARKER
        [ListItemControl]  "SPEAKER started transcription"    ← system msg (skip)
        [ListItemControl]  "SPEAKERTimestamp"                 ← header
          [TextControl]    "SPEAKER"                          ← speaker name
          [TextControl]    "N minutes N seconds"              ← timestamp
        [GroupControl]     "SPEAKER Timestamp"                ← content group
          [TextControl]    "SPEAKER Timestamp"                ← label (skip)
          [ListItemControl] "Actual spoken text…"             ← CONTENT
            [TextControl]  "Actual spoken text…"              ← duplicate (skip)
    """
    # 1. Find where the transcript entries begin
    start = _find_transcript_start(items)
    if start is None:
        return []

    # The marker's depth defines the boundary: only process items at
    # this depth or deeper.  Once the walk returns to a shallower part
    # of the tree we've left the transcript section entirely.
    marker_depth = items[start - 1][0]

    # 2. Walk through items and extract
    entries: List[TranscriptEntry] = []
    current_speaker: Optional[str] = None
    current_ts = "0:00"
    prev_text: Optional[str] = None
    below_depth_run = 0
    seen_speakers: set = set()

    i = start
    while i < len(items):
        depth, _ct, name = items[i]

        # Stop when we leave the transcript subtree
        if depth < marker_depth:
            below_depth_run += 1
            if below_depth_run >= 3:
                break
            i += 1
            continue
        below_depth_run = 0

        # Skip noise / system messages
        if is_noise(name):
            i += 1
            continue

        # ── Does this element contain a spoken timestamp? ─────────
        ts_match = SPOKEN_TS_RE.search(name)

        if ts_match:
            # Pure standalone timestamp (e.g. "0 minutes 3 seconds")
            if is_pure_timestamp(name):
                ts = parse_spoken_timestamp(name)
                if ts:
                    current_ts = ts
                i += 1
                prev_text = name
                continue

            # Combined "SPEAKER Timestamp" (header or group label)
            speaker_part = name[: ts_match.start()].strip()
            ts = parse_spoken_timestamp(name)
            if speaker_part:
                current_speaker = speaker_part
                seen_speakers.add(speaker_part)
            if ts:
                current_ts = ts
            i += 1
            prev_text = name
            continue

        # ── No timestamp — could be speaker name or content text ──

        # Skip duplicates (each text appears in parent + child)
        if name == prev_text:
            i += 1
            continue

        # Check if the NEXT item is a standalone timestamp
        # → this element is a speaker name
        if i + 1 < len(items):
            _nd, _nct, next_name = items[i + 1]
            if is_pure_timestamp(next_name):
                current_speaker = name
                i += 1
                prev_text = name
                continue

        # Must be content text — but skip if it looks like a stray header
        if current_speaker and len(name) > 2:
            # Skip if the text matches any known speaker name
            if name in seen_speakers:
                i += 1
                continue
            entries.append(TranscriptEntry(
                speaker=current_speaker,
                timestamp=current_ts,
                text=name,
            ))

        prev_text = name
        i += 1

    return entries


def _find_transcript_start(items: List[Tuple[int, str, str]]) -> Optional[int]:
    """Find the index just after the transcript list marker."""
    for i, (_d, _ct, name) in enumerate(items):
        low = name.lower()
        if "transcript" in low and "arrow keys" in low:
            return i + 1
    return None


# ══════════════════════════════════════════════════════════════════
#  WINDOWS IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════

def scrape_windows(debug: bool = False) -> Tuple[List[TranscriptEntry], str]:
    try:
        import uiautomation as auto
    except ImportError:
        fail("Missing dependency.  Run:  pip install uiautomation")

    # 1. Find Teams windows
    all_teams = _win_find_all_teams(auto)
    if not all_teams:
        fail("Microsoft Teams window not found.  Is Teams running?")

    print(f"📌  Found {len(all_teams)} Teams window(s)")
    for w in all_teams:
        print(f"    • {w.Name}")

    # 2. Debug mode
    if debug:
        for w in all_teams:
            print(f"\n--- [{w.Name}] depth {DEBUG_TREE_DEPTH} ---\n")
            _win_dump_tree(w, max_depth=DEBUG_TREE_DEPTH)
        return [], (all_teams[0].Name or "Teams Meeting")

    # 3. Walk each window's tree looking for transcript entries
    target_win = None
    tree_items: List[Tuple[int, str, str]] = []

    for w in all_teams:
        items = _win_walk_tree(w)
        if _find_transcript_start(items) is not None:
            target_win = w
            tree_items = items
            break

    if target_win is None:
        fail("Transcript panel not detected in any Teams window.\n"
             "   Open a Teams meeting → click 'Transcript' to start or view it.")

    title = (target_win.Name or "Teams Meeting").split(" | ")[0]
    print(f"\n📋  Transcript found in: {title}")

    # 4. Extract entries
    entries = parse_tree_items(tree_items)
    print(f"   ⤷ {len(entries)} entries in initial view")

    # 5. Scroll for more entries
    if entries:
        entries = _win_keyboard_scroll_and_collect(
            target_win, auto, entries,
        )

    return entries, title


def _win_find_all_teams(auto) -> List:
    windows = []
    for win in auto.GetRootControl().GetChildren():
        try:
            name = (win.Name or "").lower()
            cls = (win.ClassName or "").lower()
            if ("microsoft teams" in name
                    or "teamswebview" in cls
                    or ("teams" in name and cls)):
                windows.append(win)
        except Exception:
            continue
    return windows


def _win_walk_tree(element, depth: int = 0,
                   max_depth: int = TREE_DEPTH) -> List[Tuple[int, str, str]]:
    """Depth-first walk collecting (depth, controlType, name) for named elements."""
    items: List[Tuple[int, str, str]] = []
    if depth > max_depth:
        return items
    try:
        name = (element.Name or "").strip()
        ct = element.ControlTypeName or ""
        if name:
            items.append((depth, ct, name))
        for ch in element.GetChildren():
            items.extend(_win_walk_tree(ch, depth + 1, max_depth))
    except Exception:
        pass
    return items


def _ts_sort_key(entry: TranscriptEntry) -> int:
    """Convert timestamp string to total seconds for sorting."""
    parts = entry.timestamp.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return 0


def _win_keyboard_scroll_and_collect(teams_window, auto,
                                     initial_entries: List[TranscriptEntry]) -> List[TranscriptEntry]:
    """Scroll the transcript panel via mouse wheel and collect all entries."""
    seen: set = set()
    all_entries = list(initial_entries)
    for e in initial_entries:
        seen.add(f"{e.speaker}|{e.timestamp}|{e.text[:50]}")

    # Locate the transcript panel on screen
    click_x, click_y = _win_find_transcript_click_pos(teams_window)
    if click_x is None:
        print("   ⚠ Could not locate transcript panel position")
        return initial_entries

    print(f"📜  Scrolling transcript panel (mouse at {click_x}, {click_y})…")

    # Bring Teams to front and click on the transcript to focus it
    try:
        teams_window.SetActive()
        time.sleep(0.3)
    except Exception:
        pass

    auto.Click(click_x, click_y)
    time.sleep(0.3)

    # Scroll to top — use enough wheel ticks for long transcripts
    auto.SetCursorPos(click_x, click_y)
    for _ in range(5):
        auto.WheelUp(wheelTimes=30)
        time.sleep(0.15)
    time.sleep(SCROLL_PAUSE)

    # Re-extract from top
    items = _win_walk_tree(teams_window)
    for e in parse_tree_items(items):
        key = f"{e.speaker}|{e.timestamp}|{e.text[:50]}"
        if key not in seen:
            seen.add(key)
            all_entries.append(e)

    stale = 0
    for i in range(MAX_SCROLLS):
        auto.SetCursorPos(click_x, click_y)
        auto.WheelDown(wheelTimes=5)
        time.sleep(SCROLL_PAUSE)

        items = _win_walk_tree(teams_window)
        batch = parse_tree_items(items)

        new_count = 0
        for e in batch:
            key = f"{e.speaker}|{e.timestamp}|{e.text[:50]}"
            if key not in seen:
                seen.add(key)
                all_entries.append(e)
                new_count += 1

        if new_count == 0:
            stale += 1
            if stale >= STALE_SCROLL_LIMIT:
                break
        else:
            stale = 0

        if (i + 1) % 5 == 0:
            print(f"   ⤷ {len(all_entries)} entries so far…")

    all_entries.sort(key=_ts_sort_key)
    return all_entries


def _win_find_transcript_click_pos(teams_window) -> Tuple[Optional[int], Optional[int]]:
    """Find on-screen coordinates inside the transcript panel for mouse scrolling."""
    # Screen bounds sanity check
    win_rect = teams_window.BoundingRectangle
    if not win_rect:
        return (None, None)
    screen_left, screen_top = win_rect.left, win_rect.top
    screen_right, screen_bottom = win_rect.right, win_rect.bottom

    def _is_on_screen(rect):
        """Check if a rectangle is actually visible on screen."""
        return (rect and rect.width() > 10 and rect.height() > 5
                and rect.left >= screen_left - 50
                and rect.top >= screen_top - 50
                and rect.right <= screen_right + 50
                and rect.bottom <= screen_bottom + 50)

    # Strategy 1: find the "Transcript" GroupControl panel and click centre
    def _find_panel(el, depth=0):
        if depth > TREE_DEPTH:
            return None
        try:
            name_low = (el.Name or "").lower().strip()
            ct = el.ControlTypeName or ""
            if ct == "GroupControl" and name_low == "transcript":
                rect = el.BoundingRectangle
                if _is_on_screen(rect) and rect.width() > 50 and rect.height() > 50:
                    cx = rect.left + rect.width() // 2
                    cy = rect.top + int(rect.height() * 0.6)
                    return (cx, cy)
            for ch in el.GetChildren():
                r = _find_panel(ch, depth + 1)
                if r:
                    return r
        except Exception:
            pass
        return None

    result = _find_panel(teams_window)
    if result:
        return result

    # Strategy 2: find "Search the transcript" edit control
    def _find_search(el, depth=0):
        if depth > TREE_DEPTH:
            return None
        try:
            name_low = (el.Name or "").lower().strip()
            ct = el.ControlTypeName or ""
            if "search" in name_low and "transcript" in name_low:
                rect = el.BoundingRectangle
                if _is_on_screen(rect):
                    return (rect.left + rect.width() // 2,
                            rect.top + rect.height() + 100)
            for ch in el.GetChildren():
                r = _find_search(ch, depth + 1)
                if r:
                    return r
        except Exception:
            pass
        return None

    result = _find_search(teams_window)
    if result:
        return result

    # Strategy 3: use the right 40% of the window, 60% down
    cx = screen_left + int((screen_right - screen_left) * 0.75)
    cy = screen_top + int((screen_bottom - screen_top) * 0.6)
    return (cx, cy)


def _win_dump_tree(element, depth=0, max_depth=DEBUG_TREE_DEPTH):
    if depth > max_depth:
        return
    try:
        name = element.Name or ""
        ct = element.ControlTypeName or ""
        aid = element.AutomationId or ""
        cls = element.ClassName or ""
        indent = "  " * depth
        print(f'{indent}[{ct}] Name="{name}"  AutoId="{aid}"  Class="{cls}"')
        for ch in element.GetChildren():
            _win_dump_tree(ch, depth + 1, max_depth)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  macOS IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════

def scrape_mac(debug: bool = False) -> Tuple[List[TranscriptEntry], str]:
    try:
        from AppKit import NSWorkspace                              # noqa: F401
        from ApplicationServices import (                           # noqa: F401
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXIsProcessTrusted,
            kAXErrorSuccess,
        )
    except ImportError:
        fail("Missing dependencies.  Run:\n"
             "  pip install pyobjc-framework-ApplicationServices "
             "pyobjc-framework-Cocoa pyobjc-framework-Quartz")

    if not AXIsProcessTrusted():
        fail("Accessibility permission required.\n"
             "   System Settings → Privacy & Security → Accessibility\n"
             "   Add your terminal app (Terminal / iTerm / Warp) to the list,\n"
             "   then re-run this script.")

    pid = _mac_find_teams_pid()
    if pid is None:
        fail("Microsoft Teams is not running.")

    print(f"📌  Found Teams (PID {pid})")
    app_ref = AXUIElementCreateApplication(pid)

    if debug:
        print(f"\n--- Accessibility tree (depth {DEBUG_TREE_DEPTH}) ---\n")
        _mac_dump_tree(app_ref, max_depth=DEBUG_TREE_DEPTH)
        return [], "Teams Meeting"

    items = _mac_walk_tree(app_ref)

    if _find_transcript_start(items) is None:
        fail("Transcript panel not detected.\n"
             "   Open a Teams meeting → click 'Transcript' to start or view it.")

    print("📋  Transcript panel detected")

    entries = parse_tree_items(items)
    title = _mac_get_window_title(app_ref) or "Teams Meeting"
    print(f"   ⤷ {len(entries)} entries in initial view")

    if entries:
        print("📜  Attempting scroll for additional entries…")
        more = _mac_scroll_and_collect(pid, entries)
        if more:
            entries = more

    return entries, title


def _mac_find_teams_pid() -> Optional[int]:
    from AppKit import NSWorkspace
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        name = (app.localizedName() or "").lower()
        bundle = (app.bundleIdentifier() or "").lower()
        if "teams" in name or "teams" in bundle:
            return app.processIdentifier()
    return None


def _mac_walk_tree(element, depth: int = 0,
                   max_depth: int = TREE_DEPTH) -> List[Tuple[int, str, str]]:
    """Walk macOS accessibility tree collecting (depth, role, name)."""
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        kAXErrorSuccess,
    )
    items: List[Tuple[int, str, str]] = []
    if depth > max_depth:
        return items

    role = ""
    err, val = AXUIElementCopyAttributeValue(element, "AXRole", None)
    if err == kAXErrorSuccess and val:
        role = str(val)

    name = ""
    for attr in ("AXTitle", "AXValue", "AXDescription"):
        err, val = AXUIElementCopyAttributeValue(element, attr, None)
        if err == kAXErrorSuccess and val and str(val).strip():
            name = str(val).strip()
            break

    if name:
        items.append((depth, role, name))

    err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
    if err == kAXErrorSuccess and children:
        for child in children:
            items.extend(_mac_walk_tree(child, depth + 1, max_depth))

    return items


def _mac_get_window_title(app_ref) -> Optional[str]:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        kAXErrorSuccess,
    )
    err, windows = AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
    if err == kAXErrorSuccess and windows:
        for w in windows:
            err, title = AXUIElementCopyAttributeValue(w, "AXTitle", None)
            if err == kAXErrorSuccess and title:
                t = str(title)
                if "teams" in t.lower():
                    return t.split(" | ")[0]
    return None


def _mac_scroll_and_collect(pid, initial_entries) -> Optional[List[TranscriptEntry]]:
    import subprocess
    from ApplicationServices import AXUIElementCreateApplication

    seen: set = set()
    all_entries = list(initial_entries)
    for e in initial_entries:
        seen.add(f"{e.speaker}|{e.timestamp}|{e.text[:50]}")

    stale = 0

    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "Microsoft Teams" to activate'],
            capture_output=True, timeout=5,
        )
        time.sleep(0.5)
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to key code 115'],
            capture_output=True, timeout=5,
        )
        time.sleep(SCROLL_PAUSE)
    except Exception:
        return None

    for i in range(MAX_SCROLLS):
        fresh = AXUIElementCreateApplication(pid)
        items = _mac_walk_tree(fresh)
        batch = parse_tree_items(items)

        new_count = 0
        for e in batch:
            key = f"{e.speaker}|{e.timestamp}|{e.text[:50]}"
            if key not in seen:
                seen.add(key)
                all_entries.append(e)
                new_count += 1

        if new_count == 0:
            stale += 1
            if stale >= STALE_SCROLL_LIMIT:
                break
        else:
            stale = 0

        if (i + 1) % 10 == 0:
            print(f"   ⤷ {len(all_entries)} entries so far…")

        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to key code 121'],
                capture_output=True, timeout=5,
            )
        except Exception:
            break
        time.sleep(SCROLL_PAUSE)

    if len(all_entries) > len(initial_entries):
        all_entries.sort(key=_ts_sort_key)
        return all_entries
    return None


def _mac_dump_tree(element, depth=0, max_depth=DEBUG_TREE_DEPTH):
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        kAXErrorSuccess,
    )
    if depth > max_depth:
        return

    role = title = desc = ""
    err, val = AXUIElementCopyAttributeValue(element, "AXRole", None)
    if err == kAXErrorSuccess and val:
        role = str(val)
    err, val = AXUIElementCopyAttributeValue(element, "AXTitle", None)
    if err == kAXErrorSuccess and val:
        title = str(val)
    err, val = AXUIElementCopyAttributeValue(element, "AXDescription", None)
    if err == kAXErrorSuccess and val:
        desc = str(val)

    indent = "  " * depth
    print(f'{indent}[{role}] Title="{title}"  Desc="{desc}"')

    err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
    if err == kAXErrorSuccess and children:
        for child in children:
            _mac_dump_tree(child, depth + 1, max_depth)


# ══════════════════════════════════════════════════════════════════
#  MARKDOWN FORMATTING
# ══════════════════════════════════════════════════════════════════

def to_markdown(entries: List[TranscriptEntry], title: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean = title.split(" | ")[0] if " | " in title else title

    lines = [
        f"# Transcript: {clean}",
        "",
        f"*Extracted on {now} — {len(entries)} entries*",
        "",
        "---",
        "",
    ]

    prev_speaker = None
    for entry in entries:
        if entry.speaker != prev_speaker:
            if prev_speaker is not None:
                lines.append("---")
                lines.append("")
            lines.append(f"**{entry.speaker}** *[{entry.timestamp}]*")
            prev_speaker = entry.speaker
        else:
            lines.append(f"*[{entry.timestamp}]*")
        lines.append("")
        lines.append(entry.text)
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Scrape an open MS Teams transcript to Markdown.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output .md file path (default: transcript_YYYYMMDD_HHMMSS.md)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Dump the Teams UI tree for troubleshooting, then exit.",
    )
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════╗")
    print("║   Teams Transcript Scraper           ║")
    print("╚══════════════════════════════════════╝")
    print()
    print(f"🖥   Platform: {SYSTEM}")
    print(f"🔍  Searching for Microsoft Teams…")
    print()

    if SYSTEM == "Windows":
        entries, title = scrape_windows(debug=args.debug)
    elif SYSTEM == "Darwin":
        entries, title = scrape_mac(debug=args.debug)
    else:
        fail(f"Unsupported platform: {SYSTEM}\n"
             "   This tool supports Windows and macOS only.")

    if args.debug:
        print("\n✅  Debug dump complete.  No transcript saved.")
        return

    if not entries:
        fail("No transcript entries found.\n"
             "   Try running with --debug to inspect the UI tree.")

    output_path = args.output or f"transcript_{datetime.now():%Y%m%d_%H%M%S}.md"
    md = to_markdown(entries, title)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    print()
    print(f"✅  Saved {len(entries)} entries → {output_path}")
    print()


if __name__ == "__main__":
    main()
