# Preserve Roles in Modified Balanced Baskets

**Date:** 2026-08-02
**Status:** Approved design

## Problem

Portfolio Randomize creates a balanced basket with a saved seed, composition,
and per-symbol roles (`mover`, `anchor`, or `noise`). The setup wizard currently
deletes the entire `basketGeneration` object when the user changes either date
or any ticker row. As a result, the post-simulation Review reports every role
as `unknown`, including randomized symbols whose provenance is still known.

The application also gives an explicit `unknown` role precedence over a valid
role in `basketGeneration` in several reconstruction paths. That prevents valid
generation metadata from repairing an incomplete ticker or legacy payload.

## Desired Behavior

Treat a role as provenance: it records how a symbol entered the original
randomized basket. Editing the setup must not reclassify a symbol based on its
new dates.

The preservation and modified-state rules apply to both generated modes:
`balanced` baskets and same-year-only randomizations. In same-year mode every
original generated symbol has role `mover`.

- An unchanged randomized symbol retains its original role.
- A newly typed or runtime-added symbol has role `unknown`.
- A removed symbol is omitted from current-basket role counts.
- Changing the generated dates, symbol membership, or symbol order marks the
  basket as modified rather than deleting its provenance.
- Reverting all edited dates and symbols to their original values clears the
  modified state.
- Changes to cash, benchmark, pre-entry levels, position size, or stops do not
  mark the basket modified because they do not change basket provenance.
- Existing sessions without generation metadata remain `unknown`; roles must
  not be guessed retrospectively.

## Generation Metadata

New randomizations add enough immutable origin data to compare the submitted
setup with the generated setup:

```json
{
  "version": 2,
  "mode": "balanced",
  "seed": "...",
  "composition": {"mover": 2, "anchor": 2, "noise": 2},
  "roles": {
    "MOVE": "mover",
    "LIQ": "anchor",
    "COMPARE": "noise"
  },
  "origin": {
    "startDate": "2020-01-15",
    "endDate": "2020-06-15",
    "symbols": ["MOVE", "LIQ", "COMPARE"]
  },
  "modified": false
}
```

`composition` and `seed` continue to describe the original randomization.
`roles` retains the original symbol-to-source mapping even when a symbol is
temporarily removed, allowing its role to return if the user restores it.
`modified` describes whether the current submitted setup differs from
`origin`. Version-1 and legacy objects remain readable.

## Reconciliation

Before validation/persistence and after relevant runtime basket changes, one
reconciliation function compares normalized current dates and ordered symbols
with the immutable origin snapshot.

For each current ticker, role resolution uses this precedence:

1. a valid explicit role on the current ticker;
2. a valid role from `basketGeneration.roles[symbol]`; then
3. `unknown`.

An explicit `unknown` must not override a valid generation role. This rule is
used consistently by controller bootstrap, live Review metadata, Stats session
reconstruction, saved-review reruns, and runtime ticker management.

The original role map is never pruned. Current composition is derived from the
current basket entries when Review renders, so removed symbols do not count and
new symbols increase the `unknown` count.

## Review Presentation

For an untouched generated basket, Review continues to show:

```text
BASKET ORIGIN  balanced  mover 2  anchor 2  noise 2  seed ...
```

For an edited basket, Review shows:

```text
BASKET ORIGIN  balanced · modified  mover 2  anchor 1  noise 2  unknown 1  original seed ...
```

The role column remains hidden during setup and live simulation. It is revealed
only by the existing final-review rules. The modified label makes clear that
the seed identifies the original draw but no longer reproduces the edited
basket exactly.

## Error and Compatibility Behavior

- Malformed role strings resolve to `unknown` unless the generation map has a
  valid role for that symbol.
- A legacy generation object without `origin` preserves its known roles but is
  not claimed to be modified based on unavailable origin data.
- A session with neither valid per-ticker roles nor generation metadata remains
  `unknown`.
- No role is inferred from ticker identity, year, price history, or present-day
  anchor membership.

## Testing

Regression tests must prove:

1. date edits preserve every original role and mark the basket modified;
2. replacing or adding a ticker preserves unchanged roles and assigns the new
   ticker `unknown`;
3. removing a ticker excludes it from current composition;
4. restoring the original dates and ordered symbols clears `modified`;
5. cash, benchmark, and trade-level setup edits do not mark it modified;
6. valid generation roles override explicit `unknown` placeholders through
   controller, Review, Stats reconstruction, and rerun paths;
7. Review displays current counts, an unknown count when needed, and the
   `balanced · modified` label; and
8. version-1 and metadata-free legacy sessions remain backward compatible.

The focused JavaScript portfolio tests and the broader offline/setup regression
suite must pass. A live browser check must randomize a balanced basket, edit a
date or ticker, start the simulation, and confirm that unchanged roles appear
in the post-simulation Review.

## Non-goals

- Reclassifying a randomized ticker after the date range changes.
- Guessing roles for historical sessions that never stored provenance.
- Exposing roles before final Review.
- Changing balanced-basket allocation or anchor eligibility rules.
