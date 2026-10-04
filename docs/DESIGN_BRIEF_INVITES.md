# Design brief: Ha/Yo'q pages and taklifnomas

Written 2026-10-03, before the build, from a survey of current invitation and
proposal-page design. **Inspiration only.** Every template in
`src/gulbot/web/` is original: no layout, artwork, illustration or copy was
taken from any site below. Fonts and their licenses are listed in
`src/gulbot/web/static/fonts/LICENSES.md`.

## What the market does

### Ha/Yo'q ("will you be my valentine") pages

This is a viral TikTok and Instagram format.

- **The page.** One question, a big Yes button and a No button that dodges the
  finger.
- **The No button.** On a phone it dodges on touch. It also shrinks, swaps
  places with Yes, or changes its label, and each attempt makes Yes grow.
- **Yes.** It ends in a celebration: confetti or hearts, sometimes a card flip.
- **Variants.** Date requests, apologies, girlfriend/boyfriend asks and
  proposals.
- **How it is made.** Most generators are free, made in under a minute and
  shared as a link.

Their weak spot is a generic look, with no personal touch and one language.

Ours adds:

- ten designs;
- four languages (Uz Latin, Uz Cyrillic, Russian, English);
- the shop's own branding and link;
- an optional, single "they said Ha" message to the creator.

### Taklifnoma / e-invites in Uzbekistan and the CIS

Local services include mytaklif.uz, taklifiy.uz, invitely.uz, e-taklif.uz and
e-taklifnomalar.uz, and justinvite.ru and evently.by in Russian.

- **What they offer.** A link plus a QR code, sharing through Telegram or
  WhatsApp, Uzbek and Russian (often English), RSVP, a map, sometimes music.
- **The dominant Uzbek wedding look.** Burgundy or lace on ivory, ornamental
  frames, bilingual text.
- **The trend of 2026–27.** The *envelope*: tap the wax seal, the flap opens,
  the letter rises out. Popular on TikTok and in Canva templates.
- **How Russian builders sort templates.** By style (classic, boho, rustic,
  glam, minimal, vintage) and by palette (pastel, monochrome, contrast,
  metallic, natural, bright). Our ten designs span the same axes.

### 2026 invitation trends

From Paperless Post, Paperlust and Cotton & Bow:

- neutral greenery and botanical line art;
- hand-drawn "scribble" lines;
- lace textures;
- bold saturated colour (pink, orange, purple);
- monograms;
- dramatic type in one of three directions: huge sans, formal script, or
  minimal serif with lots of space;
- arch and scallop shapes;
- blind emboss;
- muted watercolour florals.

### Utility a 2026 guest expects

- one-tap RSVP;
- a countdown;
- add to calendar;
- a map link;
- a page that loads fast on mobile data inside Telegram's in-app browser.

## The ten designs

Every design serves both kinds of page.

| Key | Name | Mood | How it is drawn (CSS/SVG only) |
|---|---|---|---|
| `milliy` | Milliy naqsh | Classic Uzbek | Ivory, pomegranate red, gold. An eight-point star lattice (two squares, one turned 45°), a double ruled frame, a rosette ornament. |
| `atlas` | Atlas | Modern Uzbek | Abstract ikat bands in indigo, rose and saffron from repeating gradients; a white card with a saffron top edge. |
| `minimal` | Minimal | Modern minimal | Paper white, one terracotta accent, a large serif, generous space. |
| `bog` | Bog' | Floral | Sage and blush, an arch-topped card, stems and leaves in our own line art, a script heading. |
| `romantik` | Romantik | Romantic | Blush-to-rose gradient, script heading, slowly floating SVG hearts. |
| `oltin` | Oltin | Luxury gold | Deep emerald, gold "foil" gradient type, an arched double frame. |
| `quvnoq` | Quvnoq | Playful | Confetti-dot background, a scalloped card cut with a mask, offset "poster" shadows. |
| `tungi` | Tungi | Dark elegant | A navy night sky of gradient stars, a CSS crescent, thin gold rules, a soft glow. |
| `pastel` | Pastel | Pastel | Lavender, mint and peach blobs, rounded everything. |
| `konvert` | Konvert | Envelope | Arrives sealed: tap the wax seal (the initial is pressed into it), the flap turns over and the letter rises. Cream ruled paper and a handwritten heading. |

