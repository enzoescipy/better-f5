import rumps
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import pyperclip
from pynput import keyboard
import threading
import queue
import io
import time
import os
import sys

# Import AppKit for NSSound
from AppKit import NSSound

# --- Configuration ---
MODEL_SIZE = "small" # Options: "tiny", "base", "small", "medium", "large-v2", etc.
SAMPLE_RATE = 16000
CHANNELS = 1
DEVICE = None # Use default device
HOTKEY = keyboard.Key.f20

# --- States ---
STATE_IDLE = "IDLE"
STATE_RECORDING = "RECORDING"
STATE_PROCESSING = "PROCESSING"

# --- Icon Text ---
ICON_IDLE = "[ OK ]"
ICON_RECORDING = "[REC]"
ICON_PROCESSING = "[PROC]"

class BetterF5App(rumps.App):
    def __init__(self):
        super(BetterF5App, self).__init__("BetterF5", title=ICON_IDLE)
        self.quit_button = rumps.MenuItem("Quit") # Add quit button to menu

        self.state = STATE_IDLE
        self.audio_buffer = None
        self.stop_recording_event = threading.Event()
        self.result_queue = queue.Queue()
        self.listener_thread = None
        self.recording_thread = None
        self.processing_thread = None

        # Check if model path exists (optional, depends on faster-whisper caching)
        print(f"Loading Whisper model: {MODEL_SIZE}...")
        try:
            # Try loading from default cache or specified path
            self.model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8") # Adjust device/compute_type as needed
            print("Model loaded successfully.")
        except Exception as e:
            rumps.alert("Model Load Error", f"Failed to load Whisper model '{MODEL_SIZE}': {e}")
            print(f"Model load error: {e}")
            rumps.quit_application() # Exit if model fails to load

        # Timer to check for transcription results
        self.result_timer = rumps.Timer(self.check_results, 1)
        self.result_timer.start()

        # Start the hotkey listener
        self.start_listener()

    def update_state(self, new_state):
        self.state = new_state
        if new_state == STATE_IDLE:
            self.title = ICON_IDLE
        elif new_state == STATE_RECORDING:
            self.title = ICON_RECORDING
        elif new_state == STATE_PROCESSING:
            self.title = ICON_PROCESSING
        print(f"State changed to: {self.state}")

    def on_press(self, key):
        # IMPORTANT: This runs in the pynput listener thread
        if key == HOTKEY:
            print(f"Hotkey {HOTKEY} pressed. Current state: {self.state}")
            if self.state == STATE_IDLE:
                # Start recording in a separate thread to avoid blocking listener
                threading.Thread(target=self.start_recording_flow).start()
            elif self.state == STATE_RECORDING:
                # Signal recording thread to stop (handled within that thread's flow)
                self.stop_recording_event.set()

    def start_recording_flow(self):
        # This should run in a dedicated thread started by on_press
        if self.state != STATE_IDLE:
             print("Cannot start recording, not in IDLE state.")
             return # Avoid starting multiple recordings

        self.update_state(STATE_RECORDING)
        self.audio_buffer = io.BytesIO()
        self.stop_recording_event.clear()

        print("Starting audio recording...")
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, device=DEVICE, dtype='float32') as stream:
                while not self.stop_recording_event.is_set():
                    audio_chunk, overflowed = stream.read(SAMPLE_RATE) # Read 1 second chunks
                    if overflowed:
                        print("Warning: Input overflowed!")
                    self.audio_buffer.write(audio_chunk.tobytes())
            # Recording stopped
            print("Audio recording stopped.")
            self.update_state(STATE_PROCESSING)
            self.start_processing_flow() # Start processing immediately after stopping

        except Exception as e:
            print(f"Recording error: {e}")
            rumps.notification("Recording Error", "An error occurred during recording.", str(e))
            self.update_state(STATE_IDLE)
            self.audio_buffer = None # Clear buffer on error

    def start_processing_flow(self):
        if not self.audio_buffer:
             print("Processing error: No audio buffer found.")
             self.update_state(STATE_IDLE)
             return

        self.audio_buffer.seek(0) # Rewind buffer to the beginning
        audio_data = np.frombuffer(self.audio_buffer.getvalue(), dtype=np.float32)
        self.audio_buffer = None # Clear buffer after getting data

        if audio_data.size == 0:
            print("Processing skipped: No audio data recorded.")
            self.update_state(STATE_IDLE)
            return

        print("Starting audio processing...")
        # Run processing in its own thread
        self.processing_thread = threading.Thread(target=self._process_audio, args=(audio_data,))
        self.processing_thread.start()

    def _process_audio(self, audio_data):
        # This runs in the processing thread
        try:
            print(f"Processing {len(audio_data) / SAMPLE_RATE:.2f} seconds of audio...")
            segments, info = self.model.transcribe(audio_data, beam_size=5) # language="ko" can be added if needed

            full_text = ""
            for segment in segments:
                print(f"Segment: [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
                full_text += segment.text + " "

            final_text = full_text.strip()
            print(f"Transcription result: {final_text}")
            self.result_queue.put(final_text)

        except Exception as e:
            print(f"Transcription error: {e}")
            rumps.notification("Transcription Error", "Failed to transcribe audio.", str(e))
            # Put an empty string or error marker to signal completion with error?
            self.result_queue.put(None) # Signal completion even on error

    def check_results(self, _):
        # This runs in the main thread via rumps.Timer
        try:
            result = self.result_queue.get_nowait()
            if result is not None: # Check if transcription was successful
                if result: # Check if result is not empty string
                    pyperclip.copy(result)
                    try:
                        NSSound.soundNamed_("Tink").play() # Play standard Tink sound
                    except Exception as sound_err:
                        print(f"Failed to play sound: {sound_err}") # Log error if sound fails
                    print("Transcription copied to clipboard.")
                    # Shorten the notification text slightly
                    notification_text = result[:47] + '...' if len(result) > 50 else result
                    rumps.notification("Transcription Complete", f"Copied: '{notification_text}'", "")
                else:
                    print("Empty transcription result, nothing copied.")
                    rumps.notification("Transcription Complete", "No text detected.", "")
            else:
                # Handle the case where transcription failed (None was put in queue)
                 print("Transcription failed, nothing copied.")
                 # Notification already shown in _process_audio

            # Always reset state after processing (success or failure)
            self.update_state(STATE_IDLE)

        except queue.Empty:
            pass # No result yet
        except Exception as e:
            print(f"Error handling result: {e}")
            rumps.notification("Error", "Failed to process transcription result.", str(e))
            self.update_state(STATE_IDLE) # Reset state on error


    def start_listener(self):
        if self.listener_thread is None or not self.listener_thread.is_alive():
            print("Starting hotkey listener...")
            # Use a daemon thread so it doesn't block app exit
            self.listener_thread = threading.Thread(target=self._run_listener, daemon=True)
            self.listener_thread.start()

    def _run_listener(self):
        # pynput listener's run method blocks, so it needs its own thread
        try:
            with keyboard.Listener(on_press=self.on_press) as listener:
                listener.join()
        except Exception as e:
            print(f"Hotkey listener error: {e}")
            # Maybe notify the user? Requires main thread context.
            # For now, just print. We might need a way to signal errors back.


    @rumps.clicked("Quit")
    def quit_app(self, _):
        print("Quit button clicked. Shutting down...")
        # Stop listener (needs improvement, pynput listener stop is tricky)
        # listener.stop() is called from another thread, which is documented to work
        # but sometimes has issues. The daemon=True approach is often more reliable
        # for simple cases, ensuring the app exits even if the listener doesn't stop cleanly.

        # Signal any active recording to stop
        self.stop_recording_event.set()

        # Wait briefly for threads to potentially finish? (optional)
        # time.sleep(0.5)

        rumps.quit_application()


if __name__ == '__main__':
    # Check if running in a packaged app environment or from source
    if getattr(sys, 'frozen', False):
         # Running in a bundle (PyInstaller or py2app)
         # Set resource path if necessary
         pass # Usually assets are relative to sys._MEIPASS or similar

    # Set environment variable for pynput on macOS if needed
    # os.environ['PYOBJC_STRICT'] = '1' # Might be needed for some setups

    app = BetterF5App()
    app.run()