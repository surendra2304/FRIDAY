"""Web Application Operating Templates and Navigation Rules Registry.

Adapted from Jarvis webapp-templates to provide deterministic rules, element locators,
keyboard shortcuts, URL patterns, and safety boundaries for web interactions in FRIDAY.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Optional

from friday.core.logging import get_logger

logger = get_logger("integrations.webapp_templates")


@dataclass
class WebAppTemplate:
    """Operational template containing deterministic interaction rules for a webapp."""

    app_name: str
    domains: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    version: int = 1
    url: str = ""
    rules: list[str] = field(default_factory=list)
    url_patterns: dict[str, str] = field(default_factory=dict)
    instructions: str = ""

    def matches_url(self, url: str) -> bool:
        """Check if this template applies to the given URL or domain."""
        u = url.lower()
        return any(d.lower() in u for d in self.domains)

    def matches_query(self, query: str) -> bool:
        """Check if this template matches a natural language query or app name."""
        q = query.lower().strip()
        if self.app_name.lower() in q:
            return True
        if any(k.lower() in q for k in self.keywords):
            return True
        if any(d.lower() in q for d in self.domains):
            return True
        return False


# Built-in seed templates for top productivity webapps
SEED_TEMPLATES: list[WebAppTemplate] = [
    WebAppTemplate(
        app_name="WhatsApp",
        domains=["web.whatsapp.com", "whatsapp.com"],
        keywords=["whatsapp", "send whatsapp", "text on whatsapp", "wa message"],
        description="WhatsApp Web messaging — send/read messages, search contacts, send media, chat history",
        url="https://web.whatsapp.com",
        rules=[
            "Two-panel layout: Left panel holds the chat list (role='gridcell'), right panel holds the conversation.",
            "To send a text message: Click message input (role='textbox', contenteditable='true'), type message with Enter to send.",
            "Verify send: Check that the message text appears in the conversation list with single grey (sent) or double checkmark.",
            "Dismiss phone error modals ('The number isn't on WhatsApp') cleanly by clicking OK button.",
            "Max tool calls for sending a message: 5-7. Do not hunt for buttons if Enter submits.",
        ],
        url_patterns={
            "direct_send": "https://web.whatsapp.com/send?phone={phone}&text={message}",
            "home": "https://web.whatsapp.com",
        },
        instructions=(
            "1. Open WhatsApp Web. If unauthenticated, prompt user to scan the QR code.\n"
            "2. Search contact: click search input 'Search or start a new chat', type name, select chat.\n"
            "3. Send message: click textbox at bottom, type text and press Enter.\n"
            "4. For attachments: click '+' attach button, select document or photo."
        ),
    ),
    WebAppTemplate(
        app_name="Gmail",
        domains=["mail.google.com"],
        keywords=["gmail", "send email", "read email", "inbox", "compose email", "check email"],
        description="Gmail — compose, reply, forward, search, labels, attachments, and inbox management",
        url="https://mail.google.com",
        rules=[
            "Top search bar: input with name='q'. Use standard Gmail query syntax: is:unread, from:user@domain, label:important.",
            "Compose button: role='button' with text 'Compose'.",
            "Send button: role='button' whose aria-label contains '(Ctrl-Enter)'. Use Ctrl+Enter shortcut to send cleanly.",
            "Preserve thread: when replying/forwarding, append to field rather than overwriting.",
            "Press 'Escape' to abort compose without sending (auto-saved to drafts).",
        ],
        url_patterns={
            "inbox": "https://mail.google.com/mail/u/0/#inbox",
            "search": "https://mail.google.com/mail/u/0/#search/{query}",
            "sent": "https://mail.google.com/mail/u/0/#sent",
            "drafts": "https://mail.google.com/mail/u/0/#drafts",
        },
        instructions=(
            "1. Navigate to https://mail.google.com.\n"
            "2. To search: fill search box 'q' with query and press Enter.\n"
            "3. To compose: click Compose button, fill recipient 'to', subject 'subjectbox', and message body.\n"
            "4. Send with Ctrl+Enter or click Send button."
        ),
    ),
    WebAppTemplate(
        app_name="GitHub",
        domains=["github.com"],
        keywords=["github", "pull request", "pr", "repo", "issue", "commit", "merge pr"],
        description="GitHub — read repositories, search code/issues, file issues, comment, review and merge PRs",
        url="https://github.com",
        rules=[
            "URL-first: GitHub URLs are deep-linkable. Prefer direct URLs over clicking through menus.",
            "Search qualifier syntax: type=repositories, is:open, is:pr, author:username, label:bug.",
            "Outward actions (merge PR, close issue, post comment): verify current repo and PR number before submitting.",
            "Never type credentials or 2FA codes into the browser.",
        ],
        url_patterns={
            "repo": "https://github.com/{owner}/{repo}",
            "issues": "https://github.com/{owner}/{repo}/issues",
            "pulls": "https://github.com/{owner}/{repo}/pulls",
            "search": "https://github.com/search?q={query}",
            "notifications": "https://github.com/notifications",
        },
        instructions=(
            "1. Navigate directly to repo URL: https://github.com/{owner}/{repo}.\n"
            "2. Read issues: navigate to /issues or filter by label.\n"
            "3. Create issue: navigate to /issues/new, fill Title and Body, click Submit new issue.\n"
            "4. Review PR diff: navigate to /pull/{n}/files."
        ),
    ),
    WebAppTemplate(
        app_name="YouTube",
        domains=["youtube.com", "youtu.be"],
        keywords=["youtube", "play video", "watch youtube", "search youtube"],
        description="YouTube — search videos, play tracks, control playback, playlists",
        url="https://www.youtube.com",
        rules=[
            "Search input: input element with name='search_query' or id='search'.",
            "Direct play shortcut: https://www.youtube.com/results?search_query={query}",
            "Playback shortcuts: Space or 'k' = play/pause, 'f' = fullscreen, 'm' = mute, Left/Right arrow = seek 5s.",
        ],
        url_patterns={
            "search": "https://www.youtube.com/results?search_query={query}",
            "watch": "https://www.youtube.com/watch?v={video_id}",
            "home": "https://www.youtube.com",
        },
        instructions=(
            "1. Search query: navigate to https://www.youtube.com/results?search_query={encoded_query}.\n"
            "2. Click the first video title link (role='link' with ytd-video-renderer).\n"
            "3. Control playback with spacebar or 'k'."
        ),
    ),
    WebAppTemplate(
        app_name="Spotify",
        domains=["spotify.com", "open.spotify.com"],
        keywords=["spotify", "play music", "stream track", "playlist"],
        description="Spotify Web Player — search tracks, play albums, podcasts, media controls",
        url="https://open.spotify.com",
        rules=[
            "Playback requires authenticated web session or Spotify desktop app.",
            "Shortcuts: Space = play/pause, Ctrl+Right = next track, Ctrl+Left = previous track.",
        ],
        url_patterns={
            "search": "https://open.spotify.com/search/{query}",
            "track": "https://open.spotify.com/track/{track_id}",
            "home": "https://open.spotify.com",
        },
        instructions=(
            "1. Open Spotify web player or launch local desktop Spotify app.\n"
            "2. Search track or artist via https://open.spotify.com/search/{query}.\n"
            "3. Click Play button on matching track or album."
        ),
    ),
    WebAppTemplate(
        app_name="Notion",
        domains=["notion.so"],
        keywords=["notion", "notes", "workspace", "notion page", "database"],
        description="Notion workspace — notes, docs, task boards, relational databases",
        url="https://www.notion.so",
        rules=[
            "Quick Search: Ctrl+P or Cmd+P opens Notion global search.",
            "New page: Ctrl+N or Cmd+N creates a new document.",
            "Slash commands: '/' inside any line opens block insertion menu.",
        ],
        url_patterns={
            "home": "https://www.notion.so",
        },
        instructions=(
            "1. Navigate to Notion workspace.\n"
            "2. Use Ctrl+P to quickly search and switch pages.\n"
            "3. Edit blocks by clicking into them and typing."
        ),
    ),
    WebAppTemplate(
        app_name="Google Docs",
        domains=["docs.google.com"],
        keywords=["google docs", "gdocs", "document", "write doc"],
        description="Google Docs — word processing, collaborative document editing",
        url="https://docs.google.com",
        rules=[
            "New document instant shortcut: https://doc.new",
            "Content editing: Google Docs canvas uses custom rendering; prefer standard clipboard paste or direct typing.",
        ],
        url_patterns={
            "new": "https://doc.new",
            "home": "https://docs.google.com",
        },
        instructions=(
            "1. Open https://doc.new to immediately create a new document.\n"
            "2. Type or paste content into the document canvas."
        ),
    ),
]


class WebAppTemplateRegistry:
    """Registry that manages and retrieves web application operating templates."""

    def __init__(self) -> None:
        self._templates: dict[str, WebAppTemplate] = {}
        for tmpl in SEED_TEMPLATES:
            self.register(tmpl)

    def register(self, template: WebAppTemplate) -> None:
        """Register a template by its canonical lowercased app name."""
        self._templates[template.app_name.lower().strip()] = template

    def get_template(self, app_name: str) -> Optional[WebAppTemplate]:
        """Get template by exact name or closest alias."""
        key = app_name.lower().strip()
        if key in self._templates:
            return self._templates[key]
        matches = difflib.get_close_matches(key, self._templates.keys(), n=1, cutoff=0.6)
        if matches:
            return self._templates[matches[0]]
        return None

    def find_by_url(self, url: str) -> Optional[WebAppTemplate]:
        """Find template matching a URL or domain."""
        for tmpl in self._templates.values():
            if tmpl.matches_url(url):
                return tmpl
        return None

    def find_by_query(self, query: str) -> Optional[WebAppTemplate]:
        """Find template matching user query or task description."""
        for tmpl in self._templates.values():
            if tmpl.matches_query(query):
                return tmpl
        return None

    def list_templates(self) -> list[dict[str, Any]]:
        """List summary of all registered templates."""
        return [
            {
                "app_name": t.app_name,
                "domains": t.domains,
                "keywords": t.keywords,
                "description": t.description,
                "url": t.url,
            }
            for t in self._templates.values()
        ]


# Singleton instance
webapp_templates = WebAppTemplateRegistry()
