# src/agent/agent.py
# LiveKit voice agent entry point

from livekit import agents
from livekit.agents import AgentServer, AgentSession, JobContext, inference, room_io
from livekit.plugins import silero

from src.core.gmail.client import get_gmail_service

from .tools import NewsletterAssistant

server = AgentServer()

# Validate Gmail auth at import time so the agent fails fast before any session starts.
# Pass interactive=False so a missing/expired token raises RuntimeError instead of
# blocking the process trying to open a browser.
get_gmail_service(interactive=False)


# @server.rtc_session(agent_name="newsletter-assistant")
@server.rtc_session()
async def session(ctx: JobContext):
    agent_session = AgentSession(
        stt="deepgram/nova-3",
        # llm="anthropic/claude-sonnet-4-6",
        # tts="elevenlabs/eleven_flash_v2_5",
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
        instructions="Greet the user warmly and offer to load their Medium newsletter."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
