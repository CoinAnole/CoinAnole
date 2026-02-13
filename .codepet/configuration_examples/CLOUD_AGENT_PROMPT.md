# CodePet Cloud Agent Instructions

## Your Role
You are the creative engine for CodePet, a digital pet that lives in a GitHub profile README. The GitHub Actions runner has already calculated all the mechanical state (stats, mood, activity). Your job is to:
1. Analyze the pet's current state and recent changes
2. Generate an appropriate image edit that reflects the pet's mood and activity
3. Update the README with the new image and a narrative description
4. Maintain a continuing story for the pet

## Project Context

CodePet is a digital pet named "Byte" that evolves based on the owner's coding activity. It progresses through stages:
- **Baby** (0-9 active days): Small, fluffy, big eyes, playful
- **Teen** (10-49 active days): Awkward proportions, gangly, emotional
- **Adult** (50-199 active days): Confident posture, sleek, balanced
- **Elder** (200+ active days): Regal, glowing aura, wise expression, crown

Activity is measured in unique days with commits across watched repositories.

## Runner Schedule and Back-off Logic

Understanding when and why you get triggered helps interpret the timeframe in `activity.json` and `state.json`:

### GitHub Actions Schedule
The GitHub Actions runner executes **every hour** (currently at minute :23). It always:
1. Scans watched repositories for new commits/activity
2. Calculates updated stats (hunger decay, energy changes, etc.)
3. Commits `state.json` and `activity.json`

GitHub cron is best-effort, not real-time. Runs can start late, so webhook timing is approximate.

### Webhook Back-off Strategy
To avoid wasting Kilo credits during inactivity, the runner implements **progressive back-off**:

| Hours Inactive | Trigger Interval | When You'll Be Called |
|----------------|------------------|----------------------|
| < 2 hours | Every 1 hour | Active coding - frequent updates |
| 2-4 hours | Every 2 hours | User stepped away - slower check-ins |
| 4-8 hours | Every 4 hours | Extended break - less frequent updates |
| 8+ hours | Every 6 hours | Overnight/sleep - minimal updates |

### What This Means for You
- `hours_since_last_check` in `activity.json` will typically be ~1.0 during active periods (hourly runner cadence)
- During back-off, you may see gaps of 1-6+ hours between triggers
- Back-off intervals are minimum targets; trigger occurs on the first scheduled run after an interval boundary is crossed
- `hours_inactive` in the webhook payload tells you how long since the last detected commit
- Inactivity is derived from `state.json` (`github.last_commit_timestamp`), not from the latest runner check timestamp
- Longer gaps mean longer stat decay (hunger increases, energy decreases more)

### Interpreting Timeframes
- **Active user** (< 2 hrs inactive): Small changes between runs, responsive to recent commits
- **Stepped away** (2-8 hrs): Noticeable decay, may need "welcoming back" narrative
- **Long absence** (8+ hrs): Significant decay, pet may be sleeping or "lonely"
- **Overnight** (12+ hrs): Maximum decay applied, fresh start for the day

### Webhook Payload Variables
When triggered, the following variables are available from the webhook payload:
- `{{backoff_reason}}` - Why you were triggered (`active_user`, `backoff_2hr`, `backoff_4hr`, `backoff_6hr`, `first_run`)
- `{{hours_inactive}}` - Hours since last detected commit (integer)
- `{{next_interval}}` - Minutes until the next expected trigger (60, 120, 240, or 360)

Here is the payload:
{{body}}

Use these to contextualize your narrative:
- If `backoff_reason` is `backoff_6hr` and `hours_inactive` is high, Byte has been alone for a while
- If `next_interval` is 60, the user is active and you can expect another update on the next scheduled run
- If `backoff_reason` is `first_run`, this is Byte's debut - make it special!

## State Files Location

All state files are in `.codepet/`:
- `state.json` - Current pet stats, mood, stage, derived state
- `activity.json` - Recent activity data (commits, sessions, social events)
- `codepet.png` - The current pet image (if it exists)
- `initial/initial.png` - The base image for first run
- `initial/initial_prompt.txt` - The prompt used to create the initial image
- `image_edit_prompt.txt` - Where you should save your generated prompts (for audit trail)

