import sys
sys.setrecursionlimit(2000) # Increase recursion depth limit

from setuptools import setup

APP = ['main.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True, # Allows dropping files onto the app icon (not relevant here, but standard)
    'packages': ['rumps', 'pynput', 'sounddevice', 'pyperclip', 'numpy', 'faster_whisper'], # faster_whisper is included
    'iconfile': None, # No custom icon for now
    'includes': ['faster_whisper', 'cffi', 'objc', 'Quartz', 'Quartz.ImageKit', 'AppKit', 'CoreFoundation', 'Foundation'], # Add more core frameworks
    'frameworks': [
        '/opt/anaconda3/lib/libffi.8.dylib',
        '/opt/homebrew/opt/portaudio/lib/libportaudio.dylib', # Add PortAudio dylib path
        '/opt/homebrew/opt/openssl@3/lib/libssl.dylib', # Add OpenSSL lib
        '/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib' # Add OpenSSL lib
    ],
    'arch': 'universal2', # Build for both Intel and Apple Silicon
    'plist': {
        'CFBundleIdentifier': 'com.wielder.betterf5',
        'CFBundleName': 'BetterF5',
        'CFBundleShortVersionString': '0.1.0',
        'LSUIElement': True, # Hide Dock icon
        'NSHumanReadableCopyright': 'Copyright © 2024 Wielder. All rights reserved.',
        'NSMicrophoneUsageDescription': 'BetterF5 needs access to the microphone to record audio for transcription when you press the hotkey.',
        'NSAppleEventsUsageDescription': 'BetterF5 needs to monitor keyboard events globally to detect the F5 hotkey press.'
    }
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'], # Only py2app needed here
) 