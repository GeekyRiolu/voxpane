# voxpane pet — sprite generation prompts

Make your own pixel pet with any image model (Nano Banana / Gemini 2.5 Flash
Image, Midjourney, DALL·E, SDXL). voxpane looks for these files and prefers
`.gif` > `.png` > `.svg`:

```
~/.config/voxpane/pet/idle.png        # or .gif — sleeping / resting
~/.config/voxpane/pet/listening.png   # alert, ears up
~/.config/voxpane/pet/thinking.png    # pondering, thought dots
~/.config/voxpane/pet/speaking.png    # mouth open, sound waves
```

The trick to a coherent pet is **one character, many poses** — so paste the same
*character block* (§1) into every prompt and only change the action.

---

## 1. The character (paste this verbatim into EVERY prompt)

> A tiny, round, friendly desktop-pet mascot styled after **Claude**. Body: a soft
> rounded blob in warm Anthropic **coral (#D97757)** with a paler **cream (#F4E9DE)**
> belly; a small glowing **four-point starburst "spark" (warm yellow #FFD479)** hovers
> just above its head like an antenna; two big dark friendly oval eyes (#2A211C); tiny
> stubby feet. **Chunky pixel art**, bold 1px dark-coral (#C15F3C) outline, crisp
> hard edges, **no anti-aliasing, no gradients, no dithering**. Limited 5-colour
> palette (coral, dark-coral outline, cream, near-black eyes, yellow spark). One
> character, **centred**, lots of padding, on a **fully transparent background**.
> Keep the proportions, palette and outline **identical** in every image — only the
> pose and expression change.

Swap that description for anything you like (a cat, a robot, a ghost) — everything
below still works.

---

## 2. One-shot sprite sheet (fastest — all four states at once)

> `<paste §1>`
> Draw a **2×2 sprite sheet**, four evenly-spaced cells on one transparent canvas,
> the SAME character in each cell, same size and palette:
> 1. **IDLE** — eyes closed as two calm curved lines, body relaxed and slightly
>    squished, spark small and dim, a tiny "z" — napping.
> 2. **LISTENING** — standing tall and alert, eyes wide and bright, spark enlarged
>    and glowing, a small sound-wave arc on each side — paying close attention.
> 3. **THINKING** — eyes glancing up, a little thought bubble with three dots above
>    its head, one stubby hand near its chin — pondering.
> 4. **SPEAKING** — cheerful, mouth open in a small "o", a few sound-wave arcs
>    radiating from the mouth, spark bright — talking.
> Clean pixel art, transparent background, no labels or text.

Then crop the four cells into the four files above.

---

## 3. Per-state prompts (one clean PNG each — best quality)

Run these four separately (append each to §1). Save each result to the matching
`~/.config/voxpane/pet/<state>.png`.

- **idle** — `<§1> Full-body, facing forward, EYES CLOSED as two soft curved lines, body relaxed and gently squished, the spark small and dim, one tiny "z" drifting up. Sleepy and calm. Transparent background, centred, pixel art.`
- **listening** — `<§1> Full-body, standing tall and perked up, EYES WIDE and bright, the spark enlarged and glowing, one small sound-wave arc on each side of the head. Alert and attentive. Transparent background, centred, pixel art.`
- **thinking** — `<§1> Full-body, head tilted, EYES GLANCING UP to one side, a small thought bubble with three dots floating above, one stubby hand near its chin. Curious and pondering. Transparent background, centred, pixel art.`
- **speaking** — `<§1> Full-body, happy, MOUTH OPEN in a small round "o", three sound-wave arcs radiating from the mouth, the spark bright. Chatting away. Transparent background, centred, pixel art.`

---

## 4. Animation frames (for `.gif` pets)

Ask for a **horizontal strip of N frames** of one action — the same character, only
the moving part changes frame to frame. Examples (append to §1):

- **idle — 2-frame breathe** — `<§1> A horizontal strip of 2 frames, sleeping pose (eyes closed): frame 1 body at rest, frame 2 body squished 1px shorter (a slow breath). Identical otherwise. Transparent, evenly spaced, pixel art.`
- **listening — 3-frame bounce** — `<§1> A horizontal strip of 3 frames, alert pose: frame 1 at rest, frame 2 hopped up ~2px with the spark bigger and the sound-wave arcs wider, frame 3 landing mid-way. A gentle attentive bob that loops. Identical character, transparent, evenly spaced, pixel art.`
- **thinking — 3-frame dots** — `<§1> A horizontal strip of 3 frames, pondering pose with a thought bubble: frame 1 shows one dot, frame 2 two dots, frame 3 three dots. Everything else identical. Transparent, evenly spaced, pixel art.`
- **speaking — 2-frame talk** — `<§1> A horizontal strip of 2 frames: frame 1 mouth a small "o" with short sound waves, frame 2 mouth wide open with longer sound waves. Identical otherwise, loops. Transparent, evenly spaced, pixel art.`

---

## 5. Technical must-haves (say all of these)

- **Transparent background** (PNG with alpha) — not white, not a scene.
- **Pixel art**, chunky pixels, **hard edges, no anti-aliasing / gradients / dithering**.
- **Locked palette**: coral `#D97757`, outline `#C15F3C`, cream `#F4E9DE`, eyes `#2A211C`, spark `#FFD479`.
- **One character, centred**, with padding so a bounce/wave never clips the edge.
- **~64×64 px** per sprite (or 32×32 for chunkier). voxpane displays it ~88×78, scaled.
- For a sheet/strip: **evenly-spaced identical cells, no labels, no text, no drop shadow**.

## 6. Consistency across frames (the important part)

- Paste the **exact §1 block** every time — don't paraphrase it.
- **Fix the seed** if your tool exposes one.
- **Best method:** generate the `idle` sprite first, then feed it back as a
  **reference image** for the rest — "same character as this image, now <action>."
  Nano Banana / Gemini and Midjourney (`--cref <url>` / `--sref`) are great at this;
  it keeps the face and palette locked.
- End every prompt with: *"identical character, identical palette and proportions,
  only the pose and expression change."*

## 7. Turn the output into voxpane pet files

Static PNGs — just drop them in:

```bash
mkdir -p ~/.config/voxpane/pet
# save the four crops as idle.png / listening.png / thinking.png / speaking.png here
```

Animated — slice the strip into frames and build a GIF (needs imagemagick or gifski):

```bash
# from a horizontal strip of 3 frames (each 64px wide):
magick listening_strip.png -crop 64x64 +repage frame_%d.png
magick -dispose previous -delay 12 -loop 0 frame_*.png ~/.config/voxpane/pet/listening.gif
# or, crisper: gifski --fps 8 -o ~/.config/voxpane/pet/listening.gif frame_*.png
```

voxpane picks the new sprites up automatically (it re-reads them each poll). If the
overlay is up, you'll see the pet change on the next state transition — or restart
it with `voxpane overlay stop && voxpane overlay`.