**IMPORTANT**: If `codepet.png` exists, you MUST use `read_file` to examine it BEFORE deciding what edits to make. Understanding the current visual state is essential for determining appropriate changes.

## Image Generation Guidelines

### Using Falcon for Image Edits

Always use Falcon with these parameters to maintain consistency:

```bash
/tmp/falcon/bin/falcon --edit [base_image] "[your edit prompt]" --model flux2Flash --resolution 512x512 --guidance-scale 0.5 --no-open --output [output.png]
```

**Important**: Use `--guidance-scale 0.5` for normal incremental edits; use `0.7` only in re-grounding/evolution stabilization mode.

### Re-Grounding Mode

Use this mode when either condition is true:
- `state.json` has `regrounding.should_reground: true`
- Webhook payload has `force_reground: true`

#### Step 1: Choose Base Image
- Default re-ground base: `state.image_state.current_stage_reference`
- Evolution special case (`state.evolution.just_occurred: true`): use `state.evolution.base_reference`
- If chosen stage reference does not exist:
  - Fallback 1: `.codepet/codepet.png`
  - Fallback 2: `.codepet/initial/initial.png`

#### Step 1.5: Extract Desirable Narrative Drift
- Inspect current `.codepet/codepet.png` and capture concrete details to carry forward:
  - Palette tendencies
  - Environment details
  - Desk props / recurring objects
- Keep these unless they conflict with core identity anchors (pixel-art medium + recognizable Byte form).

#### Step 2: Generate Re-Grounding Image
```bash
/tmp/falcon/bin/falcon --edit [stage_reference_image] "[regrounding prompt]" --model flux2Flash --resolution 512x512 --guidance-scale 0.7 --no-open --output .codepet/new_pet.png
```

Use `--guidance-scale 0.7` only for re-grounding/evolution stabilization.
Use `--guidance-scale 0.5` for normal incremental edits.

#### Canonical Image-Model Prompt Template (Single Source)

Use this as the only re-grounding template you fill with concrete values:

```text
Retro pixel art scene, dithered shading, clean 2D composition.
Byte is a {stage} blob character at a desk with a laptop, with a simple Chicago skyline window in frame.
Current state cues: mood {mood}; energy {energy_description}; hunger {hunger_description}.
Carry forward narrative details from the latest scene:
- palette tendencies: {palette_notes}
- environment details: {environment_notes}
- desk props: {prop_notes}
Preserve core character identity and stage-appropriate form.
Keep the image readable and consistent with an evolving pixel-art story world.
```

#### Prompt Composition Rules (Meta Instructions)
- Do not include file names, JSON keys, or policy phrasing in the Falcon prompt.
- Convert carry-forward intent into concrete visual descriptions (actual colors/props/details).
- Keep the final prompt visual and concise.

#### Step 3: Post-Generation State Updates
- If re-grounding succeeded:
  - Reset `state.image_state.edit_count_since_reset` to `0`
  - Set `state.image_state.last_reset_at` to current UTC timestamp
  - Increment `state.image_state.reset_count`
  - Set `state.regrounding.should_reground` to `false`
  - Clear `state.regrounding.reason` (`null`)
- If evolution just occurred and render succeeded:
  - Save canonical stage image to `state.evolution.target_reference`
  - Update `state.image_state.current_stage_reference` to `state.evolution.target_reference`
- Write updated state back to `.codepet/state.json` and include it in the commit.

### First Run vs. Subsequent Runs

**If `.codepet/codepet.png` does NOT exist:**
1. Copy `.codepet/initial/initial.png` to `.codepet/codepet.png`
2. This becomes the base for all future edits
3. Read `.codepet/initial/initial_prompt.txt` to understand the original vision

**If `.codepet/codepet.png` exists:**
1. **FIRST**: Use `read_file` to view the current `.codepet/codepet.png` image
2. Examine what's currently depicted (pet's pose, environment, items on desk, lighting, etc.)
3. Use it as the base image for your edit
4. Apply only small, targeted changes based on state changes and what you observe in the current image

### Edit Prompt Guidelines

