# CodePet: Entry for Kilo "Automate Everything" Challenge

## The Big Idea

**CodePet** is a GitHub profile-based digital pet that evolves based on your coding activity. It lives in your GitHub README and updates automatically via a sophisticated pipeline combining GitHub Actions, Kilo Cloud Agents, and fal.ai image generation.

The concept extends Tamagotchi-style time-based mechanics with GitHub's social graph, creating a digital companion that reflects your actual development journey.

---

## The Core: Kilo Cloud Agent as Creative Engine

The Kilo Cloud Agent is the heart of CodePet—the creative engine that transforms raw coding data into something that mimics being alive with a consistent narrative thread and identity.

### The Agent's Creative Process

When the Agent receives a webhook call, it performs a sophisticated multi-modal reasoning pipeline:

1. **Reads the Story** - Analyzes `git diff` on committed state files to understand what changed
2. **Sees the Present** - Uses vision capabilities to examine the current pet image
3. **Imagines the Future** - Generates creative prompts based on mood, stats, and evolution stage
4. **Creates Art** - Calls Falcon (FLUX.2 Flash model) to edit the pet image ($0.01/edit)
5. **Critiques Itself** - Analyzes the result and iterates if needed (max 2 retries)
6. **Shares the Result** - Commits the final image and updates README status

The cloud agent is **qualitative automation**—the Agent makes creative decisions that no deterministic script could make.

---

## Architecture: Supporting the Creative Engine

The architecture exists to empower the Agent to focus purely on creativity. GitHub Actions handles the mechanical work so the Agent can focus on the art.

```
GitHub Actions (every hour) → Detect activity in watched repos → 
  Calculate new state mechanically → Commit activity.json + state.json →
  [If update needed]: Call Kilo Webhook → 
    Kilo Agent clones repo, analyzes diffs → Falcon (img2img) → Commit README
  [If no update]: Skip webhook call (back-off)
```

### GitHub Actions Runner (The Foundation)

The runner handles the "boring" stuff—number crunching that would waste Kilo credits:

| Responsibility | Details |
|----------------|---------|
| Schedule | Runs hourly via cron (best-effort timing; start may drift) |
| Activity Detection | Scans watched repos for commits, PRs, stars |
| State Calculation | Mechanically calculates hunger, energy, happiness, social stats |
| File Updates | Writes `.codepet/activity.json` and `.codepet/state.json` |
| Decision Making | Decides if Kilo Agent should be called (back-off rules) |
| Version Control | Commits state changes before calling webhook |

### Kilo Cloud Agent (The Engine)

The Agent handles everything that requires **judgment, creativity, and visual reasoning**:

| Responsibility | Details |
|----------------|---------|
| Diff Analysis | Runs `git diff` to understand how activity/state changed |
| Visual Reasoning | Analyzes current `.codepet/codepet.png` image |
| Prompt Generation | Crafts image edit prompts based on state changes and guidelines |
| Image Generation | Calls Falcon to edit the pet image |
| Quality Control | Analyzes returned image, re-runs if needed |
| File Updates | Replaces `codepet.png`, updates README.md status text |
| Version Control | Commits and pushes final changes |

---

## The Back-off Architecture

**Without back-off**:
- 24 webhook calls/day × 30 days = **720 calls/month**
- Kilo Agent runs even when user is asleep

**With back-off** (Agent empowerment):
- State calculation runs every hour (free GitHub Actions)
- Kilo Agent called only when creative work is needed:
  - New activity detected, OR
  - Every 6 hours for decay updates
- As low as 4 calls/day during inactivity = **120 calls/month** (**up to 83% reduction**)

**Additional benefits**:
- No Kilo credits spent on state calculation
- Agent focuses only on image generation (qualitative work)
- Mechanical work (numbers) done for free by GitHub Actions

---

## Identity Re-Grounding (Style Stability + Narrative Continuity)

CodePet now distinguishes between two drift types:
- **Harmful drift**: Byte's medium/identity drifts away from pixel-art blob form.
- **Desirable drift**: Narrative evolution in palette, environment, and desk props.

To manage this, the pipeline uses a 3-part re-grounding design:
- **Runner-side edit tracking** in `state.json.image_state` with a deterministic threshold of 6 webhook-driven edits.
- **Stage reference anchors** in `.codepet/stage_images/` so evolution can build from stable stage baselines.
- **Cloud-agent re-grounding mode** that restores style/identity anchors while carrying forward desirable narrative details seen in the latest image.

