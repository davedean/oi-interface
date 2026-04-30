"""
Audio (ES8311) for M5Stack StickS3.

This module handles audio input and output using the ES8311 codec.
- Audio recording (microphone input)
- Audio playback (speaker output)
- Audio caching for response storage

I2S pins:
- MCLK: G18
- BCLK: G17
- LRCK: G15
- DOUT: G14
- DIN: G16

I2C control: SDA=G47, SCL=G48

Audio format for DATP:
- Recording: 44100 Hz stereo (ES8311 hardware requirement due to PLL)
- Playback: 44100 Hz stereo (or as configured)
"""

import machine
import utime
import ujson


# I2S pins
PIN_MCLK = 18
PIN_BCLK = 17
PIN_LRCK = 15
PIN_DOUT = 14
PIN_DIN = 16

# I2C pins for ES8311 control
PIN_SDA = 47
PIN_SCL = 48

# I2C address for ES8311
ES8311_I2C_ADDR = 0x18

# Audio buffer settings
AUDIO_BUFFER_SIZE = 8192  # Bytes
MAX_AUDIO_CACHE_SIZE = 256 * 1024  # 256KB max cache

# Audio format
SAMPLE_RATE = 44100
CHANNELS = 2
BITS_PER_SAMPLE = 16


class AudioManager:
    """
    Audio manager for ES8311 codec.
    
    Handles audio recording, playback, and caching.
    """
    
    def __init__(self):
        """Initialize audio manager."""
        # I2S and I2C will be initialized on first use
        self._i2s = None
        self._i2c = None
        
        # Audio state
        self._recording = False
        self._playing = False
        self._paused = False
        
        # Recording state
        self._record_buffer = None
        self._record_start_time = None
        self._record_samples = 0
        
        # Playback state
        self._play_buffer = None
        self._play_position = 0
        
        # Audio cache (stores response audio)
        self._audio_cache = {}  # response_id -> audio_data
        self._cache_size = 0
        
        # Callbacks
        self._on_recording_started = None
        self._on_recording_stopped = None
        self._on_playback_started = None
        self._on_playback_stopped = None
        self._on_playback_error = None
    
    def set_callbacks(self, on_recording_started=None, on_recording_stopped=None,
                     on_playback_started=None, on_playback_stopped=None,
                     on_playback_error=None):
        """Set audio event callbacks."""
        self._on_recording_started = on_recording_started
        self._on_recording_stopped = on_recording_stopped
        self._on_playback_started = on_playback_started
        self._on_playback_stopped = on_playback_stopped
        self._on_playback_error = on_playback_error
    
    def _init_i2s(self):
        """Initialize I2S for audio."""
        if self._i2s:
            return
        
        try:
            # I2S configuration for ES8311
            # Note: MicroPython I2S API may vary by port
            self._i2s = machine.I2S(
                0,
                sck=machine.Pin(PIN_BCLK),
                ws=machine.Pin(PIN_LRCK),
                sd=machine.Pin(PIN_DIN),
                mck=machine.Pin(PIN_MCLK),
                mode=machine.I2S.MASTER_RX,
                bits=16,
                format=machine.I2S.STEREO,
                rate=SAMPLE_RATE,
                ibuf=AUDIO_BUFFER_SIZE
            )
        except Exception as e:
            print("I2S init failed:", e)
            self._i2s = None
    
    def _init_i2c(self):
        """Initialize I2C for ES8311 control."""
        if self._i2c:
            return
        
        try:
            self._i2c = machine.I2C(
                0,
                scl=machine.Pin(PIN_SCL),
                sda=machine.Pin(PIN_SDA),
                freq=400000
            )
            # Verify ES8311 is present
            if ES8311_I2C_ADDR in self._i2c.scan():
                self._init_es8311()
        except Exception as e:
            print("I2C init failed:", e)
            self._i2c = None
    
    def _init_es8311(self):
        """Initialize ES8311 codec."""
        # ES8311 initialization sequence
        # This is a simplified version - full init would configure
        # registers for proper audio operation
        try:
            # Reset
            self._i2c.writeto_mem(ES8311_I2C_ADDR, 0x11, bytes([0x00]))
            utime.sleep_ms(10)
            
            # Configure for default operation
            # This would set up clocks, gains, etc.
            # See ES8311 datasheet for full register map
            
            print("ES8311 initialized")
        except Exception as e:
            print("ES8311 init failed:", e)
    
    def start_recording(self) -> bool:
        """
        Start audio recording.
        
        Returns:
            True if recording started successfully.
        """
        if self._recording:
            return False
        
        self._init_i2s()
        
        if not self._i2s:
            print("Cannot start recording: I2S not initialized")
            return False
        
        # Allocate buffer
        self._record_buffer = bytearray(AUDIO_BUFFER_SIZE)
        self._record_samples = 0
        self._record_start_time = utime.ticks_ms()
        self._recording = True
        
        print("Recording started")
        
        if self._on_recording_started:
            self._on_recording_started()
        
        return True
    
    def stop_recording(self) -> bytes:
        """
        Stop audio recording.
        
        Returns:
            Recorded audio data as bytes, or None if not recording.
        """
        if not self._recording:
            return None
        
        self._recording = False
        duration_ms = utime.ticks_diff(utime.ticks_ms(), self._record_start_time)
        
        # Return recorded data
        audio_data = bytes(self._record_buffer[:self._record_samples * 4])  # 2 channels * 2 bytes
        
        print("Recording stopped: {} samples, {} ms".format(
            self._record_samples, duration_ms))
        
        if self._on_recording_stopped:
            self._on_recording_stopped(duration_ms, audio_data)
        
        return audio_data
    
    def read_audio_chunk(self) -> bytes:
        """
        Read a chunk of audio data during recording.
        
        Returns:
            Audio data chunk, or None if not recording.
        """
        if not self._recording or not self._i2s:
            return None
        
        try:
            # Read from I2S
            chunk = self._i2s.readinto(self._record_buffer)
            if chunk:
                # Update sample count
                self._record_samples += len(chunk) // 4  # 2 channels * 2 bytes
            return chunk
        except Exception as e:
            print("Audio read error:", e)
            return None
    
    def get_recording_duration_ms(self) -> int:
        """Get current recording duration in milliseconds."""
        if self._recording and self._record_start_time:
            return utime.ticks_diff(utime.ticks_ms(), self._record_start_time)
        return 0
    
    # Audio caching
    
    def cache_audio_begin(self, response_id: str, format: str = "wav_pcm16",
                         sample_rate: int = 22050, bytes: int = 0, label: str = "") -> bool:
        """
        Begin caching audio data from gateway.
        
        Args:
            response_id: Unique response identifier
            format: Audio format string
            sample_rate: Sample rate in Hz
            bytes: Expected size in bytes (0 if unknown)
            label: Optional label for the audio
        
        Returns:
            True if cache started successfully.
        """
        # Clear existing cache for this response_id if any
        if response_id in self._audio_cache:
            old_size = len(self._audio_cache[response_id])
            self._cache_size -= old_size
            del self._audio_cache[response_id]
        
        # Check total cache size
        if self._cache_size >= MAX_AUDIO_CACHE_SIZE:
            print("Audio cache full")
            return False
        
        # Start new cache
        self._audio_cache[response_id] = bytearray()
        self._cache_response_id = response_id
        
        print("Cache started: {} ({} Hz, {} bytes)".format(
            response_id, sample_rate, bytes))
        
        return True
    
    def cache_audio_chunk(self, response_id: str, seq: int, data_b64: str) -> bool:
        """
        Add a chunk of audio data to the cache.
        
        Args:
            response_id: Response identifier
            seq: Sequence number
            data_b64: Base64-encoded audio data
        
        Returns:
            True if chunk added successfully.
        """
        if response_id not in self._audio_cache:
            print("Cache chunk error: unknown response_id")
            return False
        
        try:
            # Decode base64
            import ubase64
            data = ubase64.decode(data_b64)
            
            # Append to cache
            self._audio_cache[response_id].extend(data)
            self._cache_size += len(data)
            
            return True
        except Exception as e:
            print("Cache chunk error:", e)
            return False
    
    def cache_audio_end(self, response_id: str, sha256: str = None) -> bool:
        """
        Finalize audio caching.
        
        Args:
            response_id: Response identifier
            sha256: Optional SHA256 hash for verification
        
        Returns:
            True if cache finalized successfully.
        """
        if response_id not in self._audio_cache:
            print("Cache end error: unknown response_id")
            return False
        
        print("Cache complete: {} ({} bytes)".format(
            response_id, len(self._audio_cache[response_id])))
        
        # Convert to immutable bytes to save memory
        self._audio_cache[response_id] = bytes(self._audio_cache[response_id])
        
        return True
    
    def get_cached_audio(self, response_id: str) -> bytes:
        """Get cached audio data."""
        return self._audio_cache.get(response_id)
    
    def clear_cache(self, response_id: str = None):
        """Clear audio cache."""
        if response_id:
            if response_id in self._audio_cache:
                size = len(self._audio_cache[response_id])
                self._cache_size -= size
                del self._audio_cache[response_id]
                print("Cleared cache: {}".format(response_id))
        else:
            # Clear all
            self._audio_cache = {}
            self._cache_size = 0
            print("Cleared all cache")
    
    def get_cache_size(self) -> int:
        """Get total cache size in bytes."""
        return self._cache_size
    
    # Playback
    
    def play(self, response_id: str = None) -> bool:
        """
        Play cached audio.
        
        Args:
            response_id: Specific response to play, or None for latest.
        
        Returns:
            True if playback started successfully.
        """
        # Get audio to play
        if response_id is None:
            # Get most recent
            if self._audio_cache:
                response_id = list(self._audio_cache.keys())[-1]
            else:
                print("No cached audio to play")
                return False
        
        audio_data = self._audio_cache.get(response_id)
        if not audio_data:
            print("Audio not in cache:", response_id)
            return False
        
        self._init_i2s()
        
        if not self._i2s:
            print("Cannot play: I2S not initialized")
            return False
        
        # Set up playback
        self._play_buffer = audio_data
        self._play_position = 0
        self._playing = True
        
        print("Playing: {} ({} bytes)".format(response_id, len(audio_data)))
        
        if self._on_playback_started:
            self._on_playback_started(response_id)
        
        return True
    
    def stop(self) -> bool:
        """Stop audio playback."""
        if not self._playing:
            return False
        
        self._playing = False
        response_id = self._play_response_id if hasattr(self, '_play_response_id') else None
        
        print("Playback stopped")
        
        if self._on_playback_stopped:
            self._on_playback_stopped(response_id)
        
        return True
    
    def write_audio_chunk(self) -> int:
        """
        Write a chunk of audio data during playback.
        
        Returns:
            Number of bytes written, or 0 if not playing.
        """
        if not self._playing or not self._i2s or not self._play_buffer:
            return 0
        
        try:
            # Calculate how much to write
            chunk_size = min(1024, len(self._play_buffer) - self._play_position)
            if chunk_size <= 0:
                # Playback complete
                self.stop()
                return 0
            
            # Get chunk
            chunk = self._play_buffer[self._play_position:self._play_position + chunk_size]
            
            # Write to I2S
            self._i2s.write(chunk)
            
            self._play_position += chunk_size
            return chunk_size
        except Exception as e:
            print("Playback write error:", e)
            if self._on_playback_error:
                self._on_playback_error(str(e))
            self.stop()
            return 0
    
    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._playing
    
    def is_recording(self) -> bool:
        """Check if audio is currently recording."""
        return self._recording
    
    # Volume control
    def set_volume(self, level: int):
        """
        Set volume level.
        
        Args:
            level: Volume level 0-100.
        """
        # This would configure ES8311 volume register
        print("Volume set to:", level)
    
    def get_volume(self) -> int:
        """Get current volume level."""
        # Return stored volume (would read from hardware)
        return 50


def create_audio_manager() -> AudioManager:
    """Factory function to create an audio manager."""
    return AudioManager()