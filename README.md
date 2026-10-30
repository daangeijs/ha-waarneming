# Waarneming for Home Assistant

A Home Assistant integration that turns recent rare sightings from [waarneming.nl](https://waarneming.nl) /
[observation.org](https://observation.org) into one sensor: how many rare birds were seen around your Home zone and in
the waarneming.nl areas you follow, with the newest ones (Dutch names) in an attribute.

It replaces the REST + template YAML recipe for the HA Paper "rare birds" tile and produces the same entity, so a
tile built on the recipe keeps working.

## Install (HACS custom repository)

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/daangeijs/ha-waarneming`, type **Integration** → **Add**.
3. Search for **Waarneming** in HACS, **Download**, then restart Home Assistant.
4. Settings → Devices & services → **Add integration** → **Waarneming**.

## Configuration

Everything is set in the UI. After setup, **Configure** on the integration changes any of it.

| option | default | notes |
|---|---|---|
| Name | Rare birds nearby | gives the entity id: `sensor.rare_birds_nearby` |
| Around my Home zone | on | sightings within the radius of `zone.home`; the location is read at each update and never stored |
| Radius | 10 km | 1–10 km (the API's maximum is 10 km) |
| waarneming.nl areas | none | area ids or pasted links, one per line, e.g. `701925` or `https://waarneming.nl/locations/701925/` (Oostvaardersplassen - N2000). Sub-areas count too. |
| Minimum rarity | 3 | 1 common, 2 fairly common, 3 rare, 4 very rare (per species, for that place) |
| Days back | 3 | 1–14 |
| Species group | 1 | 1 = birds |
| Max sightings in the list | 10 | the state still counts all of them |
| Update every | 30 min | options only; never less than 15 minutes |

Each area id is checked with one API call when you add it, and its name ("Oostvaardersplassen - N2000") is looked up
and saved; it shows in the confirm step, in the options form, and as `region` on every sighting from that area. In
the options form, untick an area to stop following it, or paste new ids/links to add more.

The home zone, areas, or both: at least one source is needed. Escaped birds (`is_escape`) are always dropped;
uncertain sightings stay, marked with " ?". A sighting that two sources return (an area inside your radius) is shown
once, with the region of the first source (home first, then the areas in the order you added them).

## The entity

`sensor.rare_birds_nearby` (unit `waarnemingen`, icon `mdi:bird`)

- **state**: number of sightings after the filters, all sources together
- `sightings`: newest first (by `ts`), at most *max sightings*, each:

  ```json
  {
    "title": "3× Kraanvogel",
    "subtitle": "Heidebos · 3,2 km",
    "ts": 1793088900,
    "species": "Kraanvogel",
    "scientific": "Grus grus",
    "count": 3,
    "place": "Heidebos",
    "distance_km": 3.2,
    "observed_at": "2026-10-27T09:15:00+01:00",
    "rarity": 3,
    "certain": true,
    "region": "Rond huis",
    "url": "https://waarneming.nl/observation/123456789/"
  }
  ```

  The first three fields are ready to print, so a small display does no formatting of its own:

  - `title`: the Dutch name (the scientific name when there is none), `" ?"` appended when the sighting is not
    certain, and `"3× "` in front when more than one bird was counted.
  - `subtitle`: place and distance from your Home zone with a decimal comma (`"Heidebos · 3,2 km"`). Without a
    distance, an area sighting shows the area instead (`"Heidebos · Oostvaardersplassen - N2000"`), or just the place
    when the place is the area.
  - `ts`: observation time as Unix epoch seconds (UTC).

  waarneming.nl gives date and time as Dutch local time. `observed_at` is that time in ISO form with its UTC offset
  (`+01:00` in winter, `+02:00` in summer), or only the date when no time was recorded; such a sighting gets 12:00
  local time for `ts` and for sorting. On the night the clocks go back, a time between 02:00 and 03:00 is read as
  summer time. `distance_km` is measured from your Home zone, also for area sightings, and is `null` when the
  observation has no point or the home zone is unknown. Sightings from the home-zone source have
  `region: "Rond huis"`.
- `updated`: Unix epoch seconds of the last successful fetch
- `radius_km` (`null` when the home zone is off), `min_rarity`, `days`
- `attribution`: `Data: waarneming.nl / observation.org`

`sightings` and `updated` are kept out of the recorder's history; they are only useful now.

When waarneming.nl cannot be reached the sensor becomes unavailable (logged once, and once again when it recovers).
When the API answers 429 the next try waits for its `Retry-After`, or an hour.

## HA Paper tile

On the X4 Home web console add a **List from attributes** tile and pick `sensor.rare_birds_nearby`. Point it at
`title`, `subtitle` and `ts`, with the `attribution` in the foot. Older tiles that read `species`,
`place distance_km` and `observed_at` keep working.

## Data and attribution

Data comes from the public waarneming.nl API (anonymous GETs, `Accept-Language: nl` for Dutch names), with a
User-Agent that names this integration. observation.org agreed to this use: a personal Home Assistant polling every
30 minutes. Please keep the interval at 30 minutes or more and keep the attribution visible. This integration is not
made by or affiliated with observation.org.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

The test fixtures are made-up observations.

## License

MIT, see [LICENSE](LICENSE).
