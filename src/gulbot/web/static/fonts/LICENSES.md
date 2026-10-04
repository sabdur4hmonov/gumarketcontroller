# Fonts on the public pages

Every font here is from Google Fonts and is licensed under the **SIL Open Font
License 1.1**. The license text, with each family's copyright notice, ships
next to the font as `<family>-OFL.txt`, as the OFL requires.

The fonts are self-hosted, not loaded from Google, so that the pages make no
third-party request and the Content-Security-Policy can stay `font-src 'self'`.
Each family has one weight, cut into three subsets (`latin`, `cyrillic`,
`cyrillic-ext`) exactly as Google Fonts serves them. A browser downloads a
subset only when the page's text uses characters from its `unicode-range`.

| Family | Weight | Copyright | License file |
|---|---|---|---|
| Bad Script | 400 | 2011 The Bad Script Project Authors | `bad-script-OFL.txt` |
| Comfortaa | 600 | 2011 The Comfortaa Project Authors (RFN "Comfortaa") | `comfortaa-OFL.txt` |
| Cormorant Garamond | 600 | 2015 the Cormorant Project Authors | `cormorant-garamond-OFL.txt` |
| Forum | 400 | 2011 Denis Masharov (RFN "Forum") | `forum-OFL.txt` |
| Great Vibes | 400 | 2015 The Great Vibes Pro Project Authors | `great-vibes-OFL.txt` |
| Lora | 500 | 2011 The Lora Project Authors (RFN "Lora") | `lora-OFL.txt` |
| Montserrat | 400 | 2024 The Montserrat.Git Project Authors | `montserrat-OFL.txt` |
| Nunito | 600 | 2014 The Nunito Project Authors | `nunito-OFL.txt` |
| Unbounded | 600 | 2022 The Unbounded Project Authors | `unbounded-OFL.txt` |

The files are unmodified from Google Fonts' own subsets. They are not renamed
inside the font, so no Reserved Font Name is affected.

### Added in CP17

| Family | Weight | Copyright | License file |
|---|---|---|---|
| Balsamiq Sans | 700 | 2011 The Balsamiq Sans Project Authors | `balsamiq-sans-OFL.txt` |
| Caveat | 600 | 2014 The Caveat Project Authors | `caveat-OFL.txt` |
| El Messiri | 600 | 2015 The El Messiri Project Authors | `el-messiri-OFL.txt` |
| Kurale | 400 | 2013 The Kurale Project Authors | `kurale-OFL.txt` |
| Old Standard TT | 400 | 2011 The Old Standard Project Authors | `old-standard-tt-OFL.txt` |
| Oswald | 600 | 2016 The Oswald Project Authors | `oswald-OFL.txt` |
| Poiret One | 400 | 2011 The Poiret One Project Authors | `poiret-one-OFL.txt` |
| Prata | 400 | 2011 The Prata Project Authors | `prata-OFL.txt` |

Copied from the first line of each family's license file.

## Uzbek Cyrillic coverage

Uzbek Cyrillic needs Қ қ Ғ ғ Ҳ ҳ Ў ў. Checked glyph by glyph with fontTools
on 2026-10-03:

- **Complete:** Cormorant Garamond, Lora, Montserrat, Nunito, Forum and Bad
  Script.
- **Missing some of them:** Great Vibes (Қ Ғ Ҳ), Unbounded (Қ Ғ Ҳ) and
  Comfortaa (Ҳ). From CP17: Poiret One and El Messiri (Қ Ғ Ҳ), and Prata,
  Old Standard TT and Kurale (Ҳ). Oswald, Balsamiq Sans and Caveat are
  complete. `tests/test_web_designs.py` fails the build if a theme leads with
  an incomplete face and does not set a complete `--font-display-uzc`. Every theme that uses one of these switches its display font
  on `:lang(uz-Cyrl)` to a complete family. See `--font-display-uzc` in the
  theme CSS.

No family has a ♥ glyph, so the hearts on the pages are SVG.

## Everything else on the pages

The ornaments, patterns, envelope, wax seal and icons are all original. They
are drawn in this repository as inline SVG and CSS gradients for this
project, and no outside artwork, illustration or icon set is used.
