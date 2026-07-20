# SoundOfSilence – Chapter Detection using Whisper

**SoundOfSilence** is a Python script that analyzes audio files for supplied keywords (phrases) for purpposes of detecting section breaks.

It functions by first detecting silences using [ffmpeg](https://ffmpeg.org/) and then extracting relevant segments for transcribing  using [faster-whisper](https://github.com/guillaumekln/faster-whisper).
It outputs a listing of timestamps based on detected section breaks.

It has very high performance with good accuracy on a wide variety of books.

Very useful for chapterizing poorly marked audiobooks which use keywords in narration to separate sections.

---

## 📌 Features

- Detects **silences** using FFmpeg
- Extracts audio **snippets** following each silence
- Uses **faster-whisper** to transcribe audio
- Matches **target keywords** (e.g., "Chapter", "Section")
- Matches on **numbers only** to detect sections using only numbers in narration
- Saves **chapter timestamps** and **transcriptions** to files
- Supports **test-run** mode for quicker processing
- Optional **text cleanup** (capitalization, punctuation)

---

## 🚀 Requirements

- Python 3.7+
- `faster-whisper`
- `ffmpeg` and `ffprobe`
- `tqdm` for progress visualization

Install required Python packages:

```bash
pip install faster-whisper tqdm
```

⚠️ Ensure FFmpeg and FFprobe are installed and added to your system path, or specify the directory via `FFMPEG_PATH` or `--ffmpeg-path`.
This is important, especially for faster-whisper.  When in doubt, manually specify the path!

📝 Set `WHISPER_MODEL_PATH` or `--whisper-model-path` for location of storage for whisper models.
Placing this in a static location will ensure it won't need to be downloaded when script is moved.
Defaults to current directory `.\whisper-models`

---

## 📥 Download

To get started with SoundOfSilence, download the script and related files from the official repository:

- **Source Repository**: Clone or download the script from [SoundOfSilence.py](SoundOfSilence.py).
  ```bash
  git clone https://github.com/bengalih/ABS-scripts.git

---

## ⚙️ Configuration

Configuration can be done by supplying command line paramaeters (see Common Options below).
Alternatively, edititing the script’s configuration class block before running will save all values.
Most of the defaults should not need changing.
See below sections for more information

```python
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
```



## 🛠️ Usage

Basic usage is simply
```bash
python SoundOfSilence.py audio_source
```
Where `audio_source` is an audio file or a folder containing audio files.

You can set config options within the python file (recommended), or use command line options to set/override.

Default settings should be fine for standard detection, but you should familiarize yourself with some options.
See the note on FFMpeg path configuration under Requirements.

### Common Options

| Option                      | Description                                                                 |
|-----------------------------|-----------------------------------------------------------------------------|
| `--ffmpeg-path`             | Path to FFmpeg `bin` directory                                              |
| `--whisper-model-path`      | Local path for Whisper models                                               |
| `--silence-threshold`       | Silence level (e.g., `-30dB`)                                               |
| `--silence-duration`        | Minimum silence duration (seconds)                                         |
| `--snippet-duration`        | Duration of extracted audio (seconds)                                      |
| `--target-words`            | Target keyword(s) (e.g., `chapter`, `section`)                              |
| `--target-first-word-only`  | Only detect keyword/number if it’s the first word                          |
| `--target-numbers-only`     | Only search for numbers                                                     |
| `--whisper-profile`         | Define the performance profile for transcription (fast, flexible, accurate) |
| `--whisper-model`           | Overrides the model from the profile with specified model (e.g.: base)      |
| `--whisper-prompt`          | Optional prompt for Whisper transcription                                   |
| `--whisper-device`          | Whisper device for inference (e.g.: cpu, gpu)                               |
| `--whisper-compute-type`    | Whisper compute type (e.g.: int8, float16)                                 |
| `--file-output`             | Save silence and chapter data to files                                     |
| `--file-output-text`        | Include transcribed text in chapter output                                 |
| `--text-fixup`              | Capitalize and fix punctuation in text                                     |
| `--test-run`                | Create shorter audio file for testing                                      |
| `--test-run-duration`       | Duration (in minutes) for test audio                                       |
| `--test-run-force`          | Force overwrite of prior test file                                         |
| `--debug`                   | Enable verbose debugging output                                            |

> 📝 When using  `--target-numbers-only` or `TARGET_NUMBERS_ONLY` the `TARGET_WORDS` are ignored and instead only numbers are searched.
>
> This is a useful option if section headings are simply spoken as numbers like "Five" or "32".
> 
> When using this option, it is recommended to set `--target-first-word-only` or `TARGET_FIRST_WORD_ONLY` to `True` for accuracy.
> However this will only detect sections up to 100.  Setting to `False` may be less accurate, but find sections numbered above 100.
>
> 📝 The use of multiple words for `TARGET_WORDS` or `--target-words` is supported as shown.  However phrases can also be used.
> such as "This is the end of disc".  While not fully tested, this seems to work, however be sure to set `TARGET_FIRST_WORD_ONLY` or `--target-first-word-only` to `False`

---

## 🧪 Examples

### Basic transcription with added words:
Will append specified `--target-words` onto `TARGET_WORDS` list
```bash
python SoundOfSilence.py audio.mp3 --target-words Introduction --target-words Epilogue
```

### Detect numbers only for section headings and debug:
```bash
python SoundOfSilence.py "Adventures of Huckleberry Finn"  --target-numbers-only true  --debug true
```

### Use a different profile and model:
```bash
python SoundOfSilence.py audio.mb4 --whisper-profile fast --whisper-model base
```

### Use custom silence threshold and snippet duration:
```bash
python SoundOfSilence.py audio.mp3 -silence-duration 1.5 --snippet-duration 8
```

---

## 📂 Output

When `--file-output` is enabled (default), the script generates:
- `*_silences.txt` – List of silence break timestamps
- `*_chapters.txt` – List of detected chapter timestamps and optionally the transcribed text

The `*_chapters.txt` file can be opened in any standard editor and the timestamps can be used to enter into ABS.
This can be a manual process, so you can leverage [AChE](AChE.md) to automatically import the chapters.
While you can import the file directly, you may want to open it up and manually verify or fixup chapters prior to imporatation.
You can, of course, also import them and fix them up within ABS as well.

To import with [AChE](AChE.md) you would run:

`ACHe.py --file audio_chapters.txt --item_id 3ea96595-67c2-4579-a64e-04f50f99e247`

`--item_id` is the ABS item identifier.  The easiest way to find this is to go to the book in your browser and look at the URL:

`https://audiobookshelf.domain.com/audiobookshelf/item/3ea96595-67c2-4579-a64e-04f50f99e247`

NOTE: You will first need to edit  ACHE.py to provide your server and credential information.

---

## 🚀 Performance and Accuracy

_Transcription is not an exact science_, nor are all audibooks formatted to a standard.
SoundOfSilence is efficient in that it looks for silence breaks with the assumption that section markers will be found close by.
The majority of audiobooks will follow this format with a 2-3+ delay between the end of a chapter and the beginning of the next one.
Some audiobooks may include music or non-standard openings to chapters which makes finding proper silence markers difficult.
This is different than some other tools which will attempt to transcribe the entire book.  While these tools may have better accuracy with some books,
they will take considerably longer to run especially if your hardware is not up to the task.

`SoundOfSilence` has sucessfully processed a 66 hour audiobook in ~15 minutes with 98%+ accuracy on an i7-3820QM processor (circa 2012).

- Setting the `SILENCE_THRESHOLD` longer will decrease the number of silences found and thus increase overall speed of execution.
However, this may miss some section breaks.  Setting it shorter will find more silences, but all those silences will need to be transcoded,
this will result in longer run times.  It is not recommended to set this below 1.

- Setting the `SNIPPET_DURATION` longer may also signigicantly decrease performance as `faster-whisper` needs more time to transcribe a longer segment.
Setting it shorter may improve performance, but miss out on keywords.  Sometimes it is necessary to set it above the default of 5 in order to bypass into music on sections.

- You can always implement the `--test-run` parameter which will work on only a snippet of the book first to see if your settings are close enough to get the whole book.

- The script is designed as a single thread/process/queue.  After silence detection, it extracts each detected silence in turn via `ffmpeg` and then transcribes with `faster-whisper`.
Some testing was done doing tasks in parallel, but no major improvements were found for an overly complex change in code.
Best performance will come with better system specs, and utilizing the best `WHISPER_DEVICE` and `WHISPER_COMPUTE_TYPE` for your setup.

- The `tiny` and `tiny.en` models were chosen for a balance of speed and performance depending on the `--whisper-profile` chosen.
However each dictionary may have it's own idiosyncrasies in how it detects words.
Using larger dictionaries (including `base`) may only introduce more confusion when searching for simple words, but you can try if required based upon target words.

- The version of `ffmpeg` you have on a system may also severely impact performance.
Versions of 7.x should offer good performance, and are recommended.
Some older versions (4.x) may actually offer some minor speed improvements and be sufficient for the purposes of this script.
Simply specify the proper directory in `FFMPEG_PATH` or `--ffmpeg-path` for the version to use with the script.

e.g:

 `--ffmpeg-path "c:\Program Files\ffmpeg\bin4"`

_ Windows users may have difficulty finding older releases.  I recommend searching for `ffmpeg-4.4.1-full_build.7z` to find an older version that seems to work fully and quickly.
 While this version may be years old, its functions for the purpose of this script seem sufficient._

- Other running processes on a system may also severly impact transcription performance which is CPU heavy.

- The best performance increases will be obtained with faster hardware.  Specifically a GPU (NVIDIA) which can take advantage of CUDA.
While I have not tested on this configuration it should be as simple as installing [PyTorch] (https://pytorch.org/get-started/locally/) with CUDA support.
Then, you may need to set `--whisper-device` to `gpu` if the default `auto` setting does not detect your GPU.
If `gpu` gives errors, you will need to diagnose those with `whisper` or `faster-whisper`.
 
---

## 🧾 License

This project is licensed under the **GNU General Public License v3.0**.

You are free to use, modify, and distribute this software under the following conditions:

- You **must credit** the original author  
- Any **modified versions must also be open source** under the same license  
- You **must include a copy** of the license in any distributions  

📄 See the full license at [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)

---

## 🙋‍♂️ Author

**bengalih**

Questions or improvements?
Contributions welcome!