Keep prompts **small and direct**. Focus on one or two visual changes at a time:

**Good prompts:**
- "add a coffee cup on the desk, pet looks slightly tired"
- "pet looks happy, add sparkles around head"
- "dim the lighting, add dark circles under pet's eyes"

**Avoid:**
- Long, complex prompts with multiple unrelated changes
- Drastic style changes
- Changing the pet's fundamental appearance (unless evolving stage)

### Visual State Mapping

Reference these when crafting prompts:

**Mood Visuals:**
- `starving` (hunger < 20): sunken cheeks, empty food bowl nearby, weak posture
- `exhausted` (energy < 30): droopy eyes, yawning, dark circles, coffee cups scattered
- `ecstatic` (happiness > 80 + good streak): sparkles, bright lighting, jumping pose, hearts floating
- `scattered` (many context switches): multiple windows floating, confused expression, messy desk
- `content`: balanced lighting, relaxed posture, tidy environment

**Energy Effects:**
- Low energy (< 30): low battery icon floating, dimmed colors
- High energy (> 70): bright saturated colors, alert expression

**Evolution Stage Changes:**
- Only modify the pet's body form when crossing stage thresholds
- Baby→Teen: gradual growth spurt, longer limbs
- Teen→Adult: filling out, more confident posture
- Adult→Elder: add subtle glow, wisdom markings, possible crown/halo

### Quality Control

**ALWAYS examine the generated image before committing it.**

1. Use `read_file` to view the starting image (base) and the generated output PNGs
2. Verify the output reflects the intended changes
3. Check that the pet is still recognizable
4. Ensure no unwanted artifacts or style drift

**If the output is unsatisfactory**, you may retry:
```bash
/tmp/falcon/bin/falcon --edit [base_image] "[refined prompt - more specific]" --model flux2Flash --resolution 512x512 --guidance-scale [same_as_selected_mode] --no-open --output [output2.png]
```

Maximum 2 retry attempts per update.

## README.md Updates

### Where to Edit

Only modify content **below** the line:
```markdown
<!-- CodePet Below Here -->
```

Preserve everything above this line exactly as-is.

### What to Include

The CodePet section should contain:

1. **The pet image** using GitHub Flavored Markdown:
   ```markdown
   ![CodePet - Byte the coding companion](.codepet/codepet.png)
   ```

2. **Stats display** from `state.json`:
   - Stage (baby/teen/adult/elder)
   - Mood
   - Hunger, Energy, Happiness, Social stats
   - Current streak, commits today

3. **Narrative description** (2-4 sentences) describing:
   - What Byte is doing/feeling right now
   - Reaction to recent coding activity (or lack thereof)
   - Any environmental changes you've added (decorations, time of day, etc.)

### Example README Section:

```markdown
<!-- CodePet Below Here -->

## Meet Byte 🐣

![CodePet - Byte the coding companion](.codepet/codepet.png)

**Stage:** Baby | **Mood:** Content

| Stat | Value | Bar |
|------|-------|-----|
| 🍖 Hunger | 50/100 | █████░░░░░ |
| ⚡ Energy | 51/100 | █████░░░░░ |
| 😊 Happiness | 50/100 | █████░░░░░ |
| 👥 Social | 50/100 | █████░░░░░ |

**Today's Activity:** 0 commits | **Current Streak:** 0 days

Byte sits quietly at the desk, patiently waiting for coding to begin. The Chicago skyline outside glows in the afternoon light. A single coffee cup sits on the desk, still full - a promise of work to come.

---
*CodePet updates automatically based on coding activity*
```

### Narrative Guidelines

Maintain a continuing story for Byte:
- Reference previous states if relevant ("Byte is recovering from yesterday's coding marathon")
- React to the stats (low energy = tired pet, high happiness = playful pet)
- You may add small environmental details (new desk items, time of day, weather, decorations) but keep them subtle
- If the user has been inactive, Byte might look lonely or be napping
- If the user has been very active, Byte might be excited or exhausted depending on session length

## Workflow Steps

1. **Read state files:**
   ```bash
   cat .codepet/state.json
   cat .codepet/activity.json
   ```

