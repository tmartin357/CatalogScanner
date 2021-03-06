from common import ScanMode, ScanResult
from PIL import Image

import cv2
import functools
import imagehash
import json
import numpy
import os

from typing import Iterator, List

# The expected color for the video background.
BG_COLOR = (238, 217, 101)


class SongCover:
    """The image and data associated with a given song."""

    def __init__(self, song_name: str, hash_hex: str):
        self.song_name = song_name
        self.icon_hash = imagehash.hex_to_hash(hash_hex)

    def __repr__(self):
        return f'SongCover({self.song_name!r}, {self.hash_hex!r})'


def detect(frame: numpy.ndarray) -> bool:
    """Detects if a given frame is showing the music list."""
    color = frame[:20, 1220:1250].mean(axis=(0, 1))
    return numpy.linalg.norm(color - BG_COLOR) < 10


def scan(video_file: str, locale: str = 'en-us') -> ScanResult:
    """Scans a video of scrolling through music list and returns all songs found."""
    song_covers = parse_video(video_file)
    song_names = match_songs(song_covers)
    results = translate_names(song_names, locale)

    return ScanResult(
        mode=ScanMode.MUSIC,
        items=results,
        locale=locale.replace('auto', 'en-us'),
    )


def parse_video(filename: str) -> List[numpy.ndarray]:
    """Parses a whole video and returns images for all song covers found."""
    all_covers: List[numpy.ndarray] = []
    for i, frame in enumerate(_read_frames(filename)):
        for new_covers in _parse_frame(frame):
            if _is_duplicate_cards(all_covers, new_covers):
                continue  # Skip non-moving frames
            all_covers.extend(new_covers)
    return _remove_blanks(all_covers)


def match_songs(song_covers: List[numpy.ndarray]) -> List[str]:
    """Matches icons against database of music covers, finding best matches."""
    matched_songs = set()
    song_db = _get_song_db()
    for cover in song_covers:
        image = Image.fromarray(cover)
        test_hash = imagehash.phash(image, hash_size=18)
        best_match = min(song_db, key=lambda x: x.icon_hash - test_hash)
        matched_songs.add(best_match.song_name)
    return list(matched_songs)


def translate_names(song_names: List[str], locale: str) -> List[str]:
    """Translates a list of song names to the given locale."""
    if locale in ['auto', 'en-us']:
        return song_names

    translation_path = os.path.join('music', 'translations.json')
    with open(translation_path, encoding='utf-8') as fp:
        translations = json.load(fp)
    return [translations[name][locale] for name in song_names]


def _read_frames(filename: str) -> Iterator[numpy.ndarray]:
    """Parses frames of the given video and returns the relevant region."""
    cap = cv2.VideoCapture(filename)
    while True:
        ret, frame = cap.read()
        if not ret:
            break  # Video is over

        assert frame.shape[:2] == (720, 1280), \
            'Invalid resolution: {1}x{0}'.format(*frame.shape)

        if not detect(frame):
            continue  # Skip frames that are not showing music list.

        # Crop the region containing only song covers.
        yield frame[95:670, 40:1240]

    cap.release()


def _parse_frame(frame: numpy.ndarray) -> Iterator[List[numpy.ndarray]]:
    """Parses an individual frame and extracts song covers from the music list."""
    # Start vertical position for the 4 song covers.
    x_positions = [40, 327, 614, 900]

    # This code finds areas of the image that are sky blue (background color),
    # then it averages the frame across the Y-axis to find the area rows.
    # Lastly, it finds the y-positions marking the start/end of each row.
    thresh = cv2.inRange(frame[:410], (210, 200, 75), (255, 235, 125))
    separators = numpy.diff(thresh.mean(axis=1) > 100).nonzero()[0]
    if len(separators) < 2:
        return

    # We do a first pass finding all sensible y positions.
    y_centers = []
    for y1, y2 in zip(separators, separators[1:]):
        if 259 < y2 - y1 < 266:
            y_centers.extend([y1 % 287, (y2 + 25) % 287])
        if 20 < y2 - y1 < 27:
            y_centers.extend([y2 % 287, (y1 + 25) % 287])
    y_centroid = numpy.mean(y_centers) + 1
    y_positions = numpy.arange(y_centroid, 575, 287).astype(int)

    for y in y_positions:
        if y + 260 > frame.shape[0]:
            continue  # Past the bottom of the frame
        yield [frame[y:y+260, x:x+260] for x in x_positions]


def _is_duplicate_cards(all_covers: List[numpy.ndarray], new_covers: List[numpy.ndarray]) -> bool:
    """Checks if the new set of covers are the same as the previous seen covers."""
    if not all_covers or len(all_covers) < len(new_covers):
        return False

    new_concat = cv2.hconcat(new_covers)
    # Checks the last 2 rows for similarities to the newly added row.
    for ind in [slice(-4, None), slice(-8, -4)]:
        old_concat = cv2.hconcat(all_covers[ind])
        if old_concat is None:
            continue
        if cv2.absdiff(new_concat, old_concat).mean() < 15:
            return True
    return False


def _remove_blanks(all_icons: List[numpy.ndarray]) -> List[numpy.ndarray]:
    """Remove all icons that do not show a song cover."""
    filtered_icons = []
    for icon in all_icons:
        color = icon[5:25, 60:200].mean(axis=(0, 1))
        if numpy.linalg.norm(color - BG_COLOR) < 5:
            continue
        filtered_icons.append(icon)
    return filtered_icons


@functools.lru_cache()
def _get_song_db() -> List[SongCover]:
    """Fetches the song cover database for a given locale, with caching."""
    with open(os.path.join('music', 'names.json')) as fp:
        music_data = json.load(fp)
    return [SongCover(name, hash_hex) for name, _, hash_hex in music_data]


if __name__ == "__main__":
    results = scan('examples/music.mp4')
    print('\n'.join(results.items))
