"""Test package for LibraForge."""
import os

# No live Audible genre-tree fetch from the compile path (app/store_genres.py).
os.environ.setdefault("LIBRAFORGE_STORE_GENRE_FETCH", "0")