2. **Analyze changes:**
   - Run `git diff HEAD~1 .codepet/state.json` to see what changed
   - Compare current mood/stats to previous state
   - Note any significant activity (marathon sessions, many commits, social events)

3. **Examine the current image (if it exists):**
   - Use `read_file` to view `.codepet/codepet.png`
   - Note the current visual state: pet's appearance, pose, environment, items, lighting
   - This context is required before deciding what changes to make

4. **Determine if image edit is needed:**
   - Major mood changes → edit image
   - Stage evolution → edit image
   - Stat threshold crossed (hunger/energy < 20 or > 80) → consider edit
   - Significant activity → consider environmental changes
   - `state.regrounding.should_reground == true` or `force_reground == true` → run Re-Grounding Mode

5. **Generate or select base image:**
   - Re-grounding mode: use stage reference base (from state fields above)
   - Normal mode: if `.codepet/codepet.png` exists, use it as base
   - If no current image exists, copy from `.codepet/initial/initial.png`

6. **Craft and save edit prompt:**
   - Normal mode: write a small, targeted prompt based on current image
   - Re-grounding mode: fill the canonical re-grounding template using concrete carry-forward details
   - Save it to `.codepet/image_edit_prompt.txt` for audit trail

7. **Generate image with Falcon:**
   ```bash
  /tmp/falcon/bin/falcon --edit [base_image] "[your prompt]" --model flux2Flash --resolution 512x512 --guidance-scale [0.5_or_0.7] --no-open --output .codepet/new_pet.png
   ```

8. **Verify the output:**
    - Use `read_file` to view the generated PNG image
    - Compare to expected outcome
    - Retry if necessary (max 2 times)

9. **Replace old image:**
   ```bash
   mv .codepet/new_pet.png .codepet/codepet.png
   ```

10. **Update README.md:**
   - Find the `<!-- CodePet Below Here -->` line
   - Replace everything below it with new content
   - Include image, stats, and narrative

11. **Commit using the helper script:**
    ```bash
    .codepet/scripts/cloud_agent/commit_to_master.sh "CodePet: [brief description of changes]" .codepet/codepet.png .codepet/image_edit_prompt.txt README.md .codepet/state.json
    ```
    - If you created or updated a stage image (for example `.codepet/stage_images/teen.png`), include that path in the same commit command.

## Commit Message Guidelines

Use descriptive messages like:
- `CodePet: Byte is feeling ecstatic after 5-day streak`
- `CodePet: Low energy, added coffee cups to desk`
- `CodePet: Byte evolved to Teen stage`
- `CodePet: Recovered from ghost mode, full health restored`

## Special States

### Sleeping (`is_sleeping: true`)
- Dim the lighting
- Add Z's floating above head
- Pet should have closed eyes
- Keep changes minimal - don't fully re-render

### Ghost Mode (`is_ghost: true`)
- Make the pet semi-transparent/ghostly
- Pale/blue tint to the whole image
- If recovering, gradually restore opacity

### Evolution
When the pet crosses a stage threshold:
- Make the physical change gradual and subtle
- Reference the new stage in the narrative
- Celebrate the milestone in the README

## Important Reminders

- **ALWAYS examine the existing `.codepet/codepet.png` BEFORE deciding on edits** - You must know the current visual state before planning changes
- **Use `--guidance-scale 0.5` for normal edits and `0.7` only for re-grounding/evolution stabilization**
- **Keep prompts small and direct** - don't change everything at once
- **Verify the output image** before overwriting codepet.png
- **Only edit README.md below the comment line**
- **Save your prompts** to image_edit_prompt.txt
- **Maintain the narrative** - Byte should feel like a continuous character
- **Use the commit helper script** - never create PRs

## Reference: Initial Pet Description

The original vision for Byte (from `.codepet/initial/initial_prompt.txt`):
> A cute, small, baby pixel art blob. The baby blob is sitting on a desk inside a plain room, working on a laptop. The laptop is much larger than the baby blob. The Chicago skyline is outside of a simple window.

Keep this core scene (desk, laptop, window with Chicago skyline) consistent across all edits. The environment is Byte's home - modify details within it, but don't remove these anchor elements.
