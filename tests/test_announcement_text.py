"""Dependency-free acceptance tests; run python -B -m unittest discover -s tests -v."""

import unittest

try:
    from gulbot.announcements import numbers
except ImportError:
    numbers = None
try:
    from gulbot.announcements import lexicon
except ImportError:
    lexicon = None

VALID = [
    ("nol", 0),
    ("bir", 1),
    ("ikki", 2),
    ("uch", 3),
    ("to'rt", 4),
    ("besh", 5),
    ("olti", 6),
    ("yetti", 7),
    ("sakkiz", 8),
    ("to'qqiz", 9),
    ("o'n", 10),
    ("yigirma", 20),
    ("o'ttiz", 30),
    ("qirq", 40),
    ("ellik", 50),
    ("oltmish", 60),
    ("yetmish", 70),
    ("sakson", 80),
    ("to'qson", 90),
    ("ellik bitta", 51),
    ("ellik bir dona", 51),
    ("ellikta", 50),
    ("ikkita", 2),
    ("to'rtta", 4),
    ("uchta", 3),
    ("yuz", 100),
    ("bir yuz", 100),
    ("to'rt yuz ellik ming so'm", 450000),
    ("450 ming so'm", 450000),
    ("4 yuz 50 ming", 450000),
    ("bir million ikki yuz ellik ming", 1250000),
    ("1,5 million", 1500000),
    ("1.5 mln", 1500000),
    ("1,25 million", 1250000),
    ("yarim million", 500000),
    ("bir yarim million", 1500000),
    ("ikki yarim ming", 2500),
    ("0,5 ming", 500),
    ("million", 1000000),
    ("450\t000 som", 450000),
    ("450\n000 som", 450000),
    ("1 500 000 so'm", 1500000),
    ("450.000", 450000),
    ("450,000", 450000),
    ("1,500,000", 1500000),
    ("450\u00a0000", 450000),
    ("1000", 1000),
    ("Эллик битта", 51),
    ("тўрт юз эллик минг сўм", 450000),
    ("ярим миллион", 500000),
    ("бир ярим миллион", 1500000),
    ("тўққиз юз тўқсон тўққиз", 999),
    ("450 минг сум", 450000),
    ("to‘rt yuz ellik ming soʻm", 450000),
    ("to`rt yuz ellik ming so’m", 450000),
    ("tort yuz ellik ming som", 450000),
    ("ellik birta", 51),
    ("bir milliard ikki million uch ming to'rt", 1002003004),
    ("bir million ming bir", 1001001),
    ("１,５ million", 1500000),
]
INVALID = [
    "",
    "atirgul",
    "narxi kelishiladi",
    "ellik bitta atirgul",
    "bir ikki",
    "ellik yigirma",
    "yuz yuz",
    "ming ming",
    "ming million",
    "ikki yuz yuz",
    "-450 ming",
    "+450 ming",
    "1,5",
    "yarim",
    "1/2 million",
    "1e6",
    "NaN",
    "0,0005 ming",
    "bir yoki ikki",
    "bir-ikki",
    "1.2.3 million",
    "1 50 000",
    "bir million ikki million",
    "ikki nol",
    "yuz ikki yuz",
    "9999999999999999999999999999",
    "narxi 450 ming",
    "450 rub",
    "million yarim",
    "1.500,00",
    "1,500.00",
]


