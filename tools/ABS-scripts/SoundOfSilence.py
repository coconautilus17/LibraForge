# SoundOfSilence - Outputs timestamps based on keyword detection at silence breaks
# Copyright (C) 2025 bengalih
# version: 2.0.0

import os
import shutil
import string
import subprocess
import re
import sys
import tempfile
import argparse
import glob
import time
import logging
from pathlib import Path
from tqdm import tqdm
from datetime import timedelta

class Config:
    def __init__(self):
        # Environment Options
        self.FFMPEG_PATH = r""
        self.WHISPER_MODEL_PATH = "./whisper-models"
        # Silence Detection Options
        self.SILENCE_THRESHOLD = "-30dB"
        self.SILENCE_DURATION = 2.5
        self.SNIPPET_DURATION = 5
        # Text Detection Options
        self.TARGET_WORDS = ["chapter", "part", "section"]
        self.TARGET_NUMBERS_ONLY = False
        self.TARGET_FIRST_WORD_ONLY = True
        # Whisper Model Configuration
        self.WHISPER_PROFILE = "flexible"
        self.WHISPER_MODEL = ""
        self.WHISPER_PROMPT = ""
        self.WHISPER_DEVICE = "auto"
        self.WHISPER_COMPUTE_TYPE = "int8"
        # File Options
        self.FILE_OUTPUT = True
        self.FILE_OUTPUT_TEXT = True
        self.TEXT_FIXUP = True
        # Testing Options
        self.TEST_RUN = False
        self.TEST_RUN_DURATION = 120  # minutes
        self.TEST_RUN_FORCE = False
        self.DEBUG = False

class Timer:
    # Track processing times
    def __init__(self):
        self.start_time = None
        self.silence_detection_time = 0.0
        self.transcription_time = 0.0
        self.misc_time = 0.0
        
    def start_total(self):
        self.start_time = time.time()
        
    def get_total_elapsed(self):
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time
    
    def format_duration(self, seconds):
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"

