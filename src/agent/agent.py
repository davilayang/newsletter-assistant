# src/agent/agent.py
# LiveKit voice agent — agent definition and session wiring.

import re

from pathlib import Path
from textwrap import dedent
from typing import AsyncIterable

import yaml

from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    ModelSettings,
    inference,
    room_io,
)
from livekit.plugins import silero
from livekit.rtc import AudioFrame

# ---------------------------------------------------------------------------
# TTS text normalisation
# ---------------------------------------------------------------------------
_SPEECH_REPLACEMENTS_PATH = (
    Path(__file__).parents[2] / "config" / "speech_replacements.yaml"
)


def _load_speech_replacements() -> list[tuple[re.Pattern, str]]:
    """Load TTS normalisation rules from speech_replacements.yaml."""
    with _SPEECH_REPLACEMENTS_PATH.open() as f:
        entries = yaml.safe_load(f)
    return [(re.compile(e["pattern"]), e["replacement"]) for e in entries]


_SPEECH_REPLACEMENTS = _load_speech_replacements()


def _normalize_for_speech(text: str) -> str:
    for pattern, replacement in _SPEECH_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


from src.core.gmail.client import get_gmail_service

from .tools import (
    _NEWSLETTER_NAMES,
    get_todays_newsletter,
    read_article,
    save_note,
    search_knowledge,
)

# Validate Gmail auth at import time so the agent fails fast before any session starts.
# Pass interactive=False so a missing/expired token raises RuntimeError instead of
# blocking the process trying to open a browser.
get_gmail_service(interactive=False)

# Prewarm VAD once at process startup so the first session has no load lag.
server = AgentServer(userdata={"vad": silero.VAD.load()})  # type: ignore[call-arg]


class NewsletterAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=dedent(
                f"""\
                You are a personal reading assistant for email newsletters.
                Each morning you help the user review what arrived in their inbox.

                Available newsletters: {_NEWSLETTER_NAMES}.
                Default to "medium" if the user does not specify one.

                Style:
                - Speak naturally and conversationally. No markdown, bullet symbols,
                  asterisks, or emojis in your responses — you are speaking, not writing.
                - When summarising an article or newsletter, give the key insight in 2 to 3
                  sentences, then invite follow-up questions.
                - When saving a note, confirm exactly what was saved and to which file.
                - If the user wants to go deeper on any article, discuss it in detail.

                Start by greeting the user and offering to load their latest newsletter.
            """
            ),
            tools=[get_todays_newsletter, read_article, save_note, search_knowledge],
            allow_interruptions=True,
        )

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable[AudioFrame]:
        """Normalise text before synthesis to fix common TTS mispronunciations."""

        async def _normalised() -> AsyncIterable[str]:
            async for chunk in text:
                yield _normalize_for_speech(chunk)

        return Agent.default.tts_node(self, _normalised(), model_settings)


@server.rtc_session()
async def session(ctx: JobContext):
    agent_session: AgentSession = AgentSession(
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts=inference.TTS(
            model="inworld/inworld-tts-1",
            voice="Olivia",
        ),
        vad=ctx.userdata["vad"],  # type: ignore[attr-defined]
    )

    await agent_session.start(
        room=ctx.room,
        agent=NewsletterAssistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(),
        ),
    )

    await agent_session.generate_reply(
        instructions=dedent(
            "Greet the user warmly and offer to load their newsletter, "
            "also mention what kind of newsletters are available."
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
