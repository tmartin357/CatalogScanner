from common import ScanResult
from typing import Any, Dict

import catalog
import critters
import music
import reactions
import recipes

import cv2

from absl import app
from absl import flags
from absl import logging

SCANNERS: Dict[str, Any] = {
    'catalog': catalog,
    'critters': critters,
    'music': music,
    'reactions': reactions,
    'recipes': recipes,
}

FLAGS = flags.FLAGS
flags.DEFINE_enum('locale', 'auto', catalog.LOCALE_MAP.keys(),
                  'The locale to use for parsing item names.')
flags.DEFINE_bool('for_sale', None,
                  'If true, the scanner will skip items that are not for sale.')
flags.DEFINE_enum('mode', 'auto', ['auto'] + list(SCANNERS.keys()),
                  'The type of video to scan. Catalog refers to Nook shopping catalog '
                  'and recipes refers to DIY list. Auto tries to detect from the video frames.')


def scan_media(filename: str, mode: str = 'auto', locale: str = 'auto', for_sale: bool = False) -> ScanResult:
    if mode == 'auto':
        mode = _detect_media_type(filename)
        logging.info('Detected video mode: %s', mode)

    if mode not in SCANNERS:
        raise RuntimeError('Invalid mode: %r' % mode)

    kwargs = {}
    if mode == 'catalog':
        kwargs['for_sale'] = for_sale

    return SCANNERS[mode].scan(filename, locale=locale, **kwargs)


def _detect_media_type(filename: str) -> str:
    video_capture = cv2.VideoCapture(filename)

    # Check the first ~3s of the video.
    for _ in range(100):
        success, frame = video_capture.read()
        if not success or frame is None:
            break

        # Resize 1080p screenshots to 720p to match videos.
        if filename.endswith('.jpg') and frame.shape[:2] == (1080, 1920):
            frame = cv2.resize(frame, (1280, 720))

        assert frame.shape[:2] == (720, 1280), \
            'Invalid resolution: {1}x{0}'.format(*frame.shape)

        for mode, scanner in SCANNERS.items():
            if scanner.detect(frame):
                return mode

    raise AssertionError('Video is not showing a known scan type.')


def main(argv):
    if len(argv) > 1:
        media_file = argv[1]
    elif FLAGS.mode == 'recipes':
        media_file = 'examples/recipes.mp4'
    elif FLAGS.mode == 'critters':
        media_file = 'examples/critters.mp4'
    elif FLAGS.mode == 'reactions':
        media_file = 'examples/reactions.jpg'
    elif FLAGS.mode == 'music':
        media_file = 'examples/music.mp4'
    else:
        media_file = 'examples/catalog.mp4'

    result = scan_media(
        media_file,
        mode=FLAGS.mode,
        locale=FLAGS.locale,
        for_sale=FLAGS.for_sale,
    )

    result_count, result_mode = len(result.items), result.mode.name.lower()
    print(f'Found {result_count} items in {result_mode} [{result.locale}]')
    print('\n'.join(result.items))


if __name__ == "__main__":
    app.run(main)
