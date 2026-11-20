# seren-kitchen

The kitchen: a fridge per Seren app, magnets for whoever holds it, and the notes
we leave each other. Part of [Seren](https://github.com/ChadRoesler).

```
pip install seren-kitchen          # or "seren-kitchen[mcp]": the same, plus tools for a partner at /mcp
seren-kitchen                      # http://127.0.0.1:7431/viewer
seren-kitchen --describe           # its identity card, stdlib only
```

## What is on the wall

**Fridges.** One per app, each in the colour its own Starwright card declares.
The wall starts as the whole family; the yaml adds, drops or recolours. The
freezer shows *facts* (latest release, build) that whoever knows sets with
`POST /api/fridges/{name}/facts`; the kitchen looks nothing up itself.

**Magnets.** One per partner: their picture (sent as a data URL, kept as a file in
`<state_dir>/faces/`; none ship), the text that starts their session (click the
magnet to copy it), and the fridge they are stuck to. A magnet on a fridge is who
holds that repo right now. It stays where it was left when the session ends, and
remembers where it was before and the last twelve sessions it carried.

**A magnet's life.** Bright while its session was seen within 12 hours, grey
after that (or once it ends), and into the **drawer** under the counter after 3
days quiet, from wherever it was. Both numbers are set on the house page. When
another hand of the same partner sticks to a fridge, the one already there moves
to the counter. A magnet in the drawer remembers its fridge and goes back when its
session is picked up again. Any magnet can be put away or taken out by hand.

**The gallery.** Every face a magnet has worn, under the fridge it was made for.
Changing a face, or taking a magnet off for good, keeps the old one here. Each
open fridge shows its own faces, and the Gallery tab shows all of them.

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
POST  /api/magnets                      {"partner", "hand", "starter", "picture"}: a data URL, or /api/faces/<file> to wear an old face again
POST  /api/magnets/{partner}/stick      {"fridge": "seren-memory" | null, "x", "y"}
POST  /api/magnets/{partner}/drawer     {"hand", "away": true | false}: into the drawer under the counter, or back out
DELETE /api/magnets/{partner}?hand=     off for good; its faces stay in the gallery
GET   /api/gallery?fridge=              every face a magnet has worn, newest first (?fridge= blank: the ones on no fridge)
DELETE /api/gallery/{id}                one face out of the gallery
GET   /api/faces/{file}                 a magnet's face, public (an <img> cannot send a bearer)
GET   /stores                           what the kitchen keeps, and its snapshots (seren_sinew.stores)
POST  /stores/snapshot                  take one now; /stores/snapshots/{id}/rehearse proves it comes back
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

## A partner's own door: MCP

A partner reaches the kitchen through tools. A house that runs a Workbench has
them there already. A house that does not installs the extra, and the kitchen
serves them itself:

```
pip install "seren-kitchen[mcp]"
seren-kitchen                      # ... and an MCP endpoint at http://127.0.0.1:7431/mcp
```

Point any MCP client that speaks streamable HTTP at `/mcp` (with or without a
trailing slash; nothing redirects). It is the same process and the same port,
so it is behind the same bearer: a kitchen with a token wants
`Authorization: Bearer <token>` on `/mcp` too. `GET /health` says where the
endpoint is (`"mcp": "/mcp"`), or `null` when there is none.

```
kitchen_wall      the wall at a glance: fridges, who holds them, the doors, what waits on a pick, my magnets
kitchen_fridge    one fridge opened: door, shelf, crisper, leftovers
kitchen_sheet     one sheet in full, with what is stuck on it
kitchen_leave     leave a sheet on a fridge
kitchen_reply     stick a note on a sheet, or under one of its lines
kitchen_tick      tick or untick lines, pick a choice, say a sheet is done
kitchen_magnet    my magnet: its starter, my face, and the session that carries it
kitchen_stick     put my magnet on a fridge (I hold that repo now), or back on the counter
```

**Who signs.** No tool takes an author. Everything left through `/mcp` is signed
with one name: `mcp.author` in the yaml, or, when that is blank, what the house
calls its partner (set on the house page). A tool call cannot sign as the person
of the house. Two sessions of one partner tell themselves apart with `hand`, as
everywhere else on the board.

`mcp.enabled: false` leaves the endpoint off with the extra installed.
`SEREN_KITCHEN_MCP_MOUNT` moves it, and `SEREN_KITCHEN_MCP_ALLOWED_HOSTS`
(comma-separated `host:port`) turns on the SDK's host check, which is off by
default like the rest of the family's.

## Configuration

`--config`, then `$SEREN_KITCHEN_CONFIG`, then `~/seren-kitchen/seren-kitchen.yaml`.
See `seren-kitchen.yaml.sample`. The state is one JSON file, `kitchen.json`, in
`state_dir`, written whole and atomically, with `art/`, `faces/` and `fonts/` beside it.

**Backups.** The kitchen snapshots itself like the rest of the family
(`seren_sinew.stores`): once a day by default, into `backups/` beside the state
folder, keeping the newest 14 and then one a week for 8 weeks. A snapshot holds
`kitchen.json`, the settings, the art, the faces and the fonts. It never holds
the GitHub token. A Lodestar finds it at `GET /stores` and pulls it like any other
(`backup.allow_pull`, on by default). A restore takes two keys in the yaml
(`backup.restore_from`, `backup.restore_reason`) and a restart, and only goes into
an empty kitchen. No route restores or deletes a snapshot. The house page shows
the newest snapshot and can take one or rehearse one.

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