class AudioProcessor:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.progress_bars = {}
        self.timer = Timer()
        self.silences_file = None
        self.chapters_file = None
        self.all_silences = []
        self.all_chapters = []
        self.cumulative_offset = 0
        
    def initialize_whisper(self):
        display_logger("Initializing WhisperModel...","yellow")
        try:
            from faster_whisper import WhisperModel
            
            profile_settings = self.get_whisper_profile_settings()
            model_name = self.config.WHISPER_MODEL or profile_settings["model"]
                       
            display_logger(f"Loading faster-whisper with profile:","yellow",None,False)
            display_logger(f" {self.config.WHISPER_PROFILE}","bright_magenta")
            
            if self.config.WHISPER_MODEL:
                display_logger(f"Profile model override:","yellow",None,False)
                display_logger(f" {model_name}","bright_magenta")
                
            if self.config.DEBUG:
                display_logger(f"Profile settings:","yellow",None,False)
                display_logger(f" {profile_settings}","bright_magenta")
                
            self.model = WhisperModel(
                model_name,
                compute_type=self.config.WHISPER_COMPUTE_TYPE,
                download_root=self.config.WHISPER_MODEL_PATH,
                device=self.config.WHISPER_DEVICE
            )
            return True
            
        except Exception as e:
            display_logger(f"Error loading Whisper model: {e}","red")
            return False
    
    def get_whisper_profile_settings(self):
        profiles = {
            "fast": {"model": "tiny", "best_of": 1, "beam_size": 1, "temperature": 0.1},
            "flexible": {"model": "tiny.en", "best_of": 7, "beam_size": 7, "temperature": 0.2},
            "accurate": {"model": "tiny.en", "best_of": 10, "beam_size": 5, "temperature": 0.1},
        }
        return profiles.get(self.config.WHISPER_PROFILE, profiles["flexible"])
    
    def collect_audio_files(self, input_path):
        audio_extensions = ['.mp3', '.m4a', '.m4b', '.aac', '.opus', '.wav', '.flac', '.ogg']
        
        if os.path.isfile(input_path):
            if any(input_path.lower().endswith(ext) for ext in audio_extensions):
                return [input_path]
            return []
        
        if os.path.isdir(input_path):
            files = []
            for ext in audio_extensions:
                files.extend(glob.glob(os.path.join(input_path, '**', f'*{ext}'), recursive=True))
            return sorted(files, key=lambda x: (os.path.dirname(x), os.path.basename(x)))
        
        return []
    
    def get_audio_duration(self, audio_path):
        cmd = [
            os.path.join(self.config.FFMPEG_PATH, "ffprobe"),
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  text=True, check=True)
            return float(result.stdout.strip())
        except Exception as e:
            if self.config.DEBUG:
                display_logger(f"Error getting audio duration: {e}","red")
            return None
    
    def create_test_file(self, input_file):
        base, ext = os.path.splitext(input_file)
        test_file = f"{base}_testrun{ext}"
        
        if os.path.exists(test_file) and not self.config.TEST_RUN_FORCE:
            display_logger(f"Using existing test file: {test_file}","yellow")
            return test_file
        
        duration_seconds = self.config.TEST_RUN_DURATION * 60
        total_duration = self.get_audio_duration(input_file)
        if total_duration:
            duration_seconds = min(duration_seconds, total_duration)
        
        display_logger(f"Creating test file:","yellow",None,False)
        display_logger(f" {test_file}","bright_blue",None,False)
        display_logger(f" ({self.config.TEST_RUN_DURATION} minutes)","bright_magenta")
        
        cmd = [
            os.path.join(self.config.FFMPEG_PATH, "ffmpeg"),
            "-y", "-i", input_file, "-t", str(duration_seconds),
            "-map", "0:a:0", "-dn", "-sn", "-vn",
            "-c", "copy", test_file
        ]
         
        with tqdm(total=duration_seconds, unit="s", desc="\033[33mCreating:\033[0m", 
                 bar_format="{desc:<35} {percentage:3.0f}%|{bar:10}| Elapsed: {elapsed} | ETA: {remaining}") as pbar:
            try:
                with subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True) as proc:
                    time_pattern = re.compile(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d+)')
                    
                    for line in proc.stderr:
                        match = time_pattern.search(line)
                        if match:
                            h, m, s, f = match.groups()
                            current = int(h) * 3600 + int(m) * 60 + int(s) + int(f) / (10 ** len(f))
                            pbar.n = min(current, duration_seconds)
                            
                            # Update with total time
                            total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
                            pbar.set_description(f"Creating test file (Total: {total_elapsed})")
                            pbar.refresh()
                    
                    proc.wait()
                    if proc.returncode == 0 and os.path.exists(test_file):
                        pbar.n = duration_seconds
                        pbar.refresh()
                        return test_file
                        
            except Exception as e:
                if self.config.DEBUG:
                    display_logger(f"Error creating test file: {e}","red")
        
        return input_file
    
    def detect_silences(self, audio_path):
        silence_start_time = time.time()
        
        duration = self.get_audio_duration(audio_path)
        if not duration:
            display_logger("Could not determine audio duration","red")
            return []
        
        cmd = [
            os.path.join(self.config.FFMPEG_PATH, "ffmpeg"),
            "-hide_banner", "-i", audio_path,
            "-map", "0:a:0", "-dn", "-sn", "-vn",
            "-af", f"silencedetect=noise={self.config.SILENCE_THRESHOLD}:d={self.config.SILENCE_DURATION}",
            "-f", "null", "-"
        ]
        
        silence_ends = []
        time_pattern = re.compile(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d+)')
        silence_pattern = re.compile(r"silence_end: ([0-9.]+)")
        
        if self.config.DEBUG:
            display_logger(f"Detecting silences (Duration: {self.format_timestamp(duration)}) ...","bright_yellow")
        
        total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
        
        with tqdm(total=duration, unit="", desc=f"\033[1;33mDetect\033[0m (Time: {total_elapsed}):",
                 bar_format="{desc:<37} {percentage:3.0f}%|{bar:10}| Elapsed: {elapsed} | ETA: {remaining} | {unit}",
                 ncols=100, dynamic_ncols=False, leave=True, file=sys.stdout) as pbar:
            
            pbar.unit = "0 silence(s) (00:00:00)"
            pbar.refresh()
            
            try:
                with subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True) as proc:
                    for line in proc.stderr:
                        # Update progress
                        time_match = time_pattern.search(line)
                        if time_match:
                            h, m, s, f = time_match.groups()
                            current = int(h) * 3600 + int(m) * 60 + int(s) + int(f) / (10 ** len(f))
                            pbar.n = min(current, duration)
                            pbar.unit = f"{len(silence_ends)} silence(s) ({self.format_timestamp(silence_ends[-1]) if silence_ends else '00:00'})"
                            
                            # Update with total time
                            total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
                            pbar.set_description(f"\033[1;33mDetect\033[0m (Time: {total_elapsed})")
                            pbar.refresh()
                        
                        # Detect silence end
                        silence_match = silence_pattern.search(line)
                        if silence_match:
                            silence_time = float(silence_match.group(1)) - 0.5
                            silence_ends.append(silence_time)
                    
                    proc.wait()
                    
            except Exception as e:
                if self.config.DEBUG:
                    display_logger(f"Error during silence detection: {e}","red")
            finally:
                pbar.n = duration
                pbar.unit = f"{len(silence_ends)} silence(s) ({self.format_timestamp(silence_ends[-1]) if silence_ends else '00:00'})"
                total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
                pbar.set_description(f"\033[1;33mDetect\033[0m (Time: {total_elapsed})")
                pbar.refresh()
        
        # Track silence detection time
        silence_end_time = time.time()
        self.timer.silence_detection_time += (silence_end_time - silence_start_time)
        
        return silence_ends
    
    def extract_segment(self, input_file, start_time, duration, output_file):
        cmd = [
            os.path.join(self.config.FFMPEG_PATH, "ffmpeg"),
            "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(start_time), "-t", str(duration),
            "-i", input_file,
            "-map", "0:a:0", "-dn", "-sn", "-vn",
            "-ac", "1", "-ar", "16000",
            "-acodec", "pcm_s16le", "-f", "wav", output_file
        ]
        
        try:
            subprocess.run(cmd, check=True)
            return os.path.exists(output_file)
        except Exception as e:
            if self.config.DEBUG:
                display_logger(f"Error extracting segment: {e}","red")
            return False
    
    def transcribe_segment(self, audio_file):
        try:
            profile_settings = self.get_whisper_profile_settings()
            segments, _ = self.model.transcribe(
                audio_file, language="en", vad_filter=False,
                best_of=profile_settings["best_of"],
                beam_size=profile_settings["beam_size"],
                temperature=profile_settings["temperature"],
                initial_prompt=self.config.WHISPER_PROMPT,
            )
            
            text = " ".join([seg.text for seg in segments]).strip()
            
            # Check for target words
            found = False
            if self.config.TARGET_FIRST_WORD_ONLY and text:
                first_word = text.split()[0].strip(string.punctuation).lower()
                found = first_word in [word.lower() for word in self.config.TARGET_WORDS]
            else:
                found = any(word.lower() in text.lower() for word in self.config.TARGET_WORDS)
            
            if self.config.DEBUG:
                found_color = "green" if found else "red"
                display_logger(f"\n{found}: ",found_color,None,False)
                display_logger(f"{text}","yellow",None,True)
         
            return found, text
            
        except Exception as e:
            if self.config.DEBUG:
                display_logger(f"Error during transcription: {e}","red")
            return False, ""
    
    def process_silences(self, audio_path, test_points):
        transcription_start_time = time.time()
        chapters = []
        
        if self.config.DEBUG:
            display_logger(f"Transcribing {len(test_points)} test points","bright_cyan")

        total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
        
        with tqdm(total=len(test_points), unit="", desc=f"\033[1;36mTranscribe\033[0m (Time: {total_elapsed}):",
                 bar_format="{desc} {percentage:3.0f}%|{bar:10}| Elapsed: {elapsed} | ETA: {remaining} | {n}/{total} ({unit})",
                 ncols=100, dynamic_ncols=False, file=sys.stdout, leave=True) as pbar:
            
            pbar.unit = "00:00:00"
            pbar.refresh()
            
            with tempfile.TemporaryDirectory() as temp_dir:
                for i, test_point in enumerate(test_points):
                    segment_file = os.path.join(temp_dir, f"segment_{i}.wav")
                    
                    # Extract and transcribe segment
                    if self.extract_segment(audio_path, test_point, self.config.SNIPPET_DURATION, segment_file):
                        found, text = self.transcribe_segment(segment_file)
                        os.remove(segment_file)
                        if found:
                            timestamp = test_point + self.cumulative_offset
                            formatted_time = self.format_timestamp(timestamp)
                            formatted_time_ms = self.format_timestamp(timestamp,True)
                            fixed_text = self.fix_text(self.to_camel_case(text))
                            
                            chapters.append((fixed_text, formatted_time, timestamp))
                            #point_type = "\033[35mfile start\033[0m" if test_point == 0.0 else "\033[34msilence\033[0m"
                            #tqdm.write(f"\033[32m{formatted_time}\t{fixed_text} ({point_type})\033[0m")
                            tqdm.write(f"\033[32m{formatted_time}\t{fixed_text}\033[0m")
                            
                            # Write chapter to file immediately
                            if self.config.FILE_OUTPUT:
                                try:
                                    with open(self.chapters_file, "a") as f:
                                        if self.config.FILE_OUTPUT_TEXT:
                                            f.write(f"{fixed_text}\t{formatted_time_ms}\n")
                                        else:
                                            f.write(f"{formatted_time_ms}\n")
                                except Exception as e:
                                    display_logger(f"Error writing to chapters file: {e}","red")
                    
                    pbar.update(1)
  
                    current_timestamp = self.format_timestamp(test_point)
                    pbar.unit = current_timestamp
                    
                    # Update with total time
                    total_elapsed = self.timer.format_duration(self.timer.get_total_elapsed())
                    pbar.set_description(f"\033[1;36mTranscribe\033[0m (Time: {total_elapsed})")
                    pbar.refresh()
        
        # Track transcription time
        transcription_end_time = time.time()
        self.timer.transcription_time += (transcription_end_time - transcription_start_time)
        
        return chapters
    
    def process_files(self, audio_files):
        self.all_silences = []
        self.all_chapters = []
        self.cumulative_offset = 0
        test_remaining = self.config.TEST_RUN_DURATION * 60 if self.config.TEST_RUN else float('inf')
        
        # Determine output base name
        if len(audio_files) == 1:
            base_path = os.path.splitext(audio_files[0])[0]
        else:
            base_dir = os.path.dirname(audio_files[0])
            dir_name = os.path.basename(base_dir) or "output"
            base_path = os.path.join(base_dir, dir_name)
        
        self.silences_file = f"{base_path}_silences.txt"
        self.chapters_file = f"{base_path}_chapters.txt"
        if self.config.FILE_OUTPUT:
            try:
                if os.path.exists(self.silences_file):
                    os.remove(self.silences_file)
                if os.path.exists(self.chapters_file):
                    os.remove(self.chapters_file)
            except Exception as e:
                display_logger(f"Error clearing output files: {e}","red")
        
        display_logger(f"Processing {len(audio_files)} file(s)...","cyan",False)
              
        for i, audio_path in enumerate(audio_files, 1):
            # Handle test run limits
            if self.config.TEST_RUN and test_remaining <= 0:
                display_logger("Test run duration exhausted","red")
                break
            
            processing_path = audio_path
            file_duration = self.get_audio_duration(audio_path)
            
            display_logger(f"\n--- File {i}/{len(audio_files)}: {os.path.basename(audio_path)}","cyan",None,False)
            display_logger(f" ({self.format_timestamp(file_duration)})","magenta",None,False)
            display_logger(f" ---","cyan")
            
            if not file_duration:
                display_logger(f"Skipping file due to duration detection failure","red")
                continue
            
            if self.config.TEST_RUN:
                actual_duration = min(file_duration, test_remaining)
                if actual_duration < file_duration:
                    processing_path = self.create_test_file(audio_path)
            else:
                actual_duration = file_duration
            
            # Detect silences
            silence_ends = self.detect_silences(processing_path)
            
            # Write silences to file immediately
            if self.config.FILE_OUTPUT and silence_ends:
                try:
                    with open(self.silences_file, "a") as f:
                        for silence in silence_ends:
                            adjusted_silence = silence + self.cumulative_offset
                            f.write(f"{self.format_timestamp(adjusted_silence, True)}\n")
                    if self.config.DEBUG:
                        display_logger(f"\nSilences appended to: {self.silences_file}","yellow")
                except Exception as e:
                    display_logger(f"Error writing to silences file: {e}","red")
            
            # Always test the beginning of each file as a potential chapter start
            test_points = [0.0]  # Always start with file beginning
            test_points.extend(silence_ends)
            
            # Adjust silences for cumulative offset
            adjusted_silences = [s + self.cumulative_offset for s in silence_ends]
            self.all_silences.extend(adjusted_silences)
            
            # Process test points for chapters
            chapters = self.process_silences(processing_path, test_points)
            self.all_chapters.extend(chapters)
            
            # Update offsets
            self.cumulative_offset += actual_duration
            if self.config.TEST_RUN:
                test_remaining -= actual_duration
        
        return self.all_silences, self.all_chapters
    
    def setup_target_words(self):
        if self.config.TARGET_NUMBERS_ONLY:
            self.config.TARGET_WORDS = [
                "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
                "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
                "31", "32", "33", "34", "35", "36", "37", "38", "39", "40",
                "41", "42", "43", "44", "45", "46", "47", "48", "49", "50",
                "51", "52", "53", "54", "55", "56", "57", "58", "59", "60",
                "61", "62", "63", "64", "65", "66", "67", "68", "69", "70",
                "71", "72", "73", "74", "75", "76", "77", "78", "79", "80",
                "81", "82", "83", "84", "85", "86", "87", "88", "89", "90",
                "91", "92", "93", "94", "95", "96", "97", "98", "99", "100",
                "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                "twenty one", "twenty two", "twenty three", "twenty four", "twenty five",
                "twenty six", "twenty seven", "twenty eight", "twenty nine", "thirty",
                "thirty one", "thirty two", "thirty three", "thirty four", "thirty five",
                "thirty six", "thirty seven", "thirty eight", "thirty nine", "forty",
                "forty one", "forty two", "forty three", "forty four", "forty five",
                "forty six", "forty seven", "forty eight", "forty nine", "fifty",
                "fifty one", "fifty two", "fifty three", "fifty four", "fifty five",
                "fifty six", "fifty seven", "fifty eight", "fifty nine", "sixty",
                "sixty one", "sixty two", "sixty three", "sixty four", "sixty five",
                "sixty six", "sixty seven", "sixty eight", "sixty nine", "seventy",
                "seventy one", "seventy two", "seventy three", "seventy four", "seventy five",
                "seventy six", "seventy seven", "seventy eight", "seventy nine", "eighty",
                "eighty one", "eighty two", "eighty three", "eighty four", "eighty five",
                "eighty six", "eighty seven", "eighty eight", "eighty nine", "ninety",
                "ninety one", "ninety two", "ninety three", "ninety four", "ninety five",
                "ninety six", "ninety seven", "ninety eight", "ninety nine", "one hundred"
            ]
    
    @staticmethod
    def format_timestamp(seconds, ms=False):
        """Format seconds to HH:MM:SS.mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)  # Extract milliseconds
        if ms:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
        else:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    @staticmethod
    def to_camel_case(text):
        return ' '.join(word.capitalize() for word in text.split())
    
    def fix_text(self, text):
        if not self.config.TEXT_FIXUP:
            return text
        
        # Standardize chapter/part/section formatting
        pattern = re.compile(
            r'^(Chapter|Section|Part)\s+(\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)[.,]?\s*(.*?)[\.,]?$', 
            re.IGNORECASE
        )
        match = pattern.match(text)
        if match:
            prefix, number, title = match.groups()
            title = title.rstrip('.,')
            return f"{prefix} {number}: {title}"
        
        return text.rstrip('.,')

def display_logger(message, fg_color=None, bg_color=None, newline=True):
    # Color mappings for ANSI codes
    fg_color_map = {
        # Foreground colors (standard)
        'black': '\033[30m',
        'red': '\033[31m',
        'green': '\033[32m',
        'yellow': '\033[33m',
        'blue': '\033[34m',
        'magenta': '\033[35m',
        'cyan': '\033[36m',
        'white': '\033[37m',
        # Foreground colors (bright)
        'bright_red': '\033[1;31m',
        'bright_green': '\033[1;32m',
        'bright_yellow': '\033[1;33m',
        'bright_blue': '\033[1;34m',
        'bright_magenta': '\033[1;35m',
        'bright_cyan': '\033[1;36m',
        'white': '\033[1;37m',
        # Reset
        'reset': '\033[0m'
    }

    bg_color_map = {
        # Background colors (standard)
        'black': '\033[40m',
        'red': '\033[41m',
        'green': '\033[42m',
        'yellow': '\033[43m',
        'blue': '\033[44m',
        'magenta': '\033[45m',
        'cyan': '\033[46m',
        'white': '\033[47m',
        # Background colors (bright)
        'bright_red': '\033[1;41m',
        'bright_green': '\033[1;42m',
        'bright_yellow': '\033[1;43m',
        'bright_blue': '\033[1;44m',
        'bright_magenta': '\033[1;45m',
        'bright_cyan': '\033[1;46m',
        'bright_white': '\033[1;47m',
        # Reset
        'reset': '\033[0m'
    }
    # Prepare terminal output
    codes = []
    if fg_color in fg_color_map:
        codes.append(fg_color_map[fg_color])
    if bg_color in bg_color_map:
        codes.append(bg_color_map[bg_color])
    
    if codes:
        colored_message = f"{''.join(codes)}{message}{fg_color_map['reset']}"
    else:
        colored_message = message

    # Print to terminal
    print(colored_message, end='' if not newline else '\n', flush=True)

    # Log plain text (strip ANSI codes if present)
    plain_message = re.sub(r'\033\[[0-9;]*m', '', message)
    logging.info(plain_message)
    
def validate_ffmpeg_path(config):
    ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    
    if config.FFMPEG_PATH:
        ffmpeg_path = os.path.join(config.FFMPEG_PATH, ffmpeg_name)
        ffprobe_path = os.path.join(config.FFMPEG_PATH, ffprobe_name)
        
        if not (os.path.isfile(ffmpeg_path) and os.path.isfile(ffprobe_path)):
            config.FFMPEG_PATH = ""
    
    if not config.FFMPEG_PATH:
        if not (shutil.which(ffmpeg_name) and shutil.which(ffprobe_name)):
            display_logger("Error: FFmpeg not found. Please install FFmpeg or specify --ffmpeg-path","red")
            sys.exit(1)

def str2bool(v):
    return str(v).lower() in ("yes", "true", "t", "1")

def whisper_profile_validator(profiles_dict):
    def validator(value):
        if value not in profiles_dict:
            raise argparse.ArgumentTypeError(
                f"\nInvalid profile '{value}'. Choose from: {', '.join(profiles_dict.keys())}"
            )
        return value
    return validator

def main():
    # Whisper profiles
    WHISPER_PROFILES_DICT = {
        "fast": {"model": "tiny", "best_of": 1, "beam_size": 1, "temperature": 0.1},
        "flexible": {"model": "tiny.en", "best_of": 7, "beam_size": 7, "temperature": 0.2},
        "accurate": {"model": "tiny.en", "best_of": 10, "beam_size": 5, "temperature": 0.1},
    }
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='Detect chapters in audio files using silence detection and transcription')
    parser.add_argument('audio_file', help='Path to audio file or directory')
    parser.add_argument('--ffmpeg-path', default=Config().FFMPEG_PATH, help='Path to FFmpeg bin directory')
    parser.add_argument('--whisper-model-path', default=Config().WHISPER_MODEL_PATH, help='Path to Whisper model directory')
    parser.add_argument('--silence-threshold', default=Config().SILENCE_THRESHOLD, help='Silence detection threshold')
    parser.add_argument('--silence-duration', type=float, default=Config().SILENCE_DURATION, help='Minimum silence duration')
    parser.add_argument('--snippet-duration', type=int, default=Config().SNIPPET_DURATION, help='Transcription snippet duration')
    parser.add_argument('--target-words', action='append', default=[], help='Target words to detect')
    parser.add_argument('--target-first-word-only', type=str2bool, default=Config().TARGET_FIRST_WORD_ONLY, help='Match only first word')
    parser.add_argument('--target-numbers-only', type=str2bool, default=Config().TARGET_NUMBERS_ONLY, help='Use numeric detection only')
    parser.add_argument('--whisper-profile', type=whisper_profile_validator(WHISPER_PROFILES_DICT), default=Config().WHISPER_PROFILE, help='Whisper performance profile')
    parser.add_argument('--whisper-model', default=Config().WHISPER_MODEL, help='Whisper model name')
    parser.add_argument('--whisper-prompt', default=Config().WHISPER_PROMPT, help='Whisper prompt')
    parser.add_argument('--whisper-device', default=Config().WHISPER_DEVICE, help='Device for inference')
    parser.add_argument('--whisper-compute-type', default=Config().WHISPER_COMPUTE_TYPE, help='Compute type')
    parser.add_argument('--file-output', type=str2bool, default=Config().FILE_OUTPUT, help='Write output files')
    parser.add_argument('--file-output-text', type=str2bool, default=Config().FILE_OUTPUT_TEXT, help='Include text in output')
    parser.add_argument('--text-fixup', type=str2bool, default=Config().TEXT_FIXUP, help='Enable text fixup')
    parser.add_argument('--test-run', type=str2bool, default=Config().TEST_RUN, help='Enable test run mode')
    parser.add_argument('--test-run-duration', type=int, default=Config().TEST_RUN_DURATION, help='Test run duration (minutes)')
    parser.add_argument('--test-run-force', type=str2bool, default=Config().TEST_RUN_FORCE, help='Force recreation of test file')
    parser.add_argument('--debug', type=str2bool, default=Config().DEBUG, help='Enable debug output')
    
    args = parser.parse_args()
    
    # Configure
    config = Config()
    config.FFMPEG_PATH = args.ffmpeg_path
    config.WHISPER_MODEL_PATH = args.whisper_model_path
    config.SILENCE_THRESHOLD = args.silence_threshold
    config.SILENCE_DURATION = args.silence_duration
    config.SNIPPET_DURATION = args.snippet_duration
    config.TARGET_WORDS = config.TARGET_WORDS + (args.target_words or [])
    config.TARGET_FIRST_WORD_ONLY = args.target_first_word_only
    config.TARGET_NUMBERS_ONLY = args.target_numbers_only
    config.WHISPER_PROFILE = args.whisper_profile
    config.WHISPER_MODEL = args.whisper_model
    config.WHISPER_PROMPT = args.whisper_prompt
    config.WHISPER_DEVICE = args.whisper_device
    config.WHISPER_COMPUTE_TYPE = args.whisper_compute_type
    config.FILE_OUTPUT = args.file_output
    config.FILE_OUTPUT_TEXT = args.file_output_text
    config.TEXT_FIXUP = args.text_fixup
    config.TEST_RUN = args.test_run
    config.TEST_RUN_DURATION = args.test_run_duration
    config.TEST_RUN_FORCE = args.test_run_force
    config.DEBUG = args.debug
    
    if config.DEBUG:
        # Configure logging
        logging.basicConfig(
            filename="sound_of_silence.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    # Validate environment
    validate_ffmpeg_path(config)
    os.environ["PATH"] += os.pathsep + config.FFMPEG_PATH
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    
    # Initialize processor
    processor = AudioProcessor(config)
    
    # Start total timing
    processor.timer.start_total()
    
    # Setup target words
    processor.setup_target_words()
    
    # Collect audio files
    audio_files = processor.collect_audio_files(args.audio_file)
    if not audio_files:
        display_logger(f"No audio files found at: {args.audio_file}","red")
        return
    
    if config.DEBUG:
        display_logger(f"Found {len(audio_files)} audio file(s)","green")
        
    # Initialize Whisper
    if not processor.initialize_whisper():
        return
    
    # Display configuration
    target_display = "{TARGET_NUMBERS_ONLY}" if config.TARGET_NUMBERS_ONLY else config.TARGET_WORDS
    display_logger(f'Target words:',"white","bright_cyan",False)
    display_logger(f' {target_display}',"bright_cyan",None)
    
    # Process files
    processor.process_files(audio_files)
    
    # Calculate final timing
    total_time = processor.timer.get_total_elapsed()
    silence_time = processor.timer.silence_detection_time
    transcription_time = processor.timer.transcription_time
    misc_time = total_time - silence_time - transcription_time
    
    # Summary
    display_logger(f"\n=== Summary ===","cyan")
    display_logger(f"Silences detected: {len(processor.all_silences)}","cyan")
    display_logger(f"Target Breaks found: {len(processor.all_chapters)}","magenta")
    
    # Timing breakdown
    display_logger(f"\n=== Timing Breakdown ===","cyan")
    display_logger(f"Silence Detection: {processor.timer.format_duration(silence_time)}","cyan")
    display_logger(f"Transcription: {processor.timer.format_duration(transcription_time)}","magenta")
    display_logger(f"Total Time: {processor.timer.format_duration(total_time)}","yellow")
    
    if processor.all_chapters:
        display_logger(f"\n=== Target Breaks ===","cyan")
        for text, timestamp, _ in sorted(processor.all_chapters, key=lambda x: x[2]):
            display_logger(f"{text}","green",None,False)
            display_logger(f"\t{timestamp}","yellow")
            
        display_logger(f"\n=== Output files ===","cyan")
        display_logger(f"{processor.chapters_file}","bright_yellow")
        display_logger(f"{processor.silences_file}","bright_yellow")

        display_logger(f"\nChapter data can be imported manually, or with","black","white",False)
        display_logger(f" ACHe.py","green","white")
        
if __name__ == "__main__":
    main()
