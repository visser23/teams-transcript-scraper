import unittest

from scrape_transcript import (
    TranscriptEntry,
    _mac_clean_window_title,
    parse_mac_clipboard_text,
)


class MacClipboardParserTests(unittest.TestCase):
    def test_extracts_meeting_name_from_current_mac_window_title(self):
        self.assertEqual(
            _mac_clean_window_title(
                "Chat | Product Alpha Assessment | Example Tenant | "
                "person@example.com | Microsoft Teams"
            ),
            "Product Alpha Assessment",
        )

    def test_parses_copied_teams_transcript_without_speaker_artifacts(self):
        copied = """
Transcript. Use arrow keys to navigate between transcript entries.
AS
SMITH, Alex
0 minutes 4 seconds0:04
SMITH, Alex 0 minutes 4 seconds
Mhm.
SJ
JONES, Sam
0 minutes 36 seconds0:36
JONES, Sam 0 minutes 36 seconds
Ongoing growth of the proposition.
"""

        self.assertEqual(
            parse_mac_clipboard_text(copied),
            [
                TranscriptEntry(
                    "SMITH, Alex", "0:04", "Mhm."
                ),
                TranscriptEntry(
                    "JONES, Sam",
                    "0:36",
                    "Ongoing growth of the proposition.",
                ),
            ],
        )

    def test_requires_transcript_marker(self):
        self.assertEqual(
            parse_mac_clipboard_text(
                "SPEAKER 1 minute 2 seconds\nThis is unrelated text."
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