### The Ha/Yo'q mechanics (`static/js/page.js`)

**The Yo'q button.**

- It runs to a random spot that never overlaps Ha, using `pointerenter` for a
  mouse and `touchstart` for a finger.
- It shrinks a little each time and changes its label through a playful
  localized list.
- Each attempt grows Ha a little.
- With `prefers-reduced-motion` it does not fly, but it still shrinks and
  changes its label.

**Ha.** The page swaps to the celebration: a beating heart, "Hurraa!", a line
that fits the question, and confetti and hearts. It POSTs once; the server
keeps only the first answer.

### The invitation

- **The card.** The event label, the names (an ampersand for a couple), the
  message (or a ready text for that event type), and a big date block with the
  weekday and time.
- **Below it:** a live countdown, the venue, and Google and Yandex map links
  when a pin was sent.
- **"Add to calendar".** An `.ics` file.
- **The optional RSVP:** Kelaman / Kela olmayman, a number of guests and an
  optional name.

## Typography

There are nine OFL families, self-hosted. Each has one weight and three
subsets (latin, cyrillic, cyrillic-ext); see `static/fonts/LICENSES.md`.

| Role | Families |
|---|---|
| Serif display | Cormorant Garamond, Forum |
| Script | Great Vibes, Bad Script |
| Sans display | Unbounded, Comfortaa |
| Body | Lora, Montserrat, Nunito |

**Uzbek Cyrillic needs Қ Ғ Ҳ Ў.** We checked every font glyph by glyph before
building:

- Manrope, which the first draft of this brief named, has none of them, so it
  was dropped.
- Great Vibes, Unbounded and Comfortaa lack some of them. The themes that use
  them switch to a complete face on `:lang(uz-Cyrl)`.

## Hard constraints, all met

- **Mobile first.** Designed at 360 px. The card is at most 460 px wide, and
  there is no horizontal scroll.
- **Weight, measured on the built pages.** The HTML is 5–7 KB. CSS and JS
  come to about 35 KB uncompressed, shared and cached for a year. A page needs
  2–4 font subsets, 40–110 KB: the Milliy taklifnoma in Uzbek Latin is about
  85 KB in all. Nothing comes from a third party.
- **Security.**
  - CSP: `default-src 'none'`, with script, style, font and connect allowed
    only from `'self'`, images from `'self'` and `data:`, and no inline script
    or style.
  - Every response carries `noindex`.
  - Every typed field is escaped by Jinja autoescape.
  - No phone number is ever rendered.
- **Attribution.** Each page shows the shop's name and a monogram, and has
  "Gul buyurtma qilish" linking to that shop's own bot
  (`/p/<token>/go` → `t.me/<shop_bot>?start=pg_<token>`).

## Sources

