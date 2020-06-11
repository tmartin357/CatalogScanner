import collections
import cv2
import functools
import json
import numpy
import os

from typing import Dict, Iterator, List, Tuple

# Mapping from background colors (in BGR for cv2) to card type.
CARD_TYPES: Dict[Tuple[int, int, int], str] = {
    (174, 220, 228): 'beige',
    (229, 213, 189): 'blue',
    (113, 159, 183): 'brick',
    (65, 106, 143): 'brown',
    (110, 108, 108): 'dark-gray',
    (123, 199, 211): 'gold',
    (128, 225, 156): 'green',
    (188, 188, 187): 'light-gray',
    (109, 199, 239): 'orange',
    (185, 181, 238): 'pink',
    (87, 76, 204): 'red',
    (163, 160, 159): 'silver',
    (229, 233, 233): 'white',
    (125, 224, 229): 'yellow',
}


class RecipeCard:
    """The image and data associated with a given recipe."""

    def __init__(self, item_name, card_type):
        img_path = os.path.join('diys', 'generated', item_name + '.png')
        self.img = cv2.imread(img_path)[28:-28, :, :]
        self.item_name = item_name
        self.card_type = card_type

    def __repr__(self):
        return f'RecipeCard({self.item_name!r}, {self.card_type!r})'


def scan_recipes(video_file: str, locale: str = 'en-us') -> List[str]:
    """Scans a video of scrolling through DIY list and returns all recipes found."""
    recipe_cards = parse_video(video_file)
    matched_recipes = match_recipes(recipe_cards)
    return translate_names(matched_recipes, locale)


def parse_video(filename: str) -> List[numpy.ndarray]:
    """Parses a whole video and returns images for all recipe cards found."""
    all_cards: List[numpy.ndarray] = []
    for i, frame in enumerate(_read_frames(filename)):
        if i % 4 != 0:
            continue  # Skip every 4th frame
        for new_cards in _parse_frame(frame):
            if _is_duplicate_cards(all_cards, new_cards):
                continue  # Skip non-moving frames
            all_cards.extend(new_cards)
    return all_cards


def match_recipes(recipe_cards: List[numpy.ndarray]) -> List[str]:
    """Matches a list of names against a database of items, finding best matches."""
    matched_recipes = set()
    recipe_db = _get_recipe_db()
    for card in recipe_cards:
        card_type = _guess_card_type(card)
        best_match = _find_best_match(card, recipe_db[card_type])
        matched_recipes.add(best_match.item_name)
    return list(matched_recipes)


def translate_names(recipe_names: List[str], locale: str) -> List[str]:
    """Translates a list of recipe names to the given locale."""
    if locale in ['auto', 'en-us']:
        return recipe_names

    translation_path = os.path.join('diys', 'translations.json')
    with open(translation_path, encoding='utf-8') as fp:
        translations = json.load(fp)
    return [translations[name][locale] for name in recipe_names]


def _read_frames(filename: str) -> Iterator[numpy.ndarray]:
    """Parses frames of the given video and returns the relevant region."""
    cap = cv2.VideoCapture(filename)
    while True:
        ret, frame = cap.read()
        if not ret:
            break  # Video is over
        assert frame.shape[:2] == (720, 1280), \
            'Invalid resolution: {1}x{0}'.format(*frame.shape)
        yield frame[110:720, 45:730]  # Return relevant region
    cap.release()


def _parse_frame(frame: numpy.ndarray) -> Iterator[List[numpy.ndarray]]:
    """Parses an individual frame and extracts cards from the recipe list."""
    # Start/end horizontal position for the 5 DIY cards.
    x_positions = [(10, 122), (148, 260), (285, 397), (423, 535), (560, 672)]

    # This code finds areas of the image that are beige (background color),
    # then it averages the frame across the Y-axis to find the area rows.
    # Lastly, it finds the y-positions marking the start/end of each row.
    thresh = cv2.inRange(frame, (185, 215, 218), (210, 230, 237))
    separators = numpy.diff(thresh.mean(axis=1) > 200).nonzero()[0]
    y_positions = zip(separators, separators[1:])

    # Loop over pair of start/end positions:
    for y1, y2 in y_positions:
        if not (180 < y2 - y1 < 200):
            continue  # Invalid card size

        row = []
        for x1, x2 in x_positions:
            card = frame[y1+36:y1+148, x1:x2]
            # Detects selected cards, which are bigger, and resizes them.
            if thresh[y1-10:y1-5, x1:x2].mean() < 100:
                card = frame[y1+22:y1+152, x1-9:x2+9]
                card = cv2.resize(card, (112, 112))
            row.append(card)
        yield row


def _is_duplicate_cards(all_cards: List[numpy.ndarray], new_cards: List[numpy.ndarray]) -> bool:
    """Checks if the new set of cards are the same as the previous seen cards."""
    if not new_cards or len(all_cards) < len(new_cards):
        return False

    new_concat = cv2.hconcat(new_cards)
    # Checks the last 3 rows for similarities to the newly added row.
    for ind in [slice(-5, None), slice(-10, -5), slice(-15, -10)]:
        old_concat = cv2.hconcat(all_cards[ind])
        if old_concat is None:
            continue
        if cv2.absdiff(new_concat, old_concat).mean() < 15:
            return True
    return False


@functools.lru_cache()
def _get_recipe_db() -> Dict[str, List[RecipeCard]]:
    """Fetches the item database for a given locale, with caching."""
    with open(os.path.join('diys', 'names.json')) as fp:
        diy_data = json.load(fp)

    recipe_db = collections.defaultdict(list)
    for item_name, _, card_type in diy_data:
        recipe = RecipeCard(item_name, card_type)
        recipe_db[card_type].append(recipe)

    # Merge orange, pink and yellow since they are often mixed up.
    merged = recipe_db['orange'] + recipe_db['pink'] + recipe_db['yellow']
    recipe_db['orange'] = recipe_db['pink'] = recipe_db['yellow'] = merged

    return recipe_db


def _guess_card_type(card: numpy.ndarray) -> str:
    """Guessed the recipe type by the card's background color."""
    # Cut a small piece from the corner and calculate the average color.
    bg_color = card[106:, 60:70, :].mean(axis=(0, 1))

    # Find the closest match in the list of known card types.
    distance_func = lambda x: numpy.linalg.norm(numpy.array(x) - bg_color)
    best_match = min(CARD_TYPES.keys(), key=distance_func)
    return CARD_TYPES[best_match]


def _find_best_match(card: numpy.ndarray, recipes: List[RecipeCard]) -> RecipeCard:
    """Finds the closest matching recipe for the given card."""
    fast_similarity_metric = lambda r: cv2.absdiff(card, r.img).mean()
    similarities = list(map(fast_similarity_metric, recipes))
    sim1, sim2 = numpy.partition(similarities, kth=2)[:2]

    # If the match seems obvious, return the quick result.
    if abs(sim1 - sim2) > 3:
        return recipes[numpy.argmin(similarities)]

    # Otherwise, we use a slower matching, which tries various shifts.
    def slow_similarity_metric(recipe, debug=False):
        diffs = []
        for y in [-2, -1, 0, 1]:
            shifted = numpy.roll(card, y, axis=0)
            diffs.append(cv2.absdiff(shifted, recipe.img).sum())
        return min(diffs)  # Return lowest diff across shifts.

    similarities = list(map(slow_similarity_metric, recipes))
    return recipes[numpy.argmin(similarities)]
