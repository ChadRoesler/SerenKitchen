# seren-kitchen

The kitchen: a fridge per Seren app, magnets for whoever holds it, and the notes
we leave each other. Part of [Seren](https://github.com/ChadRoesler).

```
pip install seren-kitchen
seren-kitchen                      # http://127.0.0.1:7431/viewer
seren-kitchen --describe           # its identity card, stdlib only
```

## What is on the wall

**Fridges.** One per app, each in the colour its own Starwright card declares.
The wall starts as the whole family; the yaml adds, drops or recolours. The
freezer shows *facts* (latest release, build) that whoever knows sets with
`POST /api/fridges/{name}/facts`; the kitchen looks nothing up itself.

**Magnets.** One per partner: their picture (a data URL they provide; none ship),
the text that starts their session (click the magnet to copy it), and the fridge
they are stuck to. A magnet on a fridge is who holds that repo right now. It stays
where it was left when the session ends, and remembers where it was before.

**Sheets.** A sheet is one piece of paper: a title in someone's hand and lines
under it that can be ticked. A list is one sheet with many lines; a thought is a
sheet with one. Its kind says where it sits:

| kind       | sits on      | what it is                                        |
|------------|--------------|---------------------------------------------------|
| `now`      | the door     | honey-do now                                      |
| `list`     | the shelf    | honey-do list                                     |
| `person`   | the door     | a note to the person of the house (`house.person` names them) |
| `other`    | the door     | a note to the partner (`house.partner` names them)  |
| `self`     | the door     | a note to self                                    |
| `art`      | the crisper  | a picture, a sketch, a link to one                |
| `decision` | the door     | options and a pick; unpicked past `sour_after_days` it goes sour |

Every line ticked, or `done`, moves a sheet to the **leftovers**. A pick
finishes a decision. `DELETE` takes a sheet off the fridge for good.

## The API

```
GET   /api/kitchen                      the wall: fridges, magnets, the sheets on the doors
GET   /api/fridges/{name}               one fridge opened: door, shelf, crisper, leftovers, magnets
POST  /api/fridges/{name}/facts         {"release": "5.6.1", "build": "ok"}; null forgets a key
POST  /api/fridges/{name}/sheets        {"kind", "title", "lines": [], "author", "pin", "options": []}
GET   /api/sheets?fridge=&kind=&place=&author=&open=true
GET   /api/sheets/{id}
PATCH /api/sheets/{id}                  title | lines | add_lines | tick | untick | place | x | y | rot | pin | fridge | done | pick
DELETE /api/sheets/{id}
GET   /api/magnets
POST  /api/magnets                      {"partner", "starter", "picture"}
POST  /api/magnets/{partner}/stick      {"fridge": "seren-memory" | null, "x", "y"}
DELETE /api/magnets/{partner}
POST  /api/sheets/{id}/reply            {"kind", "title", "lines", "author", "line"}: a sheet stuck on a sheet
POST  /api/sheets/{id}/art              the request body IS the picture (image/png, jpeg, gif or webp; 8 MB at most)
GET   /api/art/{file}                   a sheet's picture, public (an <img> cannot send a bearer)
POST  /api/freezer/refresh              read GitHub for every fridge now
GET   /api/fonts/{name|freezer|hand}    the configured font file, public (a stylesheet cannot send a bearer)
```

Pictures live as files in `<state_dir>/art/`, one per sheet, and come down with
the sheet. The freezer (`github:` in the yaml) reads each fridge's latest release
or tag and the last workflow run's conclusion, once an hour unauthenticated; a
token named by `github.token_env` lifts GitHub's ceiling.

A refusal is a `400` with the reason in plain words. Writes are guarded by the
bearer like the rest of the family; loopback with no token is open, and a wider
bind without one is refused at startup.

## Configuration

`--config`, then `$SEREN_KITCHEN_CONFIG`, then `~/seren-kitchen/seren-kitchen.yaml`.
See `seren-kitchen.yaml.sample`. The state is one JSON file, `kitchen.json`, in
`state_dir`, written whole and atomically; back it up with `cp`.

Fonts are paths on the box, never shipped: `fonts.name` (the repo name on the
freezer), `fonts.freezer` (the facts), `fonts.hand` (the notes), and
`fonts.hands` (one hand per author: a sheet signed by that name is drawn in
that font). Unset, the page falls back to system fonts. `house.person` and
`house.partner` are the names the page puts on "to the person" and "to the
partner".

## Why it is the way it is

`DESIGN.md` beside this file holds the reasons behind the kitchen's shape:
what each decision was for, so a change can be made knowing what it undoes.

## License

AGPL-3.0-or-later.