class NumberTests(unittest.TestCase):
    def test_spans_preserve_input(self):
        self.assertIsNotNone(numbers)
        text = "Qizil atirgul, ellik bitta dona, narxi to’rt yuz ellik ming so’m."
        found = numbers.find_numbers(text)
        self.assertEqual([m.value for m in found], [51, 450000])
        self.assertEqual(
            [text[m.start : m.end] for m in found], ["ellik bitta", "to’rt yuz ellik ming"]
        )

    def test_phone_and_date_not_field_candidates(self):
        self.assertIsNotNone(numbers)
        text = "51 dona, narxi 450 ming so'm, tel +998 90 123 45 67, 12/10/2026"
        self.assertEqual([m.value for m in numbers.find_numbers(text)], [51, 450000])

    def test_invalid_run_not_partially_salvaged(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.find_numbers("narxi bir ikki ming so'm"), [])

    def test_separate_amounts_not_combined(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(
            [m.value for m in numbers.find_numbers("51 dona va 450 ming so'm")], [51, 450000]
        )

    def test_unlabelled_national_phone_is_masked(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.find_numbers("901234567 va 90 123 45 67"), [])

    def test_glued_identifier_is_not_a_number(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.find_numbers("8mart 1e6 450ming"), [])

    def test_cyrillic_number_scan(self):
        self.assertIsNotNone(numbers)
        self.assertEqual([m.value for m in numbers.find_numbers("эллик битта дона")], [51])

    def test_negative_amount_is_not_salvaged(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.find_numbers("narxi -450 ming so'm"), [])

    def test_fraction_is_not_salvaged(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.find_numbers("narxi 1/2 million so'm"), [])

    def test_digit_counter_scan(self):
        self.assertIsNotNone(numbers)
        self.assertEqual([m.value for m in numbers.find_numbers("51ta atirgul")], [51])

    def test_scan_limits(self):
        self.assertIsNotNone(numbers)
        with self.assertRaises(ValueError):
            numbers.find_numbers("a" * 4097)

    def test_exhaustive_two_digit_cardinals(self):
        self.assertIsNotNone(numbers)
        tens = [
            ("o'n", 10),
            ("yigirma", 20),
            ("o'ttiz", 30),
            ("qirq", 40),
            ("ellik", 50),
            ("oltmish", 60),
            ("yetmish", 70),
            ("sakson", 80),
            ("to'qson", 90),
        ]
        units = ["bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
        for prefix, base in tens:
            for unit, value in zip(units, range(1, 10), strict=False):
                self.assertEqual(numbers.parse_number(prefix + " " + unit), base + value)


class LexiconTests(unittest.TestCase):
    def matcher(self, **kwargs):
        self.assertIsNotNone(lexicon)
        return lexicon.LexiconMatcher(**kwargs)

    def test_multiple_flowers_and_colour_spans(self):
        text = "QIZIL atirgullar va oq тюльпаны, maxsus quti bilan."
        matches = self.matcher().find(text)
        self.assertEqual(
            [(m.kind, m.canonical) for m in matches],
            [("colour", "qizil"), ("flower", "atirgul"), ("colour", "oq"), ("flower", "tyulpan")],
        )
        self.assertEqual(
            [text[m.start : m.end] for m in matches], ["QIZIL", "atirgullar", "oq", "тюльпаны"]
        )

    def test_count_word_cannot_become_colour_by_fuzzy_matching(self):
        self.assertIsNone(self.matcher().match("to'qqizta"))
        self.assertEqual(
            [(m.kind, m.canonical) for m in self.matcher().find("Oq pion to'qqizta")],
            [("colour", "oq"), ("flower", "pion")],
        )

    def test_numeric_shop_alias_cannot_override_number(self):
        self.assertIsNone(self.matcher(shop_aliases={"ellik": "atirgul"}).match("ellik"))

    def test_domain_words_do_not_rewrite_description(self):
        text = "atrgul; Zarina uchun noodatiy maxsus quti <b>!!!"
        self.matcher().find(text)
        self.assertEqual(text, "atrgul; Zarina uchun noodatiy maxsus quti <b>!!!")

    def test_cyrillic_count_suffix(self):
        self.assertIsNotNone(numbers)
        self.assertEqual(numbers.parse_number("тўртта"), 4)

    def test_phrase_does_not_cross_punctuation(self):
        matches = self.matcher().find("och, pushti")
        self.assertNotIn("ochpushti", [m.canonical for m in matches])

    def test_aliases_do_not_cross_punctuation(self):
        self.assertIsNone(self.matcher().match("atirgul<script>"))

    def test_every_curated_alias_has_exact_mapping(self):
        self.assertIsNotNone(lexicon)
        m = self.matcher()
        for table in (lexicon.FLOWERS, lexicon.COLOURS):
            for canonical, aliases in table.items():
                for word in (canonical, *aliases):
                    match = m.match(word)
                    self.assertIsNotNone(match)
                    self.assertEqual(match.canonical, canonical)
                    self.assertEqual(match.method, "exact")

    def test_shop_aliases_are_isolated(self):
        a = self.matcher(shop_aliases={"samira": "atirgul"})
        b = self.matcher()
        self.assertEqual(a.match("samira").canonical, "atirgul")
        self.assertIsNone(b.match("samira"))

    def test_occasion_aliases_not_flowers(self):
        m = self.matcher(
            shop_aliases={
                "birthday": "tugilgankun",
                "wedding": "toy",
                "8 март": "8mart",
                "роза": "atirgul",
            }
        )
        self.assertEqual(m.find("birthday wedding 8 март"), [])
        self.assertEqual(m.match("роза").canonical, "atirgul")

    def test_custom_flower_supported_explicitly(self):
        m = self.matcher(shop_aliases={"эустома": "eustoma"}, extra_flowers=("eustoma",))
        self.assertEqual(m.match("эустома").canonical, "eustoma")

    def test_conflicting_alias_is_ambiguous(self):
        m = self.matcher(shop_aliases={"атиргул": "tyulpan"})
        match = m.match("атиргул")
        self.assertIsNone(match.canonical)
        self.assertEqual(match.confidence, "low")
        self.assertEqual(set(match.alternatives), {"atirgul", "tyulpan"})

    def test_equal_distance_never_arbitrarily_picked(self):
        m = self.matcher(shop_aliases={"aaaa": "atirgul", "aabb": "tyulpan"})
        match = m.match("aaab")
        self.assertIsNone(match.canonical)
        self.assertEqual(set(match.alternatives), {"atirgul", "tyulpan"})

    def test_longest_alias_wins(self):
        m = self.matcher()
        matches = m.find("lola gul va och pushti")
        self.assertEqual(
            [(x.canonical, x.source) for x in matches],
            [("tyulpan", "lola gul"), ("ochpushti", "och pushti")],
        )

    def test_alias_mapping_not_modified(self):
        aliases = {"роза": "atirgul"}
        self.matcher(shop_aliases=aliases).find("роза")
        self.assertEqual(aliases, {"роза": "atirgul"})

    def test_bounded_inputs(self):
        m = self.matcher()
        with self.assertRaises(ValueError):
            m.find("a" * 4097)
        with self.assertRaises(ValueError):
            m.match("a" * 65)

    def test_bad_alias_rejected(self):
        with self.assertRaises(ValueError):
            self.matcher(shop_aliases={"": "atirgul"})


ALIASES = [
    ("atirgul", "atirgul", "flower", "high"),
    ("atrgul", "atirgul", "flower", "low"),
    ("atirgullar", "atirgul", "flower", "high"),
    ("atirgullarni", "atirgul", "flower", "high"),
    ("atirgulning", "atirgul", "flower", "high"),
    ("роза", "atirgul", "flower", "high"),
    ("розы", "atirgul", "flower", "high"),
    ("атиргул", "atirgul", "flower", "high"),
    ("roses", "atirgul", "flower", "high"),
    ("lola", "tyulpan", "flower", "high"),
    ("lola gul", "tyulpan", "flower", "high"),
    ("тюлпан", "tyulpan", "flower", "high"),
    ("krizantema", "xrizantema", "flower", "high"),
    ("хризантемы", "xrizantema", "flower", "high"),
    ("чиннигул", "chinnigul", "flower", "high"),
    ("пион", "pion", "flower", "high"),
    ("нилуфар", "nilufar", "flower", "high"),
    ("герберы", "gerbera", "flower", "high"),
    ("гулдаста", "buket", "flower", "high"),
    ("qizil", "qizil", "colour", "high"),
    ("қизил", "qizil", "colour", "high"),
    ("красный", "qizil", "colour", "high"),
    ("oq", "oq", "colour", "high"),
    ("оқ", "oq", "colour", "high"),
    ("белые", "oq", "colour", "high"),
    ("pushti", "pushti", "colour", "high"),
    ("пушти", "pushti", "colour", "high"),
    ("розовый", "pushti", "colour", "high"),
    ("ko‘k", "kok", "colour", "high"),
    ("koʻk", "kok", "colour", "high"),
    ("кўк", "kok", "colour", "high"),
    ("жёлтый", "sariq", "colour", "high"),
    ("to‘q qizil", "toqqizil", "colour", "high"),
    ("оч пушти", "ochpushti", "colour", "high"),
]
REJECTED_WORDS = [
    "narxi",
    "450",
    "som",
    "ming",
    "Zarina",
    "box",
    "gul",
    "on",
    "oqs",
    "redacted",
    "<script>",
    "ro",
    "dona",
]


def add_cases():
    for i, (text, expected) in enumerate(VALID):

        def valid(self, text=text, expected=expected):
            self.assertIsNotNone(numbers)
            self.assertEqual(numbers.parse_number(text), expected)

        setattr(NumberTests, f"test_valid_{i:03d}", valid)
    for i, text in enumerate(INVALID):

        def invalid(self, text=text):
            self.assertIsNotNone(numbers)
            with self.assertRaises(ValueError):
                numbers.parse_number(text)

        setattr(NumberTests, f"test_invalid_{i:03d}", invalid)
    for i, (text, canonical, kind, confidence) in enumerate(ALIASES):

        def matched(self, text=text, canonical=canonical, kind=kind, confidence=confidence):
            m = self.matcher().match(text)
            self.assertIsNotNone(m)
            self.assertEqual((m.canonical, m.kind, m.confidence), (canonical, kind, confidence))

        setattr(LexiconTests, f"test_alias_{i:03d}", matched)
    for i, text in enumerate(REJECTED_WORDS):

        def rejected(self, text=text):
            self.assertIsNone(self.matcher().match(text))

        setattr(LexiconTests, f"test_rejected_{i:03d}", rejected)


add_cases()
if __name__ == "__main__":
    unittest.main()