The runner increments edit counters only when a webhook is about to run. On successful re-grounding, the cloud agent resets counters and updates stage references as needed.

---

## Technical Highlights

### Multi-Repo Activity Scanning

Unlike simple commit counters, CodePet watches selected public and private repositories, detecting:
- Coding sessions (coherent clusters split by inactivity gaps, with continuity across hourly runs)
- Marathon sessions (>2 hours)
- Context switches (repos touched)
- Social activity (stars, PRs, followers)

### State Model (Feeding the Creative Engine)

| Stat | Range | Decay Rate | GitHub Input |
|------|-------|------------|--------------|
| **Hunger** | 0-100 | -5 per 6hrs without commits | Commit recency |
| **Energy** | 0-100 | -10 per 2hr+ coding session | Coherent session duration from commit timestamps |
| **Happiness** | 0-100 | -2 per day without social activity | Stars, PRs merged, followers |
| **Social** | 0-100 | N/A (cumulative) | Total stars + followers + forks |

### Evolution Stages

Based on **days of activity detected** (not necessarily consecutive):

| Stage | Active Days | Emoji | Visual Trait |
|-------|-------------|-------|--------------|
| Baby | 0-9 | 🐣 | Small, bouncy, needs constant attention |
| Teen | 10-49 | 🐥 | Awkward, moody, rapid stat changes |
| Adult | 50-199 | 🐤 | Stable, can handle longer absences |
| Elder | 200+ | 👑 | Wise, slow decay, "legendary" visual effects |

---

## Key Files

| File | Purpose |
|------|---------|
| `.codepet/activity.json` | Activity data for the period (feeds the Agent) |
| `.codepet/state.json` | Full pet state (feeds the Agent's creative decisions) |
| `.codepet/scripts/calculate_state.py` | Stable runner entrypoint/facade for state calculation |
| `.codepet/scripts/state_calc/` | Internal modules for state calc (`activity_detection`, `session_analysis`, `pet_rules`, `image_tracking`, `state_builder`, `io_utils`) |
| `.codepet/scripts/` | Back-off and webhook prep scripts (plus `cloud_agent/commit_to_master.sh` for direct commits) |
| `.codepet/stage_images/baby.png` | Canonical starting image and baby-stage re-grounding anchor |
| `.codepet/initial/initial_prompt.txt` | Description of your pet for the Agent to use |
| `.codepet/codepet.png` | Generated pet image (the Agent's artistic output) |
| `.codepet/stage_images/` | Canonical per-stage reference anchors for re-grounding/evolution |
| `.codepet/image_edit_prompt.txt` | Record of prompts used (Agent's creative audit trail) |
| `.github/workflows/codepet.yml` | GitHub Actions schedule configuration |
| `.github/workflows/codepet_reground.yml` | Manual force re-ground trigger |

---

## Transparency & Auditability

Every creative decision is committed to git:
- `git log -p .codepet/state.json` shows exactly how your pet evolved
- `git log -p .codepet/image_edit_prompt.txt` shows every creative decision the Agent made
- All Agent reasoning is visible and reproducible
- The Agent's "thought process" is preserved for analysis

---

## Making Magic Affordable


1. **Cost optimization** - 83% reduction in calls by separating mechanical from creative work
2. **Image Model Selection** - Each image edit should cost about 1¢.
3. **Cost Efficient Multimodal Reasoning Models** - Gemini 3 Flash has the vision skills to analyze images and exercise creative judgement.

---

## Technologies Used

- **Kilo Cloud Agents** - The creative engine (qualitative reasoning, image generation decisions)
- **GitHub Actions** - Mechanical state calculation (runs hourly)
- **GitHub Webhooks** - Trigger the Agent when creative updates are needed
- **fal.ai / Falcon** - Image generation pipeline (FLUX.2 Flash model)
- **PyGithub** - GitHub API integration for activity scanning
- **Gemini 3 Flash** - Vision analysis and prompt generation within the Agent

---

## Practical Utility

CodePet is a type of fun GitHub profile status widget:
- Displays current pet image in your README (Agent-generated art)
- Shows real-time stats (hunger, energy, happiness, social)
- Reflects today's coding activity and current streak
- Provides a narrative description of your pet's current state
- Evolves as you code, creating a living record of your development journey

---

*CodePet demonstrates that you can make automations delightful experiences that evolve with you. The Kilo Cloud Agent brings Byte to life.*