- **Proposal pages:**
  [askyourvalentine.com](https://askyourvalentine.com/),
  [willyoubemyvalentine.fun](https://willyoubemyvalentine.fun/),
  [bemyval.co](https://bemyval.co/),
  [MyHeartCraft roundup](https://myheartcraft.com/blog/cute-websites-to-send-to-boyfriend-girlfriend),
  [TikTok: proposal websites](https://www.tiktok.com/discover/will-you-be-my-girlfriend-website-proposal).
- **Invitation trends:**
  [Paperless Post 2026](https://www.paperlesspost.com/blog/wedding-invitation-design-trends/),
  [Paperlust 2026](https://paperlust.co/blog/wedding-invitation-trends-2026/),
  [Cotton & Bow](https://cottonandbow.com/15-wedding-invitation-trends-for-2026/),
  [Messagear, digital invitations 2026](https://blog.messagear.com/ultimate-guide-to-digital-invitations-2026/).
- **Uzbek market:**
  [mytaklif.uz](https://mytaklif.uz/),
  [taklifiy.uz](https://taklifiy.uz/),
  [invitely.uz](https://www.invitely.uz/),
  [e-taklif.uz](https://e-taklif.uz/),
  [Instagram @first_taklifnomalari](https://www.instagram.com/first_taklifnomalari/),
  [Pinterest "taklifnoma" board](https://www.pinterest.com/hamidovmansur25/taklifnoma/).
- **Russian market:**
  [justinvite.ru](https://justinvite.ru/wedding),
  [dtf.ru builder roundup](https://dtf.ru/kursfinder/4064535-konstruktory-saitov-dlya-svadebnykh-priglasheniy).
- **The envelope trend:**
  [TikTok, envelope animation](https://www.tiktok.com/discover/open-envelope-animation).

Instagram and TikTok feeds need a signed-in session. They were surveyed
through their public search and discover pages and the sites those point to,
not by scrolling a logged-in feed.

---

# CP17 addendum: date plans, editable invitations, ten more designs

Researched 2026-10-04. Inspiration only, as before. No layout, artwork,
ornament, photo or copy is taken from any source below, e-taklif.uz
included.

## What the second round of research found

**Uzbek invitation services.**
- e-taklif.uz advertises about 500 templates across nikoh, qiz uzatish,
  sunnat, beshik, yubiley and nahor oshi. e-taklifnoma.uz and
  e-taklifnomachi.uz lead with "your own photo and music", a map and a
  timer.
- e-taklifnomachi.uz sorts its catalogue into four moods: light modern,
  bright-but-subtle festive (for children), warm and intimate, and premium
  formal.
- Printed-template shops (soff.uz) sell the same two families again and
  again: modern floral, and black-and-gold luxury.

**What our ten designs do not yet cover:**
- a photo of the couple or the child, the strongest single request in this
  market;
- a children's style;
- a "premium formal" style that is not gold.

**Date proposal pages** (planyour.date, askfordate.app, pickourdate.co,
ourlittle.date). After Yes, the recipient picks from the CREATOR's options,
never free text: a time from the creator's slots, a place or activity from
the creator's list. The creator then gets the plan in one message.
ourlittle.date says it outright: the tone is confident and low-pressure,
the No button teases but is never manipulative, and it can be switched off.
That matches the brief for Part 2.

**General trends** (Vistaprint 2026 categories, The Knot, Paperlust):
- "graphic and editorial" typography;
- abstract watercolour;
- minimal black and white;
- photo-led layouts;
- vintage paper;
- Art Deco geometry, gold or bronze on jewel tones;
- Islamic geometric motifs used sparingly, as a border or watermark in
  ivory, gold and sage;
- for children: bold colour and a single story, such as balloons or animals,
  instead of all-white.

**Platforms not reached.**
- Instagram: the in-app browser refused the site, so it was skipped as
  instructed. No login was attempted.
- TikTok: a fetch was reset.
- Pinterest: idea pages returned no readable content.
- YouTube: search surfaced only tutorials for the same Uzbek services.

## Ten new designs (original CSS/SVG; fonts checked glyph by glyph)

| Key | Name | Gap it fills | Drawn as |
|---|---|---|---|
| `foto` | Foto | photo-led, the top local request | The creator's one photo in an arched frame. Re-encoded server-side, metadata stripped, size-capped, stored per shop. |
| `bold` | Bold | editorial typography | Huge condensed type (Oswald), one accent colour, a hard rule. |
| `geometrik` | Geometrik | Islamic geometric | An original interlaced star tiling as a watermark border, ivory, gold and sage. |
| `akvarel` | Akvarel | watercolour | Soft blurred colour blobs in CSS, with a handwritten heading (Caveat). |
| `vintaj` | Vintaj | vintage letter | Aged paper, a postmark and a stamp drawn in SVG, typewriter-era serif. |
| `oqqora` | Oq-qora | minimal black and white | High-contrast didone headline, black on white, nothing else. |
| `bolalar` | Bolalar | children's party | Balloons and confetti in SVG, rounded bold type (Balsamiq Sans). |
| `suzani` | Suzani | Uzbek embroidery, not gold | Original concentric "sun" medallions in madder, indigo and saffron, as a border. |
| `neon` | Neon | night party, graduation | Dark brick-black ground, glowing outlined type. |
| `deco` | Deco | Art Deco | Fan and step geometry in brushed bronze on deep teal. |

**New fonts, all OFL:** Oswald, Balsamiq Sans and Caveat have the complete
Uzbek Cyrillic set. Poiret One, El Messiri, Prata, Old Standard TT and Kurale
are each used only with a `:lang(uz-Cyrl)` fallback to a complete face, the
same rule as CP16.
