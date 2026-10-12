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

## CP24 — twenty further original designs (2026-10-12)

### Research and access log

The owner asked for more bright ideas while CP23 is still working in the main
checkout. This survey informs colour, hierarchy and feature choices only. No
source layout, path, ornament, image, illustration or wording is imported.
Public product descriptions are evidence of offered features, not a measurement
of market popularity. Older portfolio work below is labelled as such.

| Source inspected | Public finding / implication |
|---|---|
| [E-taklif](https://e-taklif.uz/) | Local event categories include nikoh, sunnat, beshik and jubilees; designs must not assume a couple or a wedding. |
| [etaklif.uz](https://etaklif.uz/) | Inaccessible through the research tool; do not conflate it with the reachable hyphenated domain. |
| [Taklifim](https://taklifim.uz/) | Inaccessible through the research tool; no visual or feature claims. |
| [MyTaklif](https://mytaklif.uz/) | Public shell/title reachable, but no readable catalogue; no invented visual findings. |
| [Taklifiy](https://taklifiy.uz/) and [public product](https://taklifiy.uz/en/invitations/reveal_13) | Fast link sharing and multiple languages; product description lists reveal, countdown, music, guest-count RSVP and map. Keep the existing common mechanics. |
| [Invitely](https://invitely.uz/) | Public catalogue spans emerald, vintage and green themes. Its FAQ describes dress code, photos, guest questionnaire and a tapped music player; neutral content blocks can support many events. |
| [InviteStudio](https://www.invitestudio.uz/) | Public portfolio and service description stress mobile reading, restrained typography and animated entry. Bright surfaces still need calm text areas. |
| [Invitate](https://invitate.uz/) | Public service combines shareable web invitations, maps, music and RSVP; retain our self-hosted version of these affordances. |
| [Just Invite gallery](https://justinvite.ru/gallery) | Russian catalogue groups weddings, children's events, business, graduation, religious and seasonal events; broadens the content-neutral design directions. |
| [Just Invite boho article](https://justinvite.ru/blog/priglashieniia-na-svadbu-v-stilie-bokho/) | Older tutorial, not evidence of a new 2026 trend: warm paper and restrained natural motifs support the terracotta direction. |
| [Pinterest terracotta pin](https://www.pinterest.com/pin/619807967516647253/) | Public pin metadata pairs terracotta and white; only the colour direction is used. No art downloaded. |
| [Pinterest Palette 2026](https://newsroom.pinterest.com/fr/pdf/pinterest-palette-2026-pdf/) | Platform's published orange colour direction suggests a brighter coral/citrus option; this is not invitation-specific popularity data. |
| [Behance typography project](https://www.behance.net/gallery/240093135/Mia-and-Seb-Invitation-Project) | December 2025 type-only assignment shows hierarchy can carry an invitation without illustration; our citrus poster uses original hierarchy and geometry. |
| [Behance architectural/watercolour project](https://www.behance.net/gallery/242588307/Hand-Drawn-Wedding-Venue-Sketch-for-Invitations) | January 2026 portfolio combines thin lines and restrained washes. Our blossom motif uses authored vector ellipses and CSS washes, with no source illustration. |
| [Behance lemon suite](https://www.behance.net/gallery/168154889/Lemon-Watercolor-Wedding-Invitation-Suite) | Older public portfolio title supports exploring citrus as a direction; no layout or painted lemons reused. |
| [Dribbble envelope/seals](https://dribbble.com/shots/1296172-Wedding-Invite-and-Envelopes) | Public older portfolio describes seals/envelopes; our existing reveal can carry twenty new themed envelopes. |
| [Dribbble monogram stationery](https://dribbble.com/shots/6993769-Wedding-invitation) | Public author description mentions monogram wax stamp and copper foil; retain creator initials rather than shop initials on the seal. |
| [Dribbble minimal/bold typography](https://dribbble.com/shots/6090234-Minimal-Bold-Typography-Centered-Wedding-Invitation) | Older type-led portfolio reinforces a plain, strong text-first option; no wording copied. |
| [YouTube digital wax-seal tutorial](https://www.youtube.com/watch?v=PDGnD3Vl6go) | Public 2025 title/description advertises interactive digital seal creation. Only metadata inspected, not a claim to have watched the video. |
| [YouTube physical wax tutorial](https://www.youtube.com/watch?v=Be4JnYHbypM) | Older public tutorial metadata: the seal metaphor predates this checkpoint; no tutorial artwork incorporated. |
| [TikTok wedding invitations](https://www.tiktok.com/tag/weddinginvitation) | Tool access blocked by robots; skipped, no feed observations claimed. |
| [Invitely's public Instagram link](https://invitely.uz/) | Linked from the public service; research access failed. No login attempted and no account content claimed. |

The owner's already-observed Instagram directions (seal envelope, ivory/gold
arch, lavender, botanical green, burgundy ornaments and interactive sections)
are owner-supplied observations, distinct from this public-source survey.

### Gaps, original compositions and gift decision

CP17 already has photo, bold, watercolour, black/white, children, suzani and
Art Deco. CP24 therefore gives each of these directions a new composition,
not a renamed palette: contact sheet versus arched portrait, a museum label
versus a framed monochrome card, stepped geometry versus the old Deco fan,
and pomegranate medallions versus the old Suzani rosette. The brighter set
adds citrus yellow, coral film stock, cobalt ribbon, purple/yellow academic,
green spring and pastel rainbow. Every motif is hand-authored SVG geometry.

| Key | Display name / original composition | CP18 gift |
|---|---|---|
| zarhal | Zarhal kecha — engraved double frame on charcoal/gold | Premium |
| zumrad | Zumrad saroy — emerald architectural niche | Premium |
| anor | Anor ipagi — bright pomegranate embroidery medallions | Premium |
| girih | Girih osmoni — eight-pointed geometric night panels | Premium |
| gulshabnam | Gul shabnami — coral/lilac blossom washes | Premium |
| sitrus | Sitrus bayram — yellow/green poster with diagonal header slab | Free |
| maktub | Mehr maktubi — postal letter and perforated stamp | Premium |
| chiziq | Chiziq galereya — black/white museum label and offset rules | Free |
| sahro | Sahro quyoshi — terracotta sunrise arch and woven stripes | Premium |
| kamalak | Kamalak orzusi — pastel rainbow and playful scallops | Free |
| ilm | Ilm nuri — purple academic bookplate with yellow sash | Free |
| anjuman | Anjuman studiya — azure business panels and lime tabs | Free |
| navroz | Navro'z nafasi — vivid spring tulips and grass border | Free |
| qish | Qish yulduzi — ice-blue snow rosette and frosted panels | Free |
| lavha | Lavha jurnal — photo-led editorial gallery | Premium |
| kadr | Kadr xotira — coral contact sheet and upright polaroids | Premium |
| zinalar | Zinalar oltini — stepped ivory/cobalt Art Deco frame | Premium |
| sokin | Sokin bog' — quiet ink circle and vermilion seal | Free |
| marjon | Marjon yurak — blush cameo with coral ribbon | Premium |
| moviy | Moviy tantana — royal blue ribbon and silver constellation | Premium |

Twelve crafted/photo-led new styles are premium; eight broadly useful new
styles stay free, so the free offering expands. The decision lives only in
`services/premium.py:CP24_PREMIUM_TEMPLATES`; activation unions it into the
existing premium set after the CP23 rebase and additive CHECK migration.
No prior free design becomes premium. Music/photos retain their existing
per-shop confirmed-order gift rule, and existing granted gifts remain valid.

### Shared features, language and weight contract

All twenty new designs use the same three page templates, translated sections,
seal/monogram and progressive reveal. Kind-specific features remain appropriate:
RSVP/countdown/programme/palette/wishes on invitations; escaping second button
and optional date plan on answerable pages; photos/music/branding use the
existing rules. A gallery-first design consumes the first gallery photo once,
keeps the remaining photos, and shows initials/heart if empty. Disabling the
invitation gallery must not surface its photos in a lead frame.

Reuse the committed OFL subset files and adjacent `<family>-OFL.txt` licences:
Cormorant Garamond, Forum, Lora, Montserrat, Nunito, Oswald and Balsamiq Sans. All seven have the documented full Қ қ Ғ ғ Ҳ ҳ Ў ў
coverage. No new font/model/browser download is needed. No external scripts,
fonts, images or style blocks are added; the existing CSP stays unchanged.

The earlier brief estimates 5–7 KB HTML, ~35 KB shared CSS/JS and 40–110 KB
fonts. CP24 treats those as planning estimates, not permission to hide bytes.
Report cold uncompressed totals (HTML + requested CSS/JS + fonts) per design
and language; target **<=180 KiB** for the chrome of a feature-rich page and
**<=110 KiB fonts**. Optional customer photo payloads are separately itemised
(up to six existing 1.5 MB stored images), never excluded without saying so.
Only the selected theme CSS is requested. Screenshot PNGs are evidence assets,
not customer page dependencies. Browser checks also enforce no foreign network
requests and inspect content boxes, not only the clipped document width.

### Isolation and activation sequence

Worktree `D:\Coding projects\gulbot-cp24`, branch `cp24-designs`, based on
CP22.2 `62571a3`. Dedicated test DB `gulbot_cp24_test`; Redis test/FSM index 11,
broker 9, results 10; default `gulbot_test` / Redis 15 are never reset here.
Historical migration probes with fixed names must be overridden to CP24 names
if selected; do not run another session's shared probe database.

While CP23 is active: prepare research/artwork/templates and focused web/share
checks only. The new names can be rendered by the read-only demo route, while
persistent `PAGE_TEMPLATES` remains the existing twenty. Do not add a CP24
migration, run the full suite or merge. Once CP23 lands: fetch/rebase, widen the
single database CHECK with ONE new additive migration, activate the names in
creation/picker and premium rules, prove every allowed name via PostgreSQL and
round-trip a newly named CP24 probe DB. Only after the other session finishes
may the full gate run. Push only `cp24-designs`; merging also needs a secrets
scan and confirmation no other session is working.

### Additional bright directions requested during CP24

The follow-up survey also checked the public [SEATORY invitation builder](https://seatory.ru/invitations), which separates corporate, birthday and graduation examples and describes programme/guest-form pages; this supports giving **Anjuman**, **Ilm** and **Kamalak** their own readable compositions. [Invitizer's birthday catalogue](https://invitizer.ru/invites/den-rozhdeniya/) search-index description mentions both vivid and restrained invitations; the direct fetch failed, so no detailed layout is claimed. [Fo.Ru's invitation builder](https://fo.ru/invitation) public description likewise spans wedding, birthday, corporate and graduation. These are research references, not dependencies or imported templates.

Original ideas developed from these gaps: a lemon-yellow typographic poster
(**Sitrus**), a coral contact sheet (**Kadr**), a lime-tab azure agenda
(**Anjuman**), a purple/yellow bookplate (**Ilm**), pomegranate medallions on
bright warm cloth (**Anor**), spring tulips (**Navro'z**) and an ice-blue
snow rosette (**Qish**). None requires copying a source illustration. Their
ornaments and layout treatments differ from both the old twenty and one
another; all retain a quiet readable content surface at 360 px.

Browser preflight found two existing worst-text problems across the old set:
long shop names could enlarge the mobile viewport, and long event/wish-author
text could exceed its box. Shared wrapping fixes preserve the existing colours,
art and behavior. The all-language section test also found missing Uzbek
Cyrillic dress-palette labels; they now use the project's fixed-string
transliteration, never changing a customer's typed text.

Visual QA changes: footer text and primary-button labels in all new styles
have an explicit >=4.5:1 solid-palette contrast check. Dark gold buttons use
dark ink; shop labels on dark backgrounds use light ink. New styles place the
optional music control in normal flow so it cannot cover maps, RSVP or the
second answer button. Four/five-letter seals use a smaller size; the worst-text
fixture now includes five wide initials and a full 400-character programme.
The browser harness observes a lazy image's actual completion after scrolling,
with a bounded wait; it does not hide a broken image behind decoder exceptions
or change the image source.

### Further bright concept board (research follow-up)

[Pinterest's official 2026 palette](https://newsroom.pinterest.com/news/from-cool-blue-to-persimmon-meet-the-2026-pinterest-palette/) names Cool Blue, Jade, Plum Noir, Wasabi and Persimmon. This is a platform-wide colour forecast, not evidence of Uzbek invitation demand. A [Behance invitation identity published 23 April 2026](https://www.behance.net/gallery/248059783/Wedding-Invitation-Suite-Visual-Identity) describes expressive typography with peach/sage botanicals. [Dribbble's public birthday invitation collection](https://dribbble.com/tags/birthday-invitation) also shows the breadth of playful illustration versus restrained typography; it is a portfolio collection, not a popularity ranking.

Our own inference is to keep the bright personality in borders, seals and
large headings while retaining a calm text surface. The CP24 styles already
apply this in Sitrus, Anor, Kadr, Ilm, Anjuman, Navro'z and Qish. Additional
original concepts worth a later collection, separate from the twenty CP24 keys:

| Concept | Own composition idea | Bright palette direction |
|---|---|---|
| Chiroq festival | Paper-lantern silhouettes along a vertical invitation rail | Electric lime / iced blue / ink |
| Xurmo picnic | Overlapping round fruit geometry framing a short personal note | Persimmon / pale peach / plum |
| Yalpiz postcard | Split address label, oversized initials and a tear-off RSVP strip | Jade / cream / coral |
| Mehr ticket | Perforated edges, large event number and horizontal programme tabs | Cobalt / lemon / white |
| Daryo daybreak | Broad flowing SVG bands, floating date plaque and upright photos | Aqua / sunrise orange / cream |
| Bayram bunting | Irregular original flag geometry above an aligned wish wall | Raspberry / mint / butter yellow |

These are ideation notes only: no extra allowlist names, assets, network
requests or new features are introduced. Any later collection would need the
same language, font licence, contrast, mobile, weight and gift-policy checks.
