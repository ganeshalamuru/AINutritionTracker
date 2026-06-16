"""Ingredient-name normalization vocabularies used while matching against USDA.

These feed the query-rewriting and head-noun-gate logic in nutrition_db.py; they hold
no logic themselves.
"""

# Stripped (after the comma) when retrying a miss with a simpler query.
COOKING_ADJECTIVES = {
    "cooked",
    "raw",
    "fried",
    "boiled",
    "roasted",
    "grilled",
    "steamed",
    "fresh",
    "baked",
    "sauteed",
    "sautéed",
}

# Words _simplify() strips on the loose retry. Adds non-cooking descriptors
# ("powder"/"stick"/"seed"/...) on top of the cooking adjectives, so an un-aliased
# "cumin powder" retries loosely as "cumin" (USDA's entry is "Spices, cumin seed",
# which strict requireAllWords=True can't match). Only fires after a strict miss.
SIMPLIFY_STRIP_WORDS = COOKING_ADJECTIVES | {
    "powder",
    "stick",
    "ground",
    "seed",
    "whole",
    "sliced",
    "chopped",
    "dried",
}

# Non-distinctive words: ignored when deriving the "food noun" a match must contain,
# so 'mint leaves' keys on 'mint' (not 'leaves') and 'rice white cooked' keys on 'rice'.
GENERIC_WORDS = {
    "leaves",
    "leaf",
    "powder",
    "ground",
    "dried",
    "fresh",
    "raw",
    "cooked",
    "fried",
    "boiled",
    "drained",
    "roasted",
    "grilled",
    "steamed",
    "baked",
    "whole",
    "plain",
    "sliced",
    "chopped",
    "oil",
    "nfs",
    "white",
    "red",
    "green",
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
    # Bulb onion. "onions cooked" alone resolves to GREEN onions (scallions); the
    # boiled/drained query lands the actual cooked bulb onion (~42 cal/100g). Frying oil,
    # if any, is counted separately as an oil ingredient.
    "onion": "onions cooked boiled drained",
    "fried onion": "onions cooked boiled drained",
    "onion, fried": "onions cooked boiled drained",
    "onions": "onions cooked boiled drained",
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
    "dal": "lentils mature boiled",
    "daal": "lentils mature boiled",
    "lentils": "lentils mature boiled",
    # Dals / legumes the decomposition step emits.
    # USDA has no urad/black gram entry — fall back to generic cooked lentils.
    "urad dal": "lentils mature boiled",
    "urad": "lentils mature boiled",
    "black gram": "lentils mature boiled",
    "toor dal": "pigeon peas cooked",
    "tur dal": "pigeon peas cooked",
    "arhar": "pigeon peas cooked",
    "pigeon peas": "pigeon peas cooked",
    "chana dal": "chickpeas cooked",
    "bengal gram": "chickpeas cooked",
    "chickpeas": "chickpeas cooked",
    "moong dal": "mung beans mature boiled",
    "mung dal": "mung beans mature boiled",
    "green gram": "mung beans mature boiled",
    "chicken": "chicken breast cooked roasted",
    "chicken breast": "chicken breast cooked roasted",
    "chicken breast, cooked": "chicken breast cooked roasted",
    # "egg whole cooked" resolves to the FRIED entry (~196 cal, assumes oil); the
    # hard-boiled query is the neutral generic (~155 cal/100g).
    "egg": "hard boiled egg",
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
    # --- Common pan-Indian aromatics, vegetables, nuts, dairy, fats & proteins ---
    # Added 2026-06; every value verified against the live USDA API via check_aliases.py.
    "garlic": "garlic raw",
    "ginger": "ginger root raw",
    "cauliflower": "cauliflower cooked",
    "gobi": "cauliflower cooked",
    "okra": "okra cooked",
    "bhindi": "okra cooked",
    "ladies finger": "okra cooked",
    "eggplant": "eggplant cooked",
    "brinjal": "eggplant cooked",
    "baingan": "eggplant cooked",
    "aubergine": "eggplant cooked",
    "bell pepper": "peppers sweet green cooked",
    "capsicum": "peppers sweet green cooked",
    "mushroom": "mushrooms cooked",
    "mushrooms": "mushrooms cooked",
    "cashews": "cashew nuts raw",
    "cashew": "cashew nuts raw",
    "kaju": "cashew nuts raw",
    "almonds": "almonds raw",
    "almond": "almonds raw",
    "badam": "almonds raw",
    "peanuts": "peanuts raw",
    "peanut": "peanuts raw",
    "groundnut": "peanuts raw",
    "groundnuts": "peanuts raw",
    "raisins": "raisins",
    "kishmish": "raisins",
    "sesame": "sesame seeds",
    "sesame seeds": "sesame seeds",
    "til": "sesame seeds",
    "cream": "cream heavy",
    "fresh cream": "cream heavy",
    "malai": "cream heavy",
    # "coconut milk" alone resolves to the sweetened beverage (~31 cal); "canned" lands
    # the cooking coconut milk used in curries (~197 cal/100g).
    "coconut milk": "coconut milk canned",
    "mustard oil": "mustard oil",
    "besan": "chickpea flour",
    "gram flour": "chickpea flour",
    "maida": "wheat flour white",
    "all purpose flour": "wheat flour white",
    "refined flour": "wheat flour white",
    # Jaggery has no USDA entry; granulated sugar is a close calorie proxy (~385/100g).
    "jaggery": "granulated sugar",
    "gur": "granulated sugar",
    "fish": "fish cooked",
    "shrimp": "shrimp cooked",
    "prawn": "shrimp cooked",
    "prawns": "shrimp cooked",
    "lamb": "lamb cooked",
    "mutton": "lamb cooked",
    "goat": "lamb cooked",
    "goat meat": "lamb cooked",
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
    "cardamom": "cardamom",
    "elaichi": "cardamom",
    "cloves": "cloves ground",
    "laung": "cloves ground",
    "bay leaf": "bay leaf",
    "bay leaves": "bay leaf",
    "tej patta": "bay leaf",
    "fennel": "fennel seed",
    "fennel seeds": "fennel seed",
    "saunf": "fennel seed",
    "fenugreek": "fenugreek seed",
    "fenugreek seeds": "fenugreek seed",
    "methi seeds": "fenugreek seed",
    "mustard seeds": "mustard seed",
    "mustard seed": "mustard seed",
    "rai": "mustard seed",
}

