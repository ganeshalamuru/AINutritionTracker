"""Ingredient-name normalization vocabularies used while matching against USDA.

These feed the query-rewriting and head-noun-gate logic in nutrition_db.py; they hold
no logic themselves.
"""

# Stripped (after the comma) when retrying a miss with a simpler query.
COOKING_ADJECTIVES = {
    "cooked", "raw", "fried", "boiled", "roasted", "grilled", "steamed",
    "fresh", "baked", "sauteed", "sautéed",
}

# Words _simplify() strips on the loose retry. Adds non-cooking descriptors
# ("powder"/"stick"/"seed"/...) on top of the cooking adjectives, so an un-aliased
# "cumin powder" retries loosely as "cumin" (USDA's entry is "Spices, cumin seed",
# which strict requireAllWords=True can't match). Only fires after a strict miss.
SIMPLIFY_STRIP_WORDS = COOKING_ADJECTIVES | {
    "powder", "stick", "ground", "seed", "whole", "sliced", "chopped", "dried",
}

# Non-distinctive words: ignored when deriving the "food noun" a match must contain,
# so 'mint leaves' keys on 'mint' (not 'leaves') and 'rice white cooked' keys on 'rice'.
GENERIC_WORDS = {
    "leaves", "leaf", "powder", "ground", "dried", "fresh", "raw", "cooked",
    "fried", "boiled", "roasted", "grilled", "steamed", "baked", "whole",
    "plain", "sliced", "chopped", "oil", "nfs", "white", "red", "green",
}

# Common (esp. Indian) ingredient names the model emits -> a concise, USDA-friendly
# generic/cooked query. The alias only rewrites the SEARCH; results still pass the
# head-noun gate, and the cache stays keyed by the original ingredient name.
FOOD_ALIASES = {
    "rice": "rice white cooked",
    "white rice": "rice white cooked",
    "cooked rice": "rice white cooked",
    "basmati rice": "rice white cooked",
    "boiled rice": "rice white cooked",
    "brown rice": "brown rice cooked",
    "yogurt": "yogurt plain whole",
    "curd": "yogurt plain whole",
    "dahi": "yogurt plain whole",
    "paneer": "cheese paneer",
    "ghee": "butter ghee",
    "butter": "salted butter",
    "onion": "onions cooked",
    "fried onion": "onions cooked",
    "onion, fried": "onions cooked",
    "onions": "onions cooked",
    "mint": "spearmint fresh",
    "mint leaves": "spearmint fresh",
    "coriander": "coriander leaves raw",
    "cilantro": "coriander leaves raw",
    "tomato": "tomatoes raw",
    "tomatoes": "tomatoes raw",
    "potato": "potatoes boiled",
    "carrot": "carrots raw",
    "carrots": "carrots raw",
    "peas": "peas green cooked",
    "green peas": "peas green cooked",
    "mixed vegetables": "mixed vegetables cooked",
    "vegetables": "mixed vegetables cooked",
    "roti": "chapati roti",
    "chapati": "chapati roti",
    "wheat roti": "chapati roti",
    "naan": "bread naan",
    "dal": "lentils cooked",
    "daal": "lentils cooked",
    "lentils": "lentils cooked",
    # Dals / legumes the decomposition step emits.
    # USDA has no urad/black gram entry — fall back to generic cooked lentils.
    "urad dal": "lentils cooked",
    "urad": "lentils cooked",
    "black gram": "lentils cooked",
    "toor dal": "pigeon peas cooked",
    "tur dal": "pigeon peas cooked",
    "arhar": "pigeon peas cooked",
    "pigeon peas": "pigeon peas cooked",
    "chana dal": "chickpeas cooked",
    "bengal gram": "chickpeas cooked",
    "chickpeas": "chickpeas cooked",
    "moong dal": "mung beans cooked",
    "mung dal": "mung beans cooked",
    "green gram": "mung beans cooked",
    "chicken": "chicken breast cooked roasted",
    "chicken breast": "chicken breast cooked roasted",
    "chicken breast, cooked": "chicken breast cooked roasted",
    "egg": "egg whole cooked",
    "milk": "milk whole",
    "apple": "apples raw",
    "apples": "apples raw",
    "banana": "bananas raw",
    "bananas": "bananas raw",
    # Other base ingredients from decomposition.
    "coconut": "coconut raw",
    "tamarind": "tamarinds raw",
    "green chili": "chili peppers raw",
    "chili": "chili peppers raw",
    "chilli": "chili peppers raw",
    "coffee": "brewed coffee",
    "filter coffee": "brewed coffee",
    "vegetable oil": "vegetable oil nfs",
    "oil": "vegetable oil nfs",
    "sugar": "granulated sugar",
    "semolina": "semolina",
    "rava": "semolina",
    "sooji": "semolina",
    # Spices — the model emits "<spice> powder/stick"; USDA files them under
    # "Spices, <spice>, ground/seed", so strict search on the model's phrasing
    # misses. Map to the USDA wording. (Verify with check_aliases.py after edits.)
    "turmeric": "turmeric ground",
    "turmeric powder": "turmeric ground",
    "haldi": "turmeric ground",
    "red chili powder": "chili powder",
    "red chilli powder": "chili powder",
    "chili powder": "chili powder",
    "chilli powder": "chili powder",
    "cumin": "cumin seed",
    "cumin powder": "cumin seed",
    "jeera": "cumin seed",
    "cinnamon": "cinnamon ground",
    "cinnamon stick": "cinnamon ground",
    "cinnamon powder": "cinnamon ground",
    "coriander powder": "coriander seed",
    "black pepper": "pepper black",
    "pepper": "pepper black",
}
