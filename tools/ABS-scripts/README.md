# ABS-scripts

A collection of Python scripts for automating [Audiobookshelf](https://www.audiobookshelf.org/) maintenance tasks.

## ABS Scripts
The following scripts are specific to ABS management only:

- [AyFu!](AyFu.md) — **AudioBookShelf Year Fix Up!** - Update book year with actual original published date of book (instead of audiobook release).
- [AeRu?](AeRu.md) — **AudioBookShelf Email Report Update** - Send email updates for all users with configured emails for new books added within X days.
- [AChE](AChE.md) — **AudioBookShelf Chapter Editor** - Download chapter data for easy manipulaton and importation.
- [ApTaGu](ApTaGu.md) — **AudioBookShelf Path Tag and Genre Updater** - Add remove tags or genres based on file path patterns.  Useful for tagging all books based on their location in a file structure.

## Assorted Scripts
These scripts are for general management of audiobooks and not specific for ABS only:
- [SoundOfSilence](SoundOfSilence.md) — **Sound Of Silence** - Outputs timestamps based on keyword detection at silence breaks.  Used to find proper chapter breaks based on Whisper transcription.

⚠️ **Warning:**

These scripts may make changes to your ABS metadata (and, if enabled your media files).
While they are well tested, issues may occur.
I recommend you test on small samples first and always have a good backup of your data (you can backup ABS metadata from within ABS settings)

Use these scripts at your own risk. I am not responsible for any loss or damage to your data.

## Links to other ABS resources:
- [abstoolbox](https://github.com/vito0912/abstoolbox)
- [abs-autoconverter](https://github.com/Vito0912/abs-autoconverter)
- [AudioBookShelf-genre-cleaner](https://github.com/gvarph/AudioBookShelf-genre-cleaner)
- [Audiobookshelf Organizer](https://github.com/jeeftor/audiobook-organizer)