# Composite DISH names -> a USDA-friendly (FNDDS) query. Tried BEFORE decomposing a
# dish into ingredients: USDA's Survey (FNDDS) database carries many Indian dishes as
# whole items, and a single "idli" lookup (scaled by the dish's portion grams) is far
# more accurate than summing mis-stated base ingredients (e.g. idli is a fermented,
# steamed batter — not plain cooked rice + cooked lentils). A dish that doesn't resolve
# here simply falls back to ingredient decomposition, so unverified entries are safe
# (just a wasted search). Curate against the real API with check_aliases.py before
# adding entries — keep only dishes that actually match in FNDDS.
DISH_ALIASES = {
    "idli": "idli",
    "idly": "idli",
    "dosa": "dosa",
    "masala dosa": "dosa",
    "plain dosa": "dosa",
    "sambar": "sambar",
    "sambhar": "sambar",
    "vada": "vada",
    "medu vada": "vada",
    "upma": "upma",
    "paratha": "paratha",
    "aloo paratha": "paratha",
    "chapati": "chapati",
    "roti": "chapati",
    "naan": "naan",
    "biryani": "biryani",
    "chicken biryani": "chicken biryani",
    "vegetable biryani": "vegetable biryani",
    # Pulao: "rice pilaf" resolved to a DRY unprepared mix (~359 cal); plain "fried rice" was
    # worse — the head-noun gate (noun=rice) let "Rice bowl with chicken, frozen entree" pass and
    # it outranked the meatless row on data type, so a veg dish landed a chicken entree. Pin the
    # discriminator last ("...meatless") so the gate keeps only "Rice, fried, meatless" (FNDDS).
    "pulao": "rice fried meatless",
    "pulav": "rice fried meatless",
    "vegetable pulao": "rice fried meatless",
    "veg pulao": "rice fried meatless",
    "dal": "dal",
    "daal": "dal",
    "palak paneer": "palak paneer",
    "chicken curry": "chicken curry",
    "butter chicken": "chicken curry",
    "samosa": "samosa",
    "pakora": "pakora",
    "pakoda": "pakora",
    "fish curry": "fish curry",
    "vegetable curry": "vegetable curry",
    "veg curry": "vegetable curry",
    "mixed vegetable curry": "vegetable curry",
    "kheer": "rice pudding",
    "rice kheer": "rice pudding",
    "payasam": "rice pudding",
    "idli sambar": "idli",
    # Indian sweets. FNDDS carries ladoo/barfi natively; jalebi≈funnel cake and gulab
    # jamun≈jelly doughnut are close fried-sweet proxies (real ~340–400 cal/100g). All four
    # verified against the offline index + check_aliases.py (2026-06). Curating them runs the
    # dish-first lookup, so the whole portion resolves instead of the model's unreliable
    # decomposition (e.g. gulab jamun → "deep-fried dumplings", a USDA miss → 0 nutrients).
    "ladoo": "ladoo",
    "laddu": "ladoo",
    "besan ladoo": "ladoo",
    "boondi ladoo": "ladoo",
    "barfi": "barfi",
    "burfi": "barfi",
    "jalebi": "funnel cake",
    "jilebi": "funnel cake",
    "gulab jamun": "jelly doughnut",
    "gulab jamoon": "jelly doughnut",
    "gulab jaman": "jelly doughnut",
    # Verified 0-hit in FNDDS (check_aliases.py, 2026-06) and therefore intentionally NOT
    # aliased — they skip the speculative dish lookup and decompose to ingredients instead:
    #   chana masala, chole, rajma, paneer curry, raita, pongal, poha, uttapam, dal makhani,
    #   aloo gobi, korma, chicken/lamb/goat tikka masala, khichdi, rasam, kadhi, pav bhaji,
    #   dhokla, halwa, lassi, lemon/tamarind/curd rice, chutneys. rasgulla and halwa have no
    #   honest calorie proxy (spongy chenna ~180; halwa varies sooji/carrot/moong), so they
    #   stay unmatched rather than report a wrong number.
}
