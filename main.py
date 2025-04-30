import rumps
import sounddevice as sd
import numpy as np
# Removed: from faster_whisper import WhisperModel
import openai # Added
import pyperclip
from pynput import keyboard
import threading
import queue
import io
import time
import os
import sys
# Removed: import torch (Potentially keep if other libs need it indirectly, but likely removable)
from dotenv import load_dotenv # Added for .env support
import soundfile as sf # Added
import json # Added for config file handling

# Import AppKit for NSSound
from AppKit import NSSound

# Load environment variables from .env file - Added
load_dotenv()

# --- Configuration ---
# Removed: MODEL_SIZE = "medium"
SAMPLE_RATE = 16000
CHANNELS = 1
DEVICE = None # Use default device
HOTKEY = keyboard.Key.f20
WHISPER_API_MODEL = "whisper-1" # Added
PREFERENCES_KEY = "openai_api_key" # Added key for settings
APP_NAME = "BetterF5"
CONFIG_DIR = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_CONFIG = {"openai_api_key": "YOUR_API_KEY_HERE"}

# --- States ---
STATE_IDLE = "[ OK ]" # Merged icon text into state for simplicity
STATE_RECORDING = "[REC]"
STATE_PROCESSING = "[PROC]"
STATE_CONFIG_ERROR = "[CFG?]" # State for config issues

# --- Icon Text ---
ICON_IDLE = "[ OK ]"
ICON_RECORDING = "[REC]"
ICON_PROCESSING = "[PROC]"

