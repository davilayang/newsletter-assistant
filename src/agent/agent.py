# src/agent/agent.py
# LiveKit voice agent — agent definition and session wiring.

from textwrap import dedent

from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    inference,
    room_io,
)
from livekit.plugins import silero

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

server = AgentServer()


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
        )


@server.rtc_session()
async def session(ctx: JobContext):
    agent_session = AgentSession(
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts=inference.TTS(
            model="inworld/inworld-tts-1",
            voice="Olivia",
        ),
        vad=silero.VAD.load(),
    )

    await agent_session.start(
        room=ctx.room,
        agent=NewsletterAssistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(),
        ),
    )

    await agent_session.generate_reply(
        instructions="Greet the user warmly and offer to load their newsletter."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
