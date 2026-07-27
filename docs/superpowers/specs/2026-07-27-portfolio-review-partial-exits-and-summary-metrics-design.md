# Portfolio Review Partial Exits and Summary Metrics

## Goal

Make the end-of-portfolio-simulation review accurately reconstruct the trade as executed, and show the same win-rate and capital-deployment metrics used by the Stats dashboard.

## Design

### Review markers

Persist each leg's normalized event log in the Stats trade record's `eventsLog` field. Each event retains its type, date, quantity, price, direction, and leg ID when available. When a session is reopened for review, rebuild chart markers from that stored log so entries, adds, partial sells or covers, stops, and final closes all appear with their quantity and fill price.

For older trade records without an event log, preserve the existing fallback that synthesizes a final-exit marker from the trade's exit fields.

### Shared summary metrics

Create one portfolio-performance calculation inside `SimStats` and use it for both:

- the automatic end-of-simulation summary; and
- the session written to the Stats dashboard.

The calculation keeps the dashboard's existing definitions:

- Win rate: profitable recorded trade legs divided by all recorded trade legs.
- Average capital deployed: the mean daily `max(0, (equity - cash) / equity)` over the portfolio equity curve, preserving the Stats dashboard's existing clamp for short-position cash accounting.
- Peak capital deployed: the maximum daily deployed percentage over that curve.

The end summary will display win rate with the win/trade count, plus average and peak capital deployed. Existing Stats records and older saved reviews remain readable.

## Testing

Add regression coverage that proves:

1. extracted trade records retain partial-exit events;
2. session review reconstruction prefers the stored event log and retains the legacy final-exit fallback;
3. the end summary and Stats persistence call the same portfolio-metrics calculation; and
4. win rate and average/peak deployment are rendered automatically in the end summary.
