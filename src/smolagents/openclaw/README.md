# OpenClaw — affiliate-revenue engine on smolagents

OpenClaw is a self-contained subpackage that turns smolagents into a
fault-tolerant, persistent-memory affiliate-marketing revenue system.

It runs a fleet of **ten** niche agents — one per affiliate vertical — behind a
**daily observe-and-tweak optimizer** that adjusts each niche's traffic / CTR /
CR / AOV / commission lever weights and converges on a closed-form
**revenue formula**.

```
              ┌──────────────────────────────────────────────────┐
              │             OpenClawOrchestrator                 │
              │  ┌──────────────────────┐  ┌──────────────────┐  │
              │  │  DailyOptimizer      │  │ RevenueFormula   │  │
              │  │  observe → tweak →   │  │ per-niche weights│  │
              │  │  accept/reject loop  │  │ + closed-form    │  │
              │  └──────────────────────┘  └──────────────────┘  │
              │                ▲                  ▲              │
              │                │                  │              │
              │  ┌─────────────┴──────────────────┴───────────┐  │
              │  │ NicheAgent × 10 (smolagents.CodeAgent)     │  │
              │  └────────────────────┬───────────────────────┘  │
              │                       │                          │
              │  ┌────────────────────▼───────────┐  ┌────────┐  │
              │  │ PersistentMemory (SQLite/WAL)  │  │ Market │  │
              │  │ observations · tweaks · notes  │  │provider│  │
              │  │ · state                        │  └────────┘  │
              │  └────────────────────────────────┘              │
              └──────────────────────────────────────────────────┘
```

## The ten niches

| Slug | Title | Notes |
|------|-------|-------|
| `outdoor_gear` | Outdoor & Hiking Gear | High AOV, seasonal |
| `home_office` | Home Office & Productivity | High AOV one-shot |
| `smart_home` | Smart Home & IoT | Volume + cross-sell |
| `personal_finance` | Personal Finance & Credit Cards | CPA model (flat $) |
| `web_hosting` | Web Hosting & SaaS | Recurring (LTV multiplier) |
| `online_learning` | Online Learning Platforms | Recurring subs |
| `pet_care` | Pet Care & Supplies | Sticky audience, low vol |
| `eco_products` | Sustainable & Eco Products | High commission |
| `mobile_gaming` | Mobile Apps & Gaming | Volume play, viral |
| `fitness_wearables` | Health & Fitness Wearables | High AOV gadgets |

## Revenue formula

Per-niche, per-day:

```
R_n = T · CTR · CR · V · L · (1 - r)
```

with `V = AOV · commission` (rate-based niches) or `V = commission` (CPA).
`L` is the LTV multiplier for recurring niches, `1` otherwise. The optimizer
learns multiplicative weights on each lever; `formula.describe()` renders the
expression with the learned coefficients.

## Quick start (offline, no API keys)

```python
from smolagents.openclaw import OpenClawOrchestrator

with OpenClawOrchestrator() as oc:
    oc.run(days=30)
    print(oc.render_formula())
```

Or via the CLI:

```bash
openclaw init                    # writes openclaw.yaml
openclaw --db ./oc.db run --days 30
openclaw --db ./oc.db formula
openclaw --db ./oc.db status
```

## Switching to a real LLM

```yaml
# openclaw.yaml
memory_path: ./openclaw.db
seed: 1337
model:
  type: litellm           # or openai, inference_client
  model_id: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
```

The `OpenClawConfig` loader resolves the `api_key_env` at runtime, instantiates
the appropriate smolagents `Model` class, and hands one model per niche to the
fleet.

## Persistent memory

Everything lives in a single SQLite file (`memory_path`). Tables:

* `observations(agent_id, day, metrics, ts)` — daily per-niche metrics
* `tweaks(agent_id, day, lever, direction, accepted, delta_revenue, ts)`
* `notes(agent_id, day, note, ts)` — free-form journal
* `state(agent_id, key, value, updated_at)` — opaque KV (params, weights, …)

A killed-and-restarted process picks up at the same day, with the same
formula weights and per-niche params. WAL mode is on so concurrent reads are safe.

## Adding a niche

```yaml
niches:
  - slug: kitchen_gadgets
    title: Kitchen Gadgets
    affiliate_programs: ["Amazon Associates", "Williams Sonoma"]
    base_traffic: 1500
    base_ctr: 0.04
    base_cr: 0.025
    base_aov: 95.0
    base_commission: 0.05
```

You can also override curated niches by slug — only the fields you specify
get patched.
