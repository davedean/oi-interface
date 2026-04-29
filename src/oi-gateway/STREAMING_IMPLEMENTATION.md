# Streaming Output Implementation

## Overview

This document describes the changes made to add streaming output support to the oi-gateway.
The implementation allows agent backends to stream text responses incrementally rather than
returning complete responses in a single round-trip.

## Changes Made

### 1. Core Contracts (`src/channel/backend.py`)

Added new data types and protocol:

- **`AgentStreamChunk`**: Represents a chunk of streaming text
  - `text_delta`: The incremental text
  - `is_final`: Whether this is the final chunk
  - `metadata`: Additional context

- **`StreamingAgentBackend`**: Optional protocol for backends that support streaming
  - `send_request_streaming(request) -> AsyncGenerator[AgentStreamChunk, None]`

**Key Design Decision**: This is an *optional* protocol layered on top of the
existing `AgentBackend` protocol. Backends can remain non-streaming and continue
to work with the existing interface.

### 2. Pi Backend (`src/channel/pi_backend.py`)

- **Added `AsyncGenerator` import** and `AgentStreamChunk` import
- **Refactored `SubprocessPiBackend`**:
  - Extracted event-reading loop into async generator `_read_events_from_prompt()`
  - Yields `AgentStreamChunk` for each `text_delta` event from pi subprocess
  - Maintains backward compatibility: `send_prompt()` still returns final text
  - Added `send_request_streaming()`: streams chunks as they arrive
- **Added `send_request_streaming()` to `StubPiBackend`**:
  - Returns fixed response as a single chunk (for testing)

**How it works**:
The pi subprocess already emits JSON events over stdout including:
- `text_delta`: Incremental text
- `text_start`: Beginning of text
- `text_end`: End of text
- `agent_end`: Final response

The generator reads these events and yields chunks immediately, enabling
real-time display of agent responses.

### 3. Hermes Backend (`src/channel/hermes_backend.py`)

- **Added streaming support** via `send_request_streaming()`:
  - Uses OpenAI-compatible SSE (Server-Sent Events) streaming: `stream=True`
  - Parses `data:` lines, extracts `delta.content` from each chunk
  - Yields incremental text chunks as they arrive
  - Falls back to non-streaming for mock/test responses (no `.content` attribute)
- **Refactored `send_request()`**:
  - Now accumulates streaming chunks and returns final response
  - Maintains same API for callers
- **Restored helper methods**: `_map_session_key`, `_extract_response_text`, `_extract_text_content`
- **Added `Idempotency-Key` header** (was missing in refactoring)

**How it works**:
When `stream=True` is set in the OpenAI API request, responses come as an
SSE stream. Each chunk contains `choices[0].delta.content`. These deltas are
accumulated and yielded as `AgentStreamChunk` objects.

### 4. OpenClaw Backend (`src/channel/openclaw_backend.py`)

- **Added streaming support**: `send_request_streaming()`
- **Handles interleaved events**: OpenClaw already sends `event` type frames
  during agent requests (currently ignored). These can contain text updates.
- **Extracts text from event payloads**: New `_extract_text_from_openclaw_payload()`
  method parses common text fields
- **Refactored `send_request()`**: Now accumulates streaming chunks
- **Added `AsyncGenerator` import** and `AgentStreamChunk` import

**How it works**:
OpenClaw's WebSocket protocol sends interleaved `event` frames during agent
requests. The streaming method captures these, extracts text, and yields
chunks. Final response comes in a `res` (response) frame.

### 5. Channel Service (`src/channel/service.py`)

- **Added streaming-aware dispatch**: `_send_backend_request()`
  - Checks for `send_request_streaming` capability first
  - Falls back to `send_request` or `send_prompt` for non-streaming backends
- **New `_handle_streaming_request()` method**:
  - Iterates over streaming chunks
  - Emits `agent_response_delta` events to EventBus for each chunk
  - Accumulates final text and returns `AgentResponse`
- **Preserves existing behavior**: Non-streaming backends work unchanged

**Event flow with streaming**:
```
transcript/event → ChannelService → backend.send_request_streaming()
  ↓
  For each chunk:
    ↓
  emit "agent_response_delta" (device_id, {text_delta, is_final, ...})
  ↓
  Final chunk:
    ↓
  emit "agent_response" (device_id, {response_text, ...})
```

## Device Display (Client-Side)

Devices can now receive real-time text updates through the existing DATP
event system:

1. **Agent response deltas**: `agent_response_delta` events (internal EventBus)
2. **DATP events**: Can be forwarded as `agent.text_delta` events to devices
3. **Display**: Any device listening for these events can append text incrementally

This gives the "*cool as shit*" streaming text display on devices ✨

## Backward Compatibility

**✅ All existing code continues to work**:

- Non-streaming backends implement only `AgentBackend` (unchanged)
- Existing callers use `send_request()` (unchanged)
- Tests pass without modification (588 passed, 71 skipped)
- All existing behavior preserved

**✅ No breaking changes**:

- No DATP protocol changes
- No API endpoint changes
- No database schema changes
- No configuration changes

**✅ Gradual adoption**:

- Backends opt-in to streaming by implementing `send_request_streaming()`
- ChannelService automatically uses streaming when available
- Same `AgentResponse` returned regardless of streaming path

## Testing

All existing tests pass:
- `test_channel.py`: 37 passed (including subprocess backend tests)
- `test_hermes_backend.py`: 3 passed
- `test_openclaw_backend.py`: 8 passed
- `test_backend_factory.py`: 19 passed
- `test_channel_request_builder.py`: 11 passed
- Full suite: 588 passed, 71 skipped

## Benefits

1. **Lower perceived latency**: Users see text appearing incrementally
2. **Better UX**: Real-time feedback during agent responses
3. **Extensible**: New backends can add streaming support without changes to gateway
4. **Optional**: Backends without streaming capability continue to work
5. **No audio complexity**: Text streaming only (TTS remains full-response)

## Future Enhancements

Possible additions (not implemented yet):

- **Streaming audio TTS**: Would require sentence boundary detection
- **DATP `agent.text_delta` command**: Formalize text streaming to devices
- **Progress indicators**: Typing indicators during streaming
- **Interruption handling**: Cancel streaming on new user input
- **Rate limiting**: Throttle delta events if too frequent

## Architecture Diagram

```

  Device    

       transcript/event
       

  ChannelService                  
  - Detects streaming capability   
  - Handles both paths             

       streaming? yes
       

  Backend                         
  - Pi: parse subprocess events   
  - Hermes: parse SSE stream      
  - OpenClaw: parse event frames  

       AgentStreamChunk (delta)
       

  ChannelService                  
  - Emits agent_response_delta    
  - Accumulates final text        

       agent_response (final)
       

  AudioDelivery/TTS               
  - Full text processing          

```

## Key Files Modified

1. `src/channel/backend.py` - Added `AgentStreamChunk`, `StreamingAgentBackend`
2. `src/channel/pi_backend.py` - Refactored streaming support
3. `src/channel/hermes_backend.py` - Added SSE streaming
4. `src/channel/openclaw_backend.py` - Added event-based streaming
5. `src/channel/service.py` - Added streaming dispatch

## Summary

The implementation adds streaming text output to all three agent backends
(Pi, Hermes, OpenClaw) while maintaining full backward compatibility.
The optional `StreamingAgentBackend` protocol allows gradual adoption,
and the existing EventBus infrastructure enables real-time text display
on devices without any DATP protocol changes.
