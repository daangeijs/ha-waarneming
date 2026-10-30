## 0.2.2

- Config flow: the example area link is a description placeholder (hassfest rejects URLs in strings).
- User-Agent carries the real version.

## 0.2.1

- Brand icon and logo in `custom_components/waarneming/brand/` (shown by Home Assistant 2026.3+ without the brands repository).

# Changelog

## 0.2.0

Display-ready fields, so a small e-paper screen only has to print.

- Every item in `sightings` gains `title` ("3× Kraanvogel ?"), `subtitle` ("Heidebos · 3,2 km", decimal comma; the
  area name when there is no distance) and `ts` (observation time as Unix epoch seconds, UTC).
- `observed_at` now carries the UTC offset (`2026-10-27T09:15:00+01:00`). The API's times are Dutch local time; a
  date-only sighting stays a bare date and counts as 12:00 local for `ts`.
- The list is sorted by `ts`. A date-only sighting now sorts as midday instead of before every timed sighting of
  that day.
- New top-level attribute `updated`: epoch seconds of the last successful fetch. Not recorded in history.
- All existing fields are kept.

## 0.1.0

First release: rare sightings around the Home zone and in chosen waarneming.nl areas as one sensor.
