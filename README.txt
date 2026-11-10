COGNAUT
=======

The cognitive revolution is here.


THE WHOLE FOLDER
----------------

  START.bat         the one thing you press (Windows)
  code.py           all the code, in one file
  data/             every user, record and uploaded file (appears on first run)
  LICENSE           what you may do with the code (GNU AGPL v3, see below)

  render.yaml       how Render runs it on the internet
  railway.json      how Railway runs it on the internet
  requirements.txt  tells hosts it is Python (it lists nothing: there is
  .python-version   nothing to install) and which Python to use

That is the entire thing. It needs Python 3.7 or newer and nothing else.


THE LICENSE, IN SHORT
---------------------

Copyright (c) 2026 Noah Dixon. Released under the GNU Affero General
Public License, version 3 -- the full text is in LICENSE, and it is the
version that counts. In plain words:

  - You may use it, copy it, change it and share it, for any purpose.
  - If you share a changed version, or run one as a website for other
    people, you must offer them its source code under this same
    license. Improvements stay open to everyone.
  - It comes with no warranty of any kind.


IF YOU GOT THIS FROM GITHUB
---------------------------

This is the program behind the Cognaut website. There are two ways to
use it:

  - Visit the website, if someone runs one. Nothing to download.
  - Run your own copy, on your own computer (see "To run it") or on the
    internet (see "Putting it on the internet"). Your copy starts empty
    and is a complete, separate site of its own: nothing you write in it
    reaches GitHub, or anyone else's copy.

On your own computer, the first name you add becomes that copy's
OPERATOR -- the one person who can start global communities and News
channels, and correct or take down anything (see "What the operator can
do" below). To make someone else the operator, put their name in the
GLOBAL_FOUNDER line near the top of code.py. On the internet the
operator is named in the host's settings instead.

One thing to be clear-eyed about: "nothing can be removed" and "nothing
can be backdated" are rules the site enforces on the people using it.
They do not bind whoever holds the data folder or runs the host: that
person can change records.db with any database tool. A copy is only as
permanent as its keeper.

The data folder is deliberately never uploaded to GitHub (the
.gitignore file sees to that). Keep it that way: it holds every record,
including private ones.


KEEPING WHAT YOU ALREADY WROTE
------------------------------

If you have run an earlier version, copy the "data" folder out of that
old folder and drop it into this one before pressing Start. Your users,
records, files and communities all carry over, and the code upgrades
the file in place.

Build 20 added passwords. Names made before then have none yet. On your
own computer, the first time you sign in as one of them, the password
you type becomes its password. On the internet a name without a
password cannot be signed into until the operator sets one.

Build 15 repaired something and every build since keeps it. Builds 7
to 14 quietly added one empty note to each record the first time you opened
your data with a newer build. That has stopped, and the empty notes
already there are removed, so records hold only what you actually put in
them.

Build 16 also found records from the very first version -- ones you
shared before communities existed, which had nowhere to sit and so
showed nowhere. They go into the oldest global community, which is the
only place they could have meant.


TO RUN IT
---------

Double-click START.bat. A black window opens and your browser opens to
the site.

Windows may say "Windows protected your PC" the first time, because the
file came from the internet. Click "More info", then "Run anyway".

Leave the black window open. It IS the website. Close it and the site
stops; nothing is lost, and you can press Start again any time.

On a Mac or Linux, open Terminal in this folder and type:

    python3 code.py

The site opens the same way. Press Ctrl+C in Terminal to stop it.


TO SEND IT TO SOMEONE
---------------------

Zip this whole folder -- including data -- and send it. When they press
START.bat they see every record you had, every file, the whole chain.
Their new records go into their copy of data.

The two copies do not talk to each other. Each is a complete, separate
site. That is what "self-contained" means here, and it is the honest
version of sharing until this lives on the internet.

Copy the data folder somewhere safe now and then. It is the only thing
in here you cannot regenerate.


HOW THE SITE WORKS
------------------

When you arrive it asks who you are: your name and your password. A
name nobody has yet becomes yours, with the password you give it (at
least 8 characters). On your own computer the names already here are
offered in a list; on the internet you type yours. You stay signed in
on that browser for 30 days, or until you press Sign out.

Choose "Just view" and you can read everything that is open to
everybody, but add nothing.

Forgotten your password? The operator can set a new one ("Reset a
password", beside their name) and tell you it. Nobody can see your
password -- it is never stored, only a one-way scramble of it.

Then pick a space:

  MY INTELLIGENCE          Everything you have written. Private to you
                           until you share it. Your name is signed after
                           the heading, in a hand.

  COLLECTIVE INTELLIGENCE  Three sections: My Network, Global
                           Communities and News.

  MY NETWORK           Yours. One screen holding two boxes, one above
                       the other, each growing with what is in it.

      MY COMMUNITIES   The communities you founded, and the ones you
                       have been let into or joined -- including one
                       deep inside somebody else's tree.
                       "+ Create community", "Browse communities",
                       "Remove community".
      MY NEWS          The same, for news channels.
                       "+ Create channel", "Browse news",
                       "Remove news".

  GLOBAL COMMUNITIES   Everyone's, and permanent. Where other people
                       find a record and respond to it.

  NEWS                 Everyone's, and permanent. Channels only -- no
                       projects, no tasks. A channel holds more channels
                       and the records published into it.


WHO CAN VIEW, WHO CAN CONTRIBUTE
-------------------------------

There are two settings, and each is one of two things:

  EVERYBODY       anyone with a name here, and the community appears
                  under "Browse communities" for people to join
  NAMED PEOPLE    only the founder and the people they tick

Open a community you founded and you get both buttons: "Who can view"
and "Who can contribute". They work identically.

On your own computer the dialog lists everyone to tick. On the internet
it lists only the people already let in, and you add anyone else by
typing their exact name -- otherwise anyone could found a community
just to see every account on the site.

They are not independent of each other. Anyone who can contribute can
obviously also view. And taking viewing away takes contributing with it
-- you cannot put something into a place you are not allowed to look at.

A community you make for yourself starts as named-people-only with
nobody named, so it is private exactly as before. A global community
starts open to everybody, which is how they have always behaved.

ACCESS REACHES DOWNWARD, NEVER UP
---------------------------------

The setting belongs to the community it is on, and covers everything
inside it. It says nothing about whatever holds it.

So if somebody is let into Metastasis, they get Metastasis and every
project, task and community inside it. They do not get Cancer Research
above it, or any of its other branches. Let them into Cancer Research
instead and they get the whole tree.

A community you are let into appears under MY COMMUNITIES on its own,
at whatever depth it sits, because that is as far up as you can go. It
is the top of the world as far as you are concerned.

Inside a community there are two separate buttons, and they are not the
same thing:

  + CREATE COMMUNITY        the founder's alone, and the founder of
     (or CREATE CHANNEL)    anything above it. The shape of a place is
                            theirs to arrange.
  + CREATE PROJECT OR TASK  any contributor. Communities only --
                            a channel has no projects or tasks.
  + ADD RECORD              any contributor.

An empty community or channel says nothing about itself. The buttons
under it already show what can go there.

A community can hold other communities, as deep as you like: cancer
research holding a community per kind of cancer, each holding its own.
It can also hold projects and tasks, which are the end of a branch --
they hold records, and nothing below them.

Records can be shared straight to any level: a community four deep, or
a task inside it. You are only offered the places you may contribute to.

For now only the operator can start a top-level GLOBAL COMMUNITY or NEWS
channel. Both sections are permanent and everybody's, so founding in
them is not a small act. Anyone can still make as many communities and
channels of their own as they like, under My Network, and anyone can put
records into a global community or a news channel that is open to them.
To change who may found one, edit the GLOBAL_FOUNDER line near the top
of code.py.

VIEWABLE OR EDITABLE
--------------------

Every row in MY NETWORK says which it is, and so does the heading of any
community, channel, project or task you open:

  (EDITABLE)   you may put records, and whatever else it holds, into it
  (VIEWABLE)   you may read it and nothing more

It is the same rule as everywhere else -- it is simply said out loud now,
rather than left for you to work out from which buttons appeared.


TAKING SOMETHING OFF YOUR OWN LIST
----------------------------------

Each box carries its own button, beside Browse: "Remove community" in
one, "Remove news" in the other. Press it and every row in THAT box
grows a Remove of its own; press each one you want gone. The button then
says Done -- press that and the rows go quiet again. The other box is
untouched throughout.

A box with nothing in it offers no Remove, there being nothing to remove.

It takes that community or channel off YOUR list. Nobody else's view
changes, nothing is deleted, and everything inside it is exactly where it
was. Browse offers it back whenever you want it again.


SEARCHING
---------

GLOBAL COMMUNITIES and NEWS each have a search box at the top. It looks
through the whole section, at any depth, and shows where each hit lives
-- "Phase III" under "Oncology / Clinical trials". Press one and you are
taken there.

It only ever finds what you are allowed to see.


WHAT THE OPERATOR CAN DO THAT NOBODY ELSE CAN
---------------------------------------------

For now one person is the operator, and it is the same name that founds
global communities and News channels. If the GLOBAL_FOUNDER line near
the top of code.py names someone, it is them; if that line is empty, it
is the first name ever added to this copy.

  CORRECT   Open a record and press Correct. You can change its
            function, its title, the text of any note and the address of
            any link. Files are left alone -- replacing one would be a
            different record.
  RENAME    Inside any community, channel, project or task, press
            Rename.
  TAKE DOWN Press Take down on a record, or inside a place. It stops
            being listed anywhere, for everybody.

Two things about this are worth being clear-eyed about.

First, nothing is destroyed. A take-down sets a marker that reading
filters out; the row stays in the file, and so does every response
hanging off it. An edit copies what the thing said before into a table
called "edits" first. So "nothing here can be edited or removed" has
become "nothing here can be edited or removed by anyone but the
operator, and even then the original is kept" -- which is a real change
to what the site promises, and worth saying plainly.

Second, these powers sit behind the operator's password and nothing
else, so choose a long one and keep it to yourself. On the internet the
operator's name is reserved when the site starts -- nobody can register
it first. The operator can also read anything, including what is
shared into communities they were never let into, so that they can
find what needs taking down. They cannot read anyone's unshared My
Intelligence through the site.

Also: "Reset a password", beside the operator's name, sets a new
password for someone who has forgotten theirs, and signs them out
everywhere.

A record that has been corrected says "corrected since" after its
timestamp, so nobody is misled about it being untouched.


NEWS AND CHANNELS
-----------------

A news channel is a community with one difference: it holds only more
channels, and the records published into it. No projects, no tasks.
Oncology holding Trials holding Phase III, as deep as you like.

There are two places channels live, and they behave like the two places
communities live:

  MY NEWS   yours. You make them, you say who sees them and who may
            publish. "Channels here can only be removed by the consent
            of all parties that have ever contributed."
  NEWS      everyone's, permanent, founded by one person for now.
            "Nothing here can ever be removed."

A channel you are let into or join appears under MY NEWS, exactly as a
community you join appears under MY COMMUNITIES.

Three functions were added for what tends to go into a channel: News,
Paper and Opinion. They sit in the same dropdown as Thought and
Critique, and they are available everywhere, not only in News.

A REWARD ON A TASK
------------------

Open a task and press "Reward". Put in an amount and, if you like, a
note saying what it is for. The task then carries the total, and the
list of who offered what.

Nothing is taken and nothing is paid. There is no money in this program
at all. A reward is a record that somebody said they would pay for the
task to be done -- the same kind of claim as a name is here.

Anyone who can see the task can offer. Offers add up, and like
everything else here they cannot be edited or withdrawn.

There are two ways a record leaves My Intelligence, and both are yours
to take deliberately.

WRITING ONE STRAIGHT IN. Stand inside any community, channel, project
or task you may contribute to and press "+ Add record". The dialog says
where it is going. The record lands there AND in your My Intelligence at
the same moment -- it is still your record, it is simply in both places
from the start.

SHARING ONE YOU ALREADY WROTE. Open it in My Intelligence and press
Share. You then choose one of four things:

  1. Keep it to myself      the default; nothing leaves
  2. My network             your communities and your channels; you can
                            make a new community right there
  3. Global communities     pick any; this cannot be undone
  4. News                   pick any channel; this cannot be undone

You can tick more than one, and you can share straight into a project,
a task or a channel rather than the community as a whole. A response
inherits wherever the record it answers already sits.

Responses sit underneath and slightly right of what they answer, as
deep as the chain goes, and they inherit whatever the parent belongs to.

Nothing in the Collective can ever be removed. Responses hang off what
they answer, so taking a record away would tear a hole in somebody
else's chain.

Every record is stamped the moment you write it. You cannot set the
time yourself, so nothing can be backdated.

A record needs a function. A title is optional -- what was done is the
record, and naming it is a convenience.

A record can carry as many links, files and notes as you want, in any
mix. A link and a note about it. A file, a link and three notes. Press
+ Link, + File or + Note as many times as you need.

Responses go as deep as you like. A response to a response to a
response steps further right each time.


ORGANISING THINGS (BOTH OPTIONAL)
---------------------------------

In MY INTELLIGENCE you can make files: named shelves for your own
records. Press "+ Create file", then choose the file from
the list at the bottom of any record you have opened. Records do not
need a file.

Clicking a file along the top narrows the view to it. Chains stay
whole: if any record in a chain is in the file, the whole chain still
shows, so a response never floats loose from what it answers.

A note on the word "file": a record can also BE a file (a PDF you
uploaded). Say the word and the organisational ones can be called
folders or collections instead.


REMOVING THINGS
---------------

Removal exists only in My Intelligence.

Open a record and press Remove. It asks once before doing it.

  A record you never shared    is gone.
  A record you did share       leaves your My Intelligence but
                               stays in the Collective, because nothing
                               there can ever be removed.

That second case is worth being clear-eyed about: the record keeps your
name on it in the Collective forever, and people can still respond to
it. Removing it here only tidies your own view.

Removing a file does not touch the records in it. They stop being
filed; nothing is lost.


ABOUT THE LINES AT THE BOTTOM
-----------------------------

Each section says what is true of it.

  MY INTELLIGENCE      "Nothing here can be edited once entered. Only
                       removed." Both halves are true.
  MY NETWORK           "Communities and channels can only be removed by
   AND BOTH ITS LISTS  the consent of all parties that have ever
                       contributed."
  GLOBAL COMMUNITIES   "Nothing here can ever be removed." Permanent by
                       design.
  NEWS                 The same. Permanent by design.

The Collective's opening screen carries no line at all -- not a blank
one, no line and no rule -- because the three sections below it promise
different things.


AM I LOOKING AT THE RIGHT VERSION?
----------------------------------

The black window's first line says which build it is, e.g. "build 21,
10 November 2026". Its second line shows the exact folder it is
running from.

Nothing on the page itself shows a build number any more. To check what
the page is actually being served, open

    http://localhost:3000/api/version

If that says an older build than the black window, the browser is
showing you a saved copy. Press Ctrl+F5 to force a fresh one.

If the black window warns that ANOTHER COPY IS ALREADY RUNNING, an
older window is still open and holding the usual address. Close every
black window, then press START.bat once.


IF SOMETHING GOES WRONG
-----------------------

"The site is not responding."
    The black Start window was closed, or never opened. Press START.bat
    again and use the browser tab it opens.

The black window says Python was not found.
    You have Anaconda, so Python is on this computer; Windows just
    cannot see it from a double-click. Open "Anaconda Prompt" from the
    Start menu, type  cd  and a space, drag this folder onto the window,
    press Enter, then type:  python code.py

The black window flashes and disappears.
    Something failed at startup. Open Anaconda Prompt as above and run
    python code.py there -- the error will stay on screen.

The site opens but looks unstyled.
    The two typefaces load from the internet. Offline, the site falls
    back to fonts already on your computer and still works.


PUTTING IT ON THE INTERNET
--------------------------

On your own computer the address is http://localhost:3000, and
"localhost" means "this computer" -- that link opens nobody else's site.
For one shared site that anyone can visit, the program runs on a
hosting service instead: a computer that never switches off. It reads
the code straight from your GitHub repository, and when you update
GitHub, the site updates itself.

It costs a few dollars a month, because the site needs a disk that
survives restarts and free plans do not keep one. As of November 2026:
Render's Starter plan is $7/month plus $0.25 per GB of disk; Railway's
Hobby plan is a $5/month minimum plus $0.15 per GB. Check their pricing
pages before you sign up.

Code.py notices by itself that it is on a host. There it listens to
the whole network, sends sign-in cookies over https only, refuses to
start without a lasting disk, stops publishing the list of names, and
takes the operator from the host's settings.

ON RENDER (recommended: it backs the disk up every day by itself)

  1. Sign in at render.com with your GitHub account.
  2. New > Blueprint. Choose the cognaut repository. Render reads
     render.yaml and shows one web service with a 1 GB disk.
  3. It asks for two values. OPERATOR: your name, exactly as you will
     sign in with it. OPERATOR_PASSWORD: your password, 8 characters or
     more. Neither is written anywhere public.
  4. Press Apply / Deploy, and add a payment card when asked.
  5. When the deploy says Live, your address is shown at the top:
     https://cognaut.onrender.com. Open it and sign in.

ON RAILWAY

  1. Sign in at railway.com with your GitHub account.
  2. New Project > Deploy from GitHub repo > cognaut.
  3. Right-click the empty canvas (or press Ctrl+K) and add a Volume;
     attach it to the cognaut service, mounted at /data. This is the
     disk; without it the site will not start, on purpose.
  4. In the service's Variables, add OPERATOR and OPERATOR_PASSWORD as
     above, and BANDWIDTH_GB (see "Keeping the bill small" below).
  5. In the service's Settings > Networking, press Generate Domain. That
     is your address.

EITHER WAY

  - The site will not start until both OPERATOR and OPERATOR_PASSWORD
    are set. That is deliberate: otherwise the operator's name would sit
    unclaimed, free for the first stranger to register.
  - OPERATOR_PASSWORD is only used to create the operator's account the
    first time the site starts. Afterwards the password lives in the
    site, like everyone else's; changing the setting does nothing.
  - Choose an OPERATOR name nobody has used on the site yet. If someone
    already signed up with that name, the site refuses to start rather
    than hand their account the operator's powers.
  - A web address of your own (cognaut.com, say) can be added later in
    the host's settings, after buying the name from a registrar.
  - Back up now and then. On Render, daily disk snapshots are kept
    for you. On Railway, keep your own copy: the data is records.db and
    the uploads folder on the volume.

KEEPING THE BILL SMALL

The host's fixed price does not change however popular the site gets:
it runs on one machine, and the disk is the size you chose. What does
grow is outgoing traffic. Render includes 5 GB a month and charges
$0.15 for each GB past that, and offers no way to set a spending limit
-- so the site sets its own.

  BANDWIDTH_GB   the most the site will send out in a calendar month.
                 render.yaml sets it to 20, which means at most about
                 $2.25 a month over the $7.25. Past it, every page shows
                 a short note that the site is resting until the 1st of
                 next month. Nothing is lost, and nobody can write either.
                 Raise or lower it in the host's Environment settings
                 whenever you like; the change applies on the next
                 restart. 0 means no limit.

Its own count runs a little below the host's (the host also counts the
encryption around each reply), so keep a few GB of headroom if the
number matters exactly. The black window -- on Render, the service's
Logs -- shows the month's total each time the site starts.

Also, so the allowance goes a long way:

  - Pages and lists are compressed, to about a quarter of their size.
  - A browser keeps the page and only checks it has not changed; the
    check costs a few hundred bytes instead of the whole page.
  - An open page checks for new records every half minute, and only
    while someone is looking at it. If nothing is new, the answer is
    empty.
  - Each visitor may download at most 300 MB of files an hour.

Render's billing page shows the month's traffic so far, and Render has
said it emails you when you near the included amount.

WHAT IT DOES TO KEEP PEOPLE SAFE ONLINE

  - Passwords are stored only as a slow one-way scramble. Sign-in lives
    in a cookie the page's own script cannot read, sent over https only.
  - The server decides who you are from that cookie alone, and checks
    on every request -- reading as well as writing -- that you may see
    or change what you asked for.
  - Uploaded files can never run as part of the site: web pages come
    back as plain text, and nothing uploaded may run scripts.
  - Each visitor's address is limited in how fast it may sign in, make
    names, change things and upload, so one script cannot guess
    passwords all day or fill the disk. Wrong guesses slow the guesser,
    never lock out the account's owner.
  - Another website cannot act on behalf of someone signed in here.

WHAT IS STILL TRUE ONCE IT IS ONLINE

  - Whoever runs the host can read everything on the disk, private
    records included. That is you. Say so to the people you invite.
  - There is no email: a forgotten password goes through the operator.
  - The server is Python's own small one, behind the host's front door,
    which handles the https. It is fine for a modest number of people.
    A large audience would want a sturdier server in front of it.
  - The page loads its three typefaces from Google Fonts, so visitors'
    browsers contact Google. If that matters to you, the fonts can be
    served from the site itself instead.
  - Running a site that holds other people's writing can bring legal
    duties (privacy laws, takedown requests) depending on where you and
    they live. Worth a look before you invite strangers.


CHANGING IT
-----------

Everything is in code.py. Open it in any text editor.

  The list of functions    the FUNCTIONS line, in the page's script
  Project and task kinds   the options in the groupDialog section
  The help paragraph       the helpDialog section
  How it looks             the :root block near the top of the page --
                           black and white is two values, --ink and
                           --paper, and nothing else names a color
  Who the operator is      the GLOBAL_FOUNDER line, near the top
  The ten tables           the SCHEMA section
  The sections and lines   the SECTIONS block, in the page's script
  The rules for a record   the create_entry method
