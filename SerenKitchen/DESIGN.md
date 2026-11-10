# Why the kitchen is the way it is

Reasons, not rules. Each of these is a decision that could have gone another
way and went this way for a reason. If you change one, change it knowing what
it was for.

## The metaphor is the information architecture

- **One big fridge, little fridges as polaroids.** The landing is one fridge
  the size of the page. Each app is a polaroid taped to its door, a mini
  fridge in the app's own colour: name, version, build dot, handles, who
  holds it, up to three tiny notes. Hover and it grows; click and it opens;
  drag it by the tape and the wall reorders. The joke (who takes a picture
  of a fridge and puts it on a fridge?) is also the whole glance: one page,
  everything at once, nothing hidden behind a menu.
- **Each fridge wears its app's colour.** The accent is the one the app's
  own installer card declares, so a fridge is recognisable from across the
  room, and the page picks dark or light ink per colour by contrast rather
  than by hand.
- **A freezer is about half the door.** Real fridges are. The freezer holds
  the name, the release and build in magnet letters, and the dispenser; the
  door holds the notes and the magnets. An empty door says EMPTY in magnet
  letters rather than whispering it.
- **Magnet letters are many-coloured with a thin black edge**, like the
  plastic ones from a bag. The release and build are read from the repo's
  own releases and workflow runs; nothing here is typed in.
- **The dispenser.** An ice-maker button on the freezer polls that one
  fridge now; the big fridge has one that polls them all. It fits the
  object, and a person already knows what a button on a fridge does.
- **The leftovers are a drawer.** Everything finished goes to the bottom of
  the fridge, closed until pulled, because what is done only grows and
  should not crowd what is not.
- **No fridge open is a fridge too**: grey, door swung out, light on,
  shelves empty, and clicking it takes you back to the wall. An empty state
  that is also the way home.

## Sheets, not tasks

- **A sheet is a note.** A title in someone's hand, a note, and an optional
  list. A thank-you, a drawing, a line of a song is as welcome on a door as
  a honey-do. Only sheets with lines or choices wait on anyone.
- **A list is one sheet with many lines**, not many sheets. A honey-do list
  is one piece of paper. Lines tick; a sheet of plain lines all ticked
  finishes itself.
- **Choices live on a line, not on the whole sheet.** A line that ends
  `? a | b | c` is a choice. Universal options on a note felt wrong; a line
  with options reads the way a person writes one.
- **Deciding is not finishing.** Picking a choice does not send a sheet to
  the leftovers. A sheet with choices stays where it was once they are
  picked, for whoever picks the work up, until someone says done. Otherwise
  a decision vanishes the moment it is made, which is exactly when it is
  most needed.
- **Milk goes off.** A choice nobody has picked past the house's bar is
  sour, and the page says so. Waiting is visible; it is never a quiet queue.
- **A missing title takes the first line.** Refusing a note for lacking a
  title punishes the person who had the least to say.
- **Replies are sheets stuck on sheets**, drawn under the line they answer,
  each saying who stuck it and when. A reader at nine in the morning with no
  coffee should see what answers what without working it out.
- **Pictures are never shrunk** in the full view, only fitted on cards; more
  than one makes a small gallery that turns on its own. A picture is someone
  spending time on you; it is shown at full size.
- **Cards are the glance; the sheet is the dialog.** A shelf shows title,
  a line of the note, how much is left and the first picture. Click to see
  everything. Long sheets stay short on the shelf.
- **Notes pile up on a door where they were left**, overlapping, newest on
  top, shrinking a little as the pile grows. A fridge should look lived in,
  not laid out.

## Magnets

- **A magnet is who holds a repo right now**, not a login. A session that
  only talks needs no magnet. A magnet stays where it was left when the
  session ends, so the next one in sees who was here, and it remembers
  where it was before.
- **A magnet carries a session starter.** Click it and the text that starts
  that partner's session is copied. The board is also the switchboard.
- **Pictures on magnets are each house's own.** None ship.

## Hands and names

- **Each author has their own hand.** A sheet signed by a name is drawn in
  that person's font; everyone else writes in the house hand. Handwriting
  tells you who is talking before you read a word.
- **Fonts are files on the box, never in the package.** A display face is
  whatever the house holds a licence for; a hand is whoever lives there.
  They are uploaded from the page and kept beside the state.
- **The house names its people.** The kinds are `person` and `partner`; the
  page puts the house's own names on them. The package ships with no names
  in it.
- **Tidy** is a setting: every note straight, galleries still, defaulting to
  on when the system asks for reduced motion. A tilt is a texture, not a
  requirement.
- **The hinge is a setting.** Handles on the right suit a left hand; a
  right-handed house flips them.

## Where things live

- **One JSON file, written whole through a rename.** A kitchen holds a few
  hundred sheets, not millions. A file a person can open, back up with `cp`
  and read after the service is gone is worth more than a query planner,
  and a crash mid-write leaves the old kitchen rather than a torn one.
- **Pictures and fonts are files beside it**, named by what they belong to,
  and come down with it.
- **The yaml is what an installer can know**: where to listen, where the
  state lives. Everything a house decides after moving in (fonts, the
  GitHub token, which fridges, whose names, how long milk keeps) is set from
  the page and kept in the state folder. Nobody should edit a file on a box
  to change a colour, and a token should never be a config flag.
- **The GitHub token is written once and never read back out.** It is a
  600 file in the state folder; the page says only whether one is set.
  Without one GitHub allows 60 calls an hour and a pass costs two per
  fridge, so the freezer defaults to an hourly pass, waits after a restart
  when its facts are fresh, and says in words when the budget is spent and
  when it comes back.
- **The kitchen never reads or writes a partner's own stores.** It is a
  shared surface between the people of a house. What each of them remembers
  is theirs alone.
- **Refusals are 400s in plain words.** The store says why; the page shows
  it; nobody reads a stack trace to learn a title is too long.
- **Fonts and pictures are served without a bearer.** A stylesheet and an
  image tag cannot send one. Everything else is guarded like the rest of
  the family.

## Small things

- A cheese on the counter. Leave it alone.
- There are a few other small things in the page that nobody is told about.
  Finding them is better than reading about them.
