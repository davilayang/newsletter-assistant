# src/frontend/livekit_widget.py
# LiveKit audio widget — HTML structure and JavaScript logic.
#
# NiceGUI 3.x forbids <script> tags inside ui.html().
# The two constants are used separately:
#   _AUDIO_WIDGET_HTML  → ui.html(..., sanitize=False)
#   _AUDIO_WIDGET_JS    → ui.add_body_html(...)

# The visible controls — no script tags allowed here.
_AUDIO_WIDGET_HTML = """
<div style="display:flex; flex-direction:column; gap:8px;">
  <span id="lk-status" style="font-size:0.85rem; color:#888;">Disconnected</span>
  <div style="display:flex; gap:8px; flex-wrap:wrap;">
    <button id="lk-connect"    onclick="lkConnect()">Connect</button>
    <button id="lk-mute"       onclick="lkToggleMute()" disabled>Mute</button>
    <button id="lk-disconnect" onclick="lkDisconnect()" disabled>Disconnect</button>
  </div>
  <div id="lk-interim" style="font-size:0.85rem; color:#888; font-style:italic; min-height:1.2em;"></div>
</div>
"""

# Script tags injected into <body> via ui.add_body_html() once per page load.
_AUDIO_WIDGET_JS = """
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/dist/livekit-client.umd.min.js"></script>
<script>
const { Room, RoomEvent, Track, createLocalAudioTrack } = LivekitClient;

let _room = null;
let _micTrack = null;

function lkSetStatus(msg) {
  document.getElementById('lk-status').textContent = msg;
}

function lkSetButtons(connected) {
  document.getElementById('lk-connect').disabled    = connected;
  document.getElementById('lk-mute').disabled       = !connected;
  document.getElementById('lk-disconnect').disabled = !connected;
}

async function lkConnect() {
  lkSetStatus('Connecting\u2026');
  try {
    const { token, url } = await fetch('/token').then(r => r.json());
    if (!token) throw new Error('No token returned \u2014 check server logs.');

    _room = new Room();

    // Attach any audio track published by a remote participant (the agent).
    _room.on(RoomEvent.TrackSubscribed, (track, _publication, _participant) => {
      if (track.kind === Track.Kind.Audio) {
        track.attach();   // creates an <audio> element and appends it to <body>
      }
    });

    _room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
      const role = participant?.isAgent ? 'assistant' : 'user';
      for (const seg of segments) {
        if (!seg.final) {
          // Show interim text immediately in the widget — no Python roundtrip.
          document.getElementById('lk-interim').textContent = seg.text;
        } else {
          // Final: clear interim display and push to Python over NiceGUI WebSocket.
          document.getElementById('lk-interim').textContent = '';
          emitEvent('transcript', { role, text: seg.text });
        }
      }
    });

    _room.on(RoomEvent.Disconnected, () => {
      lkSetStatus('Disconnected');
      lkSetButtons(false);
      emitEvent('lk_status', { connected: false });
      _room = null;
      _micTrack = null;
    });

    await _room.connect(url, token);
    _micTrack = await createLocalAudioTrack();
    await _room.localParticipant.publishTrack(_micTrack);

    lkSetStatus('Connected \u2014 mic active');
    lkSetButtons(true);
    emitEvent('lk_status', { connected: true });
  } catch (err) {
    lkSetStatus('Error: ' + err.message);
    console.error(err);
  }
}

async function lkToggleMute() {
  if (!_micTrack) return;
  if (_micTrack.isMuted) {
    await _micTrack.unmute();
    document.getElementById('lk-mute').textContent = 'Mute';
    lkSetStatus('Connected \u2014 mic active');
  } else {
    await _micTrack.mute();
    document.getElementById('lk-mute').textContent = 'Unmute';
    lkSetStatus('Connected \u2014 mic muted');
  }
}

async function lkDisconnect() {
  if (_room) await _room.disconnect();
}

// Called from NiceGUI's ui.run_javascript() for typed input (Phase 2).
async function sendText(text) {
  if (!_room) { alert('Connect to a session first.'); return; }
  const payload = JSON.stringify({ type: 'user_text', text });
  await _room.localParticipant.publishData(
    new TextEncoder().encode(payload),
    { reliable: true }
  );
  emitEvent('transcript', { role: 'user', text });
}
</script>
"""