class BetterF5App(rumps.App):
    def __init__(self):
        # Use initial state based on key availability later
        super(BetterF5App, self).__init__(APP_NAME, title=STATE_IDLE) # Start with IDLE
        # MenuItem 객체 직접 생성/할당 제거
        # self.preferences_item = rumps.MenuItem("Preferences...")
        # self.quit_button = rumps.MenuItem("Quit")

        # 메뉴를 문자열 리스트로 정의
        self.menu = [rumps.separator, "Quit"] # Keep Quit in menu definition (handled by rumps)

        self.state = STATE_IDLE # Set initial state
        self.audio_buffer_list = []
        self.stop_recording_event = threading.Event()
        self.result_queue = queue.Queue()
        self.listener_thread = None
        self.recording_thread = None
        self.processing_thread = None

        self.api_key = None
        self.client = None
        self._load_config_and_init_client() # Load config and initialize client directly

        # Timer to check for transcription results
        self.result_timer = rumps.Timer(self.check_results, 1)
        self.result_timer.start()

        # Start the hotkey listener
        self.start_listener() # Re-enabled listener

    def _load_config_and_init_client(self):
        """Load config from file and initialize OpenAI client."""
        try:
            # Ensure config directory exists
            os.makedirs(CONFIG_DIR, exist_ok=True)

            # Check if config file exists
            if not os.path.exists(CONFIG_FILE):
                print(f"Config file not found. Creating default at: {CONFIG_FILE}")
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
                rumps.alert(
                    f"{APP_NAME} Configuration Needed",
                    f"Configuration file created at:\n{CONFIG_FILE}\n\nPlease edit this file and add your OpenAI API key."
                )
                self.update_state(STATE_CONFIG_ERROR)
                return False

            # Load config file
            print(f"Loading config from: {CONFIG_FILE}")
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            api_key = config.get("openai_api_key")

            if not api_key or api_key == DEFAULT_CONFIG["openai_api_key"]:
                print("API Key not found or is default in config file.")
                rumps.alert(
                    f"{APP_NAME} API Key Needed",
                    f"Please add your OpenAI API key to:\n{CONFIG_FILE}"
                )
                self.update_state(STATE_CONFIG_ERROR)
                return False

            # Try to initialize client
            print("API Key found in config. Initializing OpenAI client...")
            self.api_key = api_key
            self.client = openai.OpenAI(api_key=self.api_key)
            # Optional: Test call to verify key
            # self.client.models.list()
            print("OpenAI client initialized successfully.")
            if self.state == STATE_CONFIG_ERROR: # Revert state if it was error
                 self.update_state(STATE_IDLE)
            return True

        except json.JSONDecodeError:
            print(f"Error decoding JSON from config file: {CONFIG_FILE}")
            rumps.alert("Config File Error", f"Could not read the configuration file. Please check its format.\n{CONFIG_FILE}")
            self.update_state(STATE_CONFIG_ERROR)
            self.client = None
            return False
        except Exception as e:
            print(f"Error loading config or initializing client: {e}")
            rumps.alert("Initialization Error", f"An error occurred: {e}")
            # Try to distinguish key errors from other init errors if possible
            if isinstance(e, openai.AuthenticationError):
                 rumps.alert("API Key Invalid", f"The API key in the config file seems invalid.\n{CONFIG_FILE}")
            self.update_state(STATE_CONFIG_ERROR)
            self.client = None
            return False

    def update_state(self, new_state):
        self.state = new_state
        self.title = new_state # Use state directly as icon text
        print(f"State changed to: {self.state}")

    def on_press(self, key):
        # IMPORTANT: This runs in the pynput listener thread
        if key == HOTKEY:
            print(f"Hotkey {HOTKEY} pressed. Current state: {self.state}")
            if self.state == STATE_IDLE:
                threading.Thread(target=self.start_recording_flow).start()
            elif self.state == STATE_RECORDING:
                self.stop_recording_event.set()
            elif self.state == STATE_CONFIG_ERROR:
                 rumps.alert("Configuration Error", f"Please check the config file and API key:\n{CONFIG_FILE}")

    def start_recording_flow(self):
        # Check for valid client before starting
        if not self.client or self.state == STATE_CONFIG_ERROR:
             print("Recording blocked: Client not initialized or config error.")
             rumps.alert("Configuration Needed", f"Please ensure a valid API Key is in the config file:\n{CONFIG_FILE}")
             return
        if self.state != STATE_IDLE:
            print("Cannot start recording, not in IDLE state.")
            return

        self.update_state(STATE_RECORDING)
        self.audio_buffer_list = [] # Reset list for new recording
        self.stop_recording_event.clear()

        print("Starting audio recording...")
        try:
            # Use a callback to append chunks directly to the list
            def audio_callback(indata, frames, time, status):
                if status:
                    print(status, file=sys.stderr)
                # Append a copy of the incoming data array
                self.audio_buffer_list.append(indata.copy())

            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, device=DEVICE, dtype='float32', callback=audio_callback):
                # Wait until the stop event is set
                while not self.stop_recording_event.is_set():
                    sd.sleep(100) # Check event periodically without busy-waiting

            # Recording stopped
            print("Audio recording stopped.")
            self.update_state(STATE_PROCESSING)
            self.start_processing_flow() # Start processing immediately after stopping

        except Exception as e:
            print(f"Recording error: {e}")
            rumps.notification("Recording Error", "An error occurred during recording.", str(e))
            self.update_state(STATE_IDLE)
            self.audio_buffer_list = [] # Clear list on error

    def start_processing_flow(self):
        if not self.audio_buffer_list:
             print("Processing error: No audio data recorded.")
             self.update_state(STATE_IDLE)
             return

        # Concatenate the list of numpy arrays into one
        audio_data_np = np.concatenate(self.audio_buffer_list, axis=0)
        self.audio_buffer_list = [] # Clear list after concatenating

        if audio_data_np.size == 0:
            print("Processing skipped: No audio data recorded.")
            self.update_state(STATE_IDLE)
            return

        # Check client again before starting thread
        if not self.client:
             print("Processing aborted: OpenAI client not initialized (Config/Key Error?).")
             self.update_state(STATE_CONFIG_ERROR)
             # Maybe show alert again?
             rumps.alert("Configuration Error", f"Cannot process audio. Please check config file:\n{CONFIG_FILE}")
             return

        print("Starting audio processing via OpenAI API...")
        # Run processing in its own thread
        self.processing_thread = threading.Thread(target=self._process_audio_api, args=(audio_data_np,))
        self.processing_thread.start()

    # Renamed from _process_audio to _process_audio_api
    def _process_audio_api(self, audio_data_np):
        # Check for client initialization
        if not self.client:
            print("API call skipped: Client not initialized.")
            self.result_queue.put(None)
            return
        # This runs in the processing thread
        wav_buffer = None
        try:
            print(f"Preparing {audio_data_np.shape[0] / SAMPLE_RATE:.2f}s audio data for API...")
            # Create an in-memory WAV file using soundfile
            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, audio_data_np, SAMPLE_RATE, format='WAV', subtype='PCM_16')
            wav_buffer.seek(0) # Reset buffer position to the beginning

            # Provide the buffer with a filename hint
            file_tuple = ("audio.wav", wav_buffer)

            print(f"Sending audio to OpenAI Whisper API...")
            # Call the OpenAI API
            transcript_response = self.client.audio.transcriptions.create(
                model=WHISPER_API_MODEL,
                file=file_tuple,
                response_format="text"
            )

            final_text = transcript_response.strip() if isinstance(transcript_response, str) else ""

            print(f"Transcription result: {final_text}")
            self.result_queue.put(final_text)

        except openai.APIConnectionError as e:
            error_message = f"Network error contacting OpenAI: {e}"
            print(error_message)
            rumps.notification("API Network Error", "Could not connect to OpenAI.", str(e))
            self.result_queue.put(None)
        except openai.RateLimitError as e:
            error_message = f"OpenAI rate limit exceeded: {e}"
            print(error_message)
            rumps.notification("API Rate Limit", "Rate limit exceeded.", str(e))
            self.result_queue.put(None)
        except openai.AuthenticationError as e:
            error_message = f"OpenAI Authentication Error: {e}. Key might be invalid."
            print(error_message)
            rumps.notification("API Authentication Error", "Invalid API Key in config.", f"Please check {CONFIG_FILE}")
            self.client = None # De-initialize client
            # State will be updated in check_results based on None result
            self.result_queue.put(None)
        except openai.APIStatusError as e:
             error_message = f"OpenAI API error: Status={e.status_code}, Response={e.response}"
             print(error_message)
             # Use message attribute if available, otherwise fallback
             detail = str(e.message) if hasattr(e, 'message') and e.message else str(e)
             rumps.notification("OpenAI API Error", f"Status Code: {e.status_code}", detail)
             self.result_queue.put(None)
        except openai.APIError as e: # Catch other API errors
            error_message = f"General OpenAI API error: {e}"
            print(error_message)
            rumps.notification("OpenAI API Error", "An API error occurred.", str(e))
            self.result_queue.put(None)
        except Exception as e: # Catch any other unexpected errors during processing
            error_message = f"Transcription error (API call / WAV conversion): {e}"
            print(error_message)
            rumps.notification("Transcription Error", "Failed during API transcription or WAV conversion.", str(e))
            self.result_queue.put(None) # Signal completion even on error
        finally:
            if wav_buffer:
                wav_buffer.close() # Ensure the BytesIO object is closed

    def check_results(self, _):
        # This runs in the main thread via rumps.Timer
        try:
            result = self.result_queue.get_nowait()
            final_state = STATE_IDLE # Assume success initially

            if result is not None: # Check if transcription was successful (not None)
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
                    # Optionally notify user about empty result
                    # rumps.notification("Transcription Complete", "No text detected.", "")
            else:
                # Handle the case where transcription failed (None was put in queue)
                 print("Transcription failed, nothing copied.")
                 # If client is None, it means config/auth error occurred
                 if not self.client:
                      final_state = STATE_CONFIG_ERROR
                 # else: other error, potentially transient, maybe stay IDLE?
                 # For simplicity, let's reset to IDLE for non-config errors.
                 # If a persistent network error occurs, user will see notifications.

            # Update state based on outcome
            self.update_state(final_state)

        except queue.Empty:
            pass # No result yet
        except Exception as e: # Catch errors in result handling itself
            print(f"Error handling result: {e}")
            rumps.notification("Error", "Failed to process transcription result.", str(e))
            # Reset to IDLE on result handling error, unless config known bad
            if self.client: # If client was valid before, reset to IDLE
                 self.update_state(STATE_IDLE)
            else: # Otherwise, stay in CONFIG_ERROR state
                 self.update_state(STATE_CONFIG_ERROR)

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


if __name__ == '__main__':
    # Removed the early API key check block, handled in __init__ now
    app = BetterF5App()
    app.run()