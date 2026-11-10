# Cognaut
# Copyright (C) 2026 Noah Dixon
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public
# License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program, in the file LICENSE. If not, see
# <https://www.gnu.org/licenses/>.

"""
Cognaut
A thought should not be bound by the thinker.

This one file is the entire website: the page, the styling, the behaviour,
the database shape and the server. It uses nothing but Python's standard
library, so there is nothing to install.

You do not run this file directly. Double-click START.bat instead.

Everything anybody records is written into the "data" folder next to this
file. That folder is the site. Zip this whole folder, send it to someone,
and when they press Start they see exactly what you saw.
"""

import base64
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import signal
import sqlite3
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, parse_qs

# Bumped every time this file changes. It is printed in the console window
# and shown in the corner of the page, so "am I looking at the new version?"
# is answerable in one glance instead of a guess.
VERSION = "build 21"

# Two ways this file runs, and it works out which by itself:
#
#   ON YOUR OWN COMPUTER  (START.bat)  -- the site is for this machine only.
#   ON A HOST             (Render, Railway) -- the site is on the internet.
#
# On a host, the hosting service sets RENDER or RAILWAY_ENVIRONMENT, or you
# set PUBLIC_SITE=1 yourself. Being on the internet changes four things:
# it listens to the whole network, it insists on a disk that survives
# restarts, sign-in cookies are sent over https only, and the operator must
# be named in the host's settings (see below), never left to chance.
PUBLIC = bool(os.environ.get("PUBLIC_SITE") or os.environ.get("RENDER")
              or os.environ.get("RAILWAY_ENVIRONMENT"))

# The operator: the one person who may found a global community or a News
# channel, and who may edit or take down anything anywhere.
# Everyone founds their own communities and news channels freely -- the gate is
# only on the two permanent public sections and on the operator's powers.
#
# ON YOUR OWN COMPUTER: left empty, the operator is whoever was the FIRST name
# ever added to this copy -- normally the person who downloaded it and pressed
# Start. Put a name between the quotes to choose someone else, e.g.
# GLOBAL_FOUNDER = "Ada Lovelace".
#
# ON A HOST: the operator is the OPERATOR setting in the host's dashboard, and
# their first password is OPERATOR_PASSWORD there. The account is made with
# that password when the site starts, so nobody else can claim the name first.
# Neither value belongs in this file, which is public on GitHub.
GLOBAL_FOUNDER = os.environ.get("OPERATOR", "").strip() or ""

# The two kinds that can hold other things. Everything else is a leaf that
# holds only records: a project, a task, or whatever kind someone typed.
HOLDERS = ("Community", "Channel")
BUILD_DATE = "10 November 2026"

HERE = os.path.dirname(os.path.abspath(__file__))
# Railway names the disk it attached; Render is told DATA_DIR in render.yaml.
DATA_DIR = (os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
            or os.path.join(HERE, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "records.db")

# On your own computer, bind to this computer only. Not 0.0.0.0 — that asks
# Windows Firewall for permission, and a denied prompt is the usual reason the
# page loads but every action then fails. On a host, the host's own front door
# talks to us over its network, so we listen on all of it.
HOST = os.environ.get("HOST") or ("0.0.0.0" if PUBLIC else "127.0.0.1")
FIRST_PORT = int(os.environ.get("PORT", "3000"))

# Sign-in. A password is never stored, only a slow one-way hash of it, and a
# signed-in browser holds a random key in a cookie the page's script cannot
# read. The server decides who you are from that key alone.
# Which header carries a visitor's real address, decided by the host.
CLIENT_IP_HEADER = (os.environ.get("CLIENT_IP_HEADER")
                    or ("True-Client-IP" if os.environ.get("RENDER") else "")
                    or ("X-Real-IP" if os.environ.get("RAILWAY_ENVIRONMENT") else ""))

# A ceiling on how much this site sends out in a calendar month, in GB.
# Hosts charge for outgoing traffic past a small allowance, and none of them
# offers a spending cap, so the cap lives here. Past it the site shows a
# short notice until the 1st of next month; nothing is lost. 0 = no cap,
# which is right on your own computer. Set BANDWIDTH_GB in the host's settings.
BANDWIDTH_GB = float(os.environ.get("BANDWIDTH_GB") or 0)

MIN_PASSWORD = 8
SESSION_COOKIE = "sc_session"
SESSION_DAYS = 30
HASH_ROUNDS = 260_000

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DEPTH = 12          # communities inside communities, at most this many levels

# Uploaded files that may be shown as themselves inside the page. Anything
# else is shown as plain text or handed over as a download.
SHOW_AS_IS = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
              "image/bmp", "image/svg+xml", "application/pdf"}
TEXT_FILES = set(("txt md markdown json csv tsv js jsx ts tsx py rb go rs java c h cpp "
                  "hpp cs php html htm css scss sass yml yaml toml ini sh bash zsh sql r m "
                  "swift kt xml log tex lisp clj hs ml pl lua vim cfg conf env").split())
MAX_TEXT_CHARS = 200_000
MAX_BODY_BYTES = 40 * 1024 * 1024

UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)
URL_RE = re.compile(r"^https?://\S+$", re.I)


# ===========================================================================
# THE DATA MODEL — two tables, and that is all of it.
# ===========================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  name_key    TEXT NOT NULL UNIQUE,   -- lowercased, so "noah" and "Noah" are one person
  created_at  TEXT NOT NULL,
  pass_hash   TEXT,                   -- never the password itself; see hash_password
  is_operator INTEGER                 -- on a host: the account made from OPERATOR
);

-- Who is signed in. The browser holds a random key; this table holds only a
-- hash of it, so a copy of this file does not let anyone sign in as anyone.
CREATE TABLE IF NOT EXISTS sessions (
  key_hash    TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);

-- How much the site has sent out each month, so it can stop before the
-- host's bill grows. One row per month: '2026-11' -> bytes.
CREATE TABLE IF NOT EXISTS usage (
  month       TEXT PRIMARY KEY,
  bytes       INTEGER NOT NULL
);

-- An organizational file: a named shelf inside one person's Personal
-- Intelligence. Entirely optional; a record needs no file.
CREATE TABLE IF NOT EXISTS folders (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  name        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

-- The Collective is a tree. A community with no parent sits at the top; a
-- community can also live inside another community, to any depth (cancer
-- research holding a community per kind of cancer). Projects and tasks are
-- leaves: they live in a community and hold nothing below them. Everything
-- here must be named.
CREATE TABLE IF NOT EXISTS groupings (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,        -- Community, Channel, Project, Task, or typed
  name        TEXT NOT NULL,
  parent_id   TEXT,                 -- NULL at the top of a section
  reach       TEXT,                 -- 'mine' (yours), 'global' (everyone's
                                    -- communities) or 'news' (everyone's News)
  viewing     TEXT,                 -- 'open' (anybody) or 'invite' (named people only)
  contribute  TEXT,                 -- same two values, for putting things in
  created_by  TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  deleted_at  TEXT,                 -- taken down by the operator; see edits
  edited_at   TEXT
);

-- Who may see or contribute to a community that is not open to everybody.
--
-- A row names ONE community, not a whole tree. Access reaches downward: being
-- named on Metastasis covers Metastasis and everything inside it, and nothing
-- above it. So the coarsest community you are named on is your ceiling. The
-- person who founded a community is always allowed and is never listed here.
CREATE TABLE IF NOT EXISTS members (
  group_id    TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  role        TEXT NOT NULL,        -- 'view' or 'contribute' (contribute implies view)
  added_at    TEXT NOT NULL,
  PRIMARY KEY (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS members_user_idx ON members (user_id);

-- Money offered for finishing a task. Nothing is transferred: this records
-- that somebody said they would pay, and who.
CREATE TABLE IF NOT EXISTS rewards (
  id          TEXT PRIMARY KEY,
  group_id    TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  author      TEXT NOT NULL,
  amount      REAL NOT NULL,
  note        TEXT,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS rewards_group_idx ON rewards (group_id);

-- Communities and channels a person has taken off their own list. Nobody
-- else's view changes; this is a curtain, not a removal.
CREATE TABLE IF NOT EXISTS feed_hidden (
  user_id     TEXT NOT NULL,
  group_id    TEXT NOT NULL,
  hidden_at   TEXT NOT NULL,
  PRIMARY KEY (user_id, group_id)
);

-- Every edit and take-down the operator makes, and what the thing said
-- before. Nothing in this program destroys what was written: a take-down
-- sets a marker that reading filters out, and an edit copies the old value
-- here first. This table is the reason both remain honest.
CREATE TABLE IF NOT EXISTS edits (
  id          TEXT PRIMARY KEY,
  target      TEXT NOT NULL,        -- 'entry' or 'grouping'
  target_id   TEXT NOT NULL,
  action      TEXT NOT NULL,        -- 'edit' or 'takedown'
  field       TEXT,                 -- which field, for an edit
  was         TEXT,                 -- what it said before
  now         TEXT,                 -- what it says after
  by_user     TEXT NOT NULL,
  by_name     TEXT NOT NULL,
  at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS edits_target_idx ON edits (target, target_id);

-- What a record produced. A record can carry as many of these as it likes,
-- in any mix: a link, an uploaded file, a note, or all three at once.
CREATE TABLE IF NOT EXISTS attachments (
  id          TEXT PRIMARY KEY,
  entry_id    TEXT NOT NULL,
  position    INTEGER NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('link', 'file', 'text')),
  url         TEXT,
  body        TEXT,
  file_name   TEXT,
  file_mime   TEXT,
  file_size   INTEGER,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS attachments_entry_idx ON attachments (entry_id, position);

-- Where a shared record sits. One row per place, so a single thought can be
-- shared to several communities at once. A record is placed at the most
-- specific level it belongs to: a community, or a project/task inside one.
CREATE TABLE IF NOT EXISTS placements (
  entry_id    TEXT NOT NULL,
  group_id    TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  PRIMARY KEY (entry_id, group_id)
);

CREATE INDEX IF NOT EXISTS placements_group_idx ON placements (group_id);

CREATE TABLE IF NOT EXISTS entries (
  id          TEXT PRIMARY KEY,
  created_at  TEXT NOT NULL,          -- stamped by the server; never sent by the browser
  user_id     TEXT NOT NULL,
  author      TEXT NOT NULL,          -- copied in, so the line never changes
  fn          TEXT NOT NULL,          -- the operation performed
  title       TEXT,                   -- optional
  kind        TEXT NOT NULL CHECK (kind IN ('link', 'file', 'text')),
  url         TEXT,
  body        TEXT,
  file_name   TEXT,
  file_mime   TEXT,
  file_size   INTEGER,
  shared      INTEGER NOT NULL DEFAULT 0,   -- 0 = Personal, 1 = Collective
  shared_at   TEXT,
  reply_to    TEXT,                         -- set when this answers another record
  folder_id   TEXT,                         -- optional, Personal
  group_id    TEXT,                         -- kept from an earlier version; see placements
  removed_at  TEXT,                         -- removed from Personal; the Collective keeps it
  hidden_at   TEXT,                         -- taken down by the operator; see edits
  edited_at   TEXT                          -- last operator edit; see edits
);

CREATE INDEX IF NOT EXISTS entries_user_idx   ON entries (user_id, created_at);
CREATE INDEX IF NOT EXISTS entries_shared_idx ON entries (shared, created_at);
CREATE INDEX IF NOT EXISTS entries_reply_idx  ON entries (reply_to);
CREATE INDEX IF NOT EXISTS folders_user_idx   ON folders (user_id, name);
"""

# Columns added after the first version shipped. Existing data folders are
# upgraded in place on startup so nobody loses records to a new feature.
LATER_COLUMNS = {
    "users": [("pass_hash", "TEXT"), ("is_operator", "INTEGER")],
    "entries": [("folder_id", "TEXT"), ("group_id", "TEXT"), ("removed_at", "TEXT"),
                ("hidden_at", "TEXT"), ("edited_at", "TEXT")],
    "groupings": [("parent_id", "TEXT"), ("reach", "TEXT"), ("contribute", "TEXT"),
                  ("viewing", "TEXT"), ("deleted_at", "TEXT"), ("edited_at", "TEXT")],
    "members": [("role", "TEXT")],
}


# ===========================================================================
# THE PAGE — html, styling and behaviour, served from memory.
# ===========================================================================

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cognaut</title>
<link rel="icon" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' fill='white'/><rect x='5' y='7' width='22' height='2.5'/><rect x='5' y='14.75' width='22' height='2.5'/><rect x='5' y='22.5' width='14' height='2.5'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;1,400;1,500&family=Mrs+Saint+Delafield&family=Newsreader:ital,opsz,wght@0,6..72,200..700;1,6..72,200..500&display=swap">

<style>
  :root {
    color-scheme: light dark;
    --paper: #ffffff;
    --ink: #000000;
    --ink-2: rgba(0, 0, 0, 0.62);
    --ink-3: rgba(0, 0, 0, 0.40);
    --rule: rgba(0, 0, 0, 0.14);
    --rule-strong: rgba(0, 0, 0, 0.34);
    --hover: rgba(0, 0, 0, 0.035);
    --inv-bg: #000000;
    --inv-fg: #ffffff;
    --veil: rgba(0, 0, 0, 0.55);
    --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    --serif: "Newsreader", "Iowan Old Style", Georgia, serif;
    --hand: "Mrs Saint Delafield", "Snell Roundhand", "Apple Chancery", cursive;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --paper: #000000;
      --ink: #ffffff;
      --ink-2: rgba(255, 255, 255, 0.66);
      --ink-3: rgba(255, 255, 255, 0.44);
      --rule: rgba(255, 255, 255, 0.18);
      --rule-strong: rgba(255, 255, 255, 0.40);
      --hover: rgba(255, 255, 255, 0.05);
      --inv-bg: #ffffff;
      --inv-fg: #000000;
      --veil: rgba(0, 0, 0, 0.72);
    }
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; }

  body {
    background: var(--paper);
    color: var(--ink);
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  img { max-width: 100%; }
  [hidden] { display: none !important; }

  .page { max-width: 980px; margin: 0 auto; padding: 40px 28px 120px; }

  /* ------------------------------------------------------------ home -- */

  .hero {
    min-height: 78vh;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 18px; text-align: center;
  }

  .brand {
    font-family: var(--serif); font-weight: 700;
    font-size: clamp(40px, 8vw, 76px); line-height: 1.0;
    letter-spacing: -0.025em; margin: 0; text-wrap: balance;
  }

  .ul { text-decoration: underline; text-underline-offset: 0.14em; }

  .thesis {
    font-family: var(--serif); font-style: italic; font-weight: 300;
    font-size: clamp(18px, 2.8vw, 24px); line-height: 1.35;
    color: var(--ink-2); margin: 0; max-width: 30ch;
  }

  /* The signer's own hand, set beside the name of their space. */
  .sig-inline {
    font-family: var(--hand); font-weight: 400;
    font-size: 0.78em; color: var(--ink-2); white-space: nowrap;
  }

  .gates { display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
           margin-top: 26px; width: min(100%, 580px); }
  @media (max-width: 540px) { .gates { grid-template-columns: 1fr; } }

  .gate-btn {
    font: inherit; font-size: 11.5px; font-weight: 500;
    letter-spacing: 0.16em; text-transform: uppercase;
    background: none; color: var(--ink); border: 1px solid var(--ink);
    padding: 19px 24px; cursor: pointer;
  }

  .gate-btn:hover { background: var(--inv-bg); color: var(--inv-fg); }
  .gate-btn:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }

  .who {
    font-size: 11px; letter-spacing: 0.06em; color: var(--ink-3);
    margin: 22px 0 0; display: flex; gap: 12px;
    align-items: baseline; justify-content: center; flex-wrap: wrap;
  }

  /* ---------------------------------------------------------- ledger -- */

  .topbar {
    display: flex; justify-content: space-between; align-items: baseline;
    gap: 16px; flex-wrap: wrap; padding-bottom: 16px;
    border-bottom: 1px solid var(--ink);
  }

  .back {
    font: inherit; font-family: var(--serif); font-weight: 700; font-size: 19px;
    letter-spacing: -0.01em; background: none; border: 0;
    color: var(--ink); padding: 0; cursor: pointer;
  }

  .back:hover { text-decoration: underline; text-underline-offset: 4px; }
  .back:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
  .topbar .who { margin: 0; }

  .view-title {
    font-family: var(--serif); font-weight: 400;
    font-size: clamp(26px, 4vw, 38px); letter-spacing: -0.015em; margin: 34px 0 6px;
  }

  .view-note { margin: 0 0 26px; font-size: 12px; color: var(--ink-3); max-width: 78ch; }

  .back .arrow { display: inline-block; font-family: var(--mono); font-weight: 400;
                 font-size: 16px; vertical-align: 1px; margin-right: 2px; }

  .chips { display: flex; flex-wrap: wrap; align-items: stretch;
           border-top: 1px solid var(--rule); }

  .chip {
    font: inherit; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase;
    background: none; border: 0; border-right: 1px solid var(--rule);
    color: var(--ink-2); padding: 11px 14px; cursor: pointer; white-space: nowrap;
  }

  .chip:hover { background: var(--hover); }
  .chip[aria-pressed="true"] { background: var(--inv-bg); color: var(--inv-fg); }
  .chip:focus-visible { outline: 2px solid var(--ink); outline-offset: -2px; }
  .chip .k { opacity: 0.55; margin-right: 6px; }
  .chip.add { color: var(--ink); }

  .opt { text-transform: none; letter-spacing: 0; opacity: 0.55; }

  .crumbs { margin: 26px 0 0; font-size: 11px; letter-spacing: 0.08em;
            text-transform: uppercase; color: var(--ink-3);
            display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }

  .crumbs button {
    font: inherit; background: none; border: 0; color: var(--ink-2); padding: 0;
    cursor: pointer; text-decoration: underline; text-underline-offset: 3px;
  }

  .crumbs .sep { opacity: 0.5; }

  .groups { margin: 8px 0 30px; border-top: 1px solid var(--rule); }

  .group-row {
    display: flex; width: 100%; align-items: baseline; gap: 16px;
    font: inherit; text-align: left; background: none; border: 0;
    border-bottom: 1px solid var(--rule); color: var(--ink);
    padding: 15px 4px 15px 0; cursor: pointer;
  }

  .group-row:hover { background: var(--hover); }
  .group-row:focus-visible { outline: 2px solid var(--ink); outline-offset: -2px; }

  /* A row you can also take off your own list: the line carries the rule so
     the two controls sit on one line under one border. */
  .group-line { display: flex; align-items: center; gap: 14px;
                border-bottom: 1px solid var(--rule); }
  .group-line .group-row { border-bottom: 0; flex: 1 1 auto; }
  .group-line .drop-btn { flex: 0 0 auto; white-space: nowrap; }

  /* Searching a whole section. Styled like the record filter, not like a
     form field, because it narrows a list rather than collecting an answer. */
  .seek { border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
  .seek input {
    font: inherit; font-size: 12px; width: 100%;
    background: none; border: 0; border-radius: 0; box-shadow: none;
    color: var(--ink); padding: 12px 2px; -webkit-appearance: none; appearance: none;
  }
  .seek input::placeholder { color: var(--ink-3); letter-spacing: 0.06em; }
  .seek input:focus { outline: none; box-shadow: none; background: var(--hover); }
  .seek input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
  .path { font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
          color: var(--ink-3); }

  /* Whether you may only look here, or may also put things in. */
  .state { font-family: var(--mono); font-size: 11px; letter-spacing: 0.1em;
           text-transform: uppercase; color: var(--ink-3); vertical-align: 4px;
           margin-left: 12px; }
  .group-row.stated .n { flex: 0 1 auto; }
  .group-row.stated .state { flex: 1 1 auto; margin-left: 0; }

  .group-row .k { flex: 0 0 auto; font-size: 9.5px; letter-spacing: 0.16em;
                  color: var(--ink-3); min-width: 8em; }
  .group-row .n { flex: 1 1 auto; font-family: var(--serif); font-size: 21px;
                  font-weight: 400; letter-spacing: -0.01em; }
  .group-row .c { flex: 0 0 auto; font-size: 10.5px; letter-spacing: 0.1em;
                  color: var(--ink-3); font-variant-numeric: tabular-nums; }
  .group-row .go { flex: 0 0 auto; color: var(--ink-3); font-size: 15px; }

  .group-add { padding: 16px 0 0; }
  .groups .empty { padding: 20px 0 4px; }

  .checks { display: grid; gap: 10px; max-height: 320px; overflow: auto; }
  .checks label { display: flex; gap: 10px; align-items: baseline;
                  font-size: 13px; letter-spacing: 0; text-transform: none;
                  color: var(--ink); cursor: pointer; }
  .checks input { width: auto; margin: 0; -webkit-appearance: auto; appearance: auto; }

  .browse-row {
    display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
    border-bottom: 1px solid var(--rule); padding: 11px 0;
  }

  .browse-row .n { font-family: var(--serif); font-size: 18px; }

  .group-add { display: flex; gap: 22px; flex-wrap: wrap; }

  /* Each half of My Network sits in its own box, which grows with what is
     in it. A light rule, deliberately: this is a container, not a panel. */
  .box { border: 1px solid var(--rule); padding: 0 20px 16px; margin: 26px 0 0; }
  .box:first-child { margin-top: 12px; }
  .box .group-row:last-of-type,
  .box .group-line:last-of-type { border-bottom: 0; }

  /* The boxes draw their own edges, so the screen wants no rules of its own. */
  .groups.boxed { border-top: 0; }
  .colophon.bare { border-top: 0; padding-top: 0; }

  /* The heading over each half. Smaller than the name of the screen, but a
     heading all the same, so it is set in the ink of one. */
  .half { font-size: 12.5px; letter-spacing: 0.12em; text-transform: uppercase;
          font-style: italic; font-weight: 500;
          color: var(--ink); padding: 17px 0 3px; }

  .danger { color: var(--ink); }

  .help-btn {
    position: fixed; bottom: 10px; right: 14px; z-index: 5;
    font: inherit; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase;
    background: var(--paper); border: 1px solid var(--rule-strong);
    color: var(--ink-2); padding: 7px 12px; cursor: pointer;
  }

  .help-btn:hover { background: var(--inv-bg); color: var(--inv-fg); border-color: var(--ink); }
  .help-btn:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

  .sheet p.para { margin: 0; font-size: 13px; line-height: 1.85; color: var(--ink); }

  /* -- the piece builder: a record carries as many of these as it likes -- */

  .adders { display: flex; gap: 10px; flex-wrap: wrap; }

  .adder {
    font: inherit; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
    background: none; border: 1px solid var(--rule-strong); color: var(--ink);
    padding: 9px 16px; cursor: pointer;
  }

  .adder:hover { background: var(--inv-bg); color: var(--inv-fg); border-color: var(--ink); }
  .adder:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

  .pieces { display: grid; gap: 12px; }

  .piece {
    border-left: 2px solid var(--ink); padding: 2px 0 2px 14px;
    display: grid; gap: 6px;
  }

  .piece-head {
    display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
    font-size: 9.5px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-2);
  }

  .piece-drop {
    font: inherit; font-size: 9.5px; letter-spacing: 0.12em; text-transform: uppercase;
    background: none; border: 0; color: var(--ink-2); cursor: pointer; padding: 0;
    text-decoration: underline; text-underline-offset: 3px;
  }

  .dests { display: grid; gap: 14px; }

  .dest { display: grid; gap: 8px; }

  .dest > label {
    display: flex; gap: 10px; align-items: baseline; cursor: pointer;
    font-size: 13px; letter-spacing: 0; text-transform: none; color: var(--ink);
  }

  .dest input[type="radio"] { width: auto; margin: 0; -webkit-appearance: auto; appearance: auto; }
  .dest .sub { padding-left: 24px; display: grid; gap: 8px; }
  .dest .warn { font-size: 11px; color: var(--ink-2); line-height: 1.6; }

  .bar { display: flex; align-items: stretch; border-top: 1px solid var(--rule);
         border-bottom: 1px solid var(--rule); flex-wrap: wrap; }

  .btn {
    font: inherit; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase;
    font-size: 11px; background: none; border: 0; color: var(--ink);
    padding: 13px 18px 13px 0; cursor: pointer;
  }

  .btn:hover { text-decoration: underline; text-underline-offset: 3px; }
  .btn:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

  .filter {
    font: inherit; font-size: 12px; flex: 1 1 160px; min-width: 120px;
    background: none; border: 0; border-left: 1px solid var(--rule);
    color: var(--ink); padding: 12px 14px;
  }

  .filter::placeholder { color: var(--ink-3); letter-spacing: 0.06em; }
  .filter:focus { outline: none; background: var(--hover); }

  .count {
    display: flex; align-items: center; padding: 0 0 0 14px;
    border-left: 1px solid var(--rule); font-size: 11px; letter-spacing: 0.08em;
    color: var(--ink-3); font-variant-numeric: tabular-nums; white-space: nowrap;
  }

  .ledger { margin-top: 4px; }
  .rec { border-bottom: 1px solid var(--rule); }
  .rec.reply { border-left: 1px solid var(--rule); }   /* margin-left set per depth */

  .line {
    font: inherit; width: 100%; text-align: left; background: none; border: 0;
    color: var(--ink); cursor: pointer; display: flex; gap: 16px;
    padding: 11px 4px 11px 0; align-items: baseline;
  }

  .rec.reply .line { padding-left: 14px; }
  .line:hover { background: var(--hover); }
  .line:focus-visible { outline: 2px solid var(--ink); outline-offset: -2px; }

  .rec-text { flex: 1 1 auto; min-width: 0; font-size: 13px; line-height: 1.7; }
  .rec-text .stamp { font-variant-numeric: tabular-nums; color: var(--ink-2); }
  .rec-text .who-name { font-weight: 500; }
  .rec-text .fn { text-transform: uppercase; letter-spacing: 0.12em;
                  font-weight: 600; font-size: 11.5px; }

  .tags { flex: 0 0 auto; display: flex; gap: 6px; align-self: center; }

  .tag { font-size: 9.5px; letter-spacing: 0.14em; color: var(--ink-3);
         border: 1px solid var(--rule); padding: 2px 7px; white-space: nowrap; }

  .tag.on { color: var(--inv-fg); background: var(--inv-bg); border-color: var(--ink); }

  .body { padding: 4px 4px 26px 14px; display: grid; gap: 14px; }

  .body a { color: var(--ink); word-break: break-all; }
  .payload { border-left: 2px solid var(--ink); padding: 2px 0 2px 16px;
             display: grid; gap: 10px; }

  pre { margin: 0; font-family: var(--mono); font-size: 12px; line-height: 1.7;
        white-space: pre-wrap; word-break: break-word; max-height: 460px; overflow: auto; }

  pre.code { white-space: pre; overflow-x: auto; }
  .body img { border: 1px solid var(--rule); display: block; }
  .body iframe { width: 100%; height: 560px; border: 1px solid var(--rule);
                 background: var(--paper); }

  .meta { font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase;
          color: var(--ink-3); display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }

  .actions { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; }
  .empty { padding: 46px 0; color: var(--ink-3); font-size: 12.5px;
           line-height: 1.8; max-width: 58ch; }

  .colophon { margin-top: 60px; padding-top: 18px; border-top: 1px solid var(--rule);
              font-size: 11px; line-height: 1.8; color: var(--ink-3); }

  /* ---------------------------------------------------------- shared -- */

  .link-btn {
    font: inherit; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
    background: none; border: 0; color: var(--ink); cursor: pointer; padding: 0;
    text-decoration: underline; text-underline-offset: 3px;
  }

  .link-btn:disabled { color: var(--ink-3); cursor: default; text-decoration: none; }
  .link-btn.quiet { color: var(--ink-2); }
  .msg { font-size: 11.5px; color: var(--ink-2); line-height: 1.6; }

  /* --------------------------------------------------------- dialogs -- */

  dialog {
    border: 1px solid var(--ink); background: var(--paper); color: var(--ink);
    padding: 0; width: min(620px, calc(100vw - 32px));
    max-height: calc(100vh - 48px); box-shadow: none;
  }

  dialog::backdrop { background: var(--veil); }
  .sheet { padding: 26px; display: grid; gap: 20px; }

  .sheet-head { font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase;
                color: var(--ink-2); display: flex; justify-content: space-between; gap: 12px; }

  .sheet h2 { font-family: var(--serif); font-weight: 700; font-size: 27px;
              margin: 0; letter-spacing: -0.015em; line-height: 1.15; }

  .sheet p.lead { margin: 0; font-size: 12.5px; color: var(--ink-2); line-height: 1.7; }

  .answering { border-left: 2px solid var(--ink); padding-left: 14px;
               font-size: 12px; color: var(--ink-2); line-height: 1.6; }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 18px; }
  .field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .field.wide { grid-column: 1 / -1; }

  label, .lbl { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-2); }

  input[type="text"], input[type="url"], input[type="password"], select, textarea {
    font: inherit; font-size: 13px; color: var(--ink); background: var(--paper);
    border: 1px solid var(--rule-strong); padding: 9px 10px; width: 100%;
    border-radius: 0; -webkit-appearance: none; appearance: none;
  }

  select {
    background-image: linear-gradient(45deg, transparent 50%, var(--ink) 50%),
                      linear-gradient(135deg, var(--ink) 50%, transparent 50%);
    background-position: right 14px center, right 9px center;
    background-size: 5px 5px, 5px 5px; background-repeat: no-repeat; padding-right: 30px;
  }

  textarea { min-height: 108px; resize: vertical; line-height: 1.6; }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }

  .segments { display: flex; border: 1px solid var(--rule-strong); width: fit-content; max-width: 100%; }

  .segments button {
    font: inherit; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
    background: none; border: 0; border-right: 1px solid var(--rule-strong);
    color: var(--ink-2); padding: 9px 16px; cursor: pointer;
  }

  .segments button:last-child { border-right: 0; }
  .segments button[aria-pressed="true"] { background: var(--inv-bg); color: var(--inv-fg); }
  .segments button:focus-visible { outline: 2px solid var(--ink); outline-offset: -2px; }

  .hint { font-size: 11px; color: var(--ink-3); line-height: 1.6; }

  input[type="file"] { font: inherit; font-size: 12px; color: var(--ink-2); }
  input[type="file"]::file-selector-button {
    font: inherit; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase;
    background: var(--inv-bg); color: var(--inv-fg); border: 0; padding: 8px 14px;
    margin-right: 12px; cursor: pointer;
  }

  .sheet-foot { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }

  .submit {
    font: inherit; font-size: 11px; font-weight: 500; letter-spacing: 0.14em;
    text-transform: uppercase; background: var(--inv-bg); color: var(--inv-fg);
    border: 1px solid var(--ink); padding: 12px 26px; cursor: pointer;
  }

  .submit:disabled { opacity: 0.4; cursor: default; }
  .submit:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

  @media (prefers-reduced-motion: no-preference) { .rec { transition: background 120ms ease; } }
</style>
</head>
<body>

<div class="page">

  <section id="home">
    <div class="hero">
      <h1 class="brand">Cognaut</h1>
      <p class="thesis">The cognitive revolution is <span class="ul">here</span>.</p>
      <div class="gates">
        <button class="gate-btn" type="button" data-go="collective">Collective Intelligence</button>
        <button class="gate-btn" type="button" data-go="personal">My Intelligence</button>
      </div>
      <p class="who" id="whoHome"></p>
    </div>
  </section>

  <section id="view" hidden>
    <header class="topbar">
      <button class="back" type="button" id="backBtn">
        <span class="arrow" aria-hidden="true">&#8592;</span> Cognaut
      </button>
      <span class="who" id="whoView"></span>
    </header>

    <p class="crumbs" id="crumbs" hidden></p>
    <h2 class="view-title" id="viewTitle"></h2>
    <p class="view-note" id="viewNote"></p>

    <div class="chips" id="chips"></div>
    <div class="groups" id="groups"></div>

    <div class="bar" id="bar">
      <button class="btn" type="button" id="addBtn">+ Add record</button>
      <input class="filter" id="filter" type="text" placeholder="Filter" aria-label="Filter records">
      <span class="count" id="count"></span>
    </div>

    <div class="ledger" id="ledger"></div>

    <p class="colophon" id="colophon"></p>
  </section>

</div>

<button class="help-btn" type="button" id="helpBtn">How does this work?</button>

<dialog id="gate">
  <form class="sheet" id="gateForm" method="dialog">
    <h2>Who is entering?</h2>
    <p class="lead">Records are signed with your name. Sign in to write, or continue without a name to read. A name nobody has yet becomes yours, with the password you give it.</p>

    <div class="field" id="pickField" hidden>
      <label for="g-pick">Name</label>
      <select id="g-pick"></select>
    </div>

    <div class="field" id="nameField">
      <label for="g-name" id="nameLabel">Name</label>
      <input type="text" id="g-name" autocomplete="username" placeholder="Your name">
    </div>

    <div class="field">
      <label for="g-pass">Password</label>
      <input type="password" id="g-pass" autocomplete="current-password">
      <span class="hint">New here? Choose one of at least 8 characters. Nobody, not even the operator, can see it.</span>
    </div>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="gateSubmit">Enter</button>
      <button type="button" class="link-btn quiet" id="gateSkip">Just view</button>
      <span class="msg" id="gateMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="folderDialog">
  <form class="sheet" id="folderForm" method="dialog">
    <h2>Create file</h2>
    <div class="field">
      <label for="fo-name">Name</label>
      <input type="text" id="fo-name" placeholder="Thesis reading">
    </div>
    <div class="sheet-foot">
      <button type="submit" class="submit" id="folderSubmit">Create file</button>
      <button type="button" class="link-btn quiet" id="folderCancel">Cancel</button>
      <span class="msg" id="folderMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="groupDialog">
  <form class="sheet" id="groupForm" method="dialog">
    <h2 id="groupHeading">Create community</h2>
    <div class="grid">
      <div class="field" id="grKindField" hidden>
        <label for="gr-kind">What is it</label>
        <select id="gr-kind">
          <option>Project</option>
          <option>Task</option>
          <option value="__own__">+ Add your own</option>
        </select>
      </div>
      <div class="field" id="grKindOther" hidden>
        <label for="gr-kind-other">Call it</label>
        <input type="text" id="gr-kind-other" placeholder="Reading group">
      </div>
      <div class="field wide">
        <label for="gr-name">Name</label>
        <input type="text" id="gr-name" placeholder="A Theory of Biology">
      </div>
    </div>
    <div class="sheet-foot">
      <button type="submit" class="submit" id="groupSubmit">Create</button>
      <button type="button" class="link-btn quiet" id="groupCancel">Cancel</button>
      <span class="msg" id="groupMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="browseDialog">
  <div class="sheet">
    <h2 id="browseHeading">Browse communities</h2>
    <p class="lead" id="browseLead"></p>
    <div id="browseList"></div>
    <div class="sheet-foot">
      <button type="button" class="submit" id="browseClose">Done</button>
      <span class="msg" id="browseMsg"></span>
    </div>
  </div>
</dialog>

<dialog id="accessDialog">
  <form class="sheet" id="accessForm" method="dialog">
    <h2 id="accessHeading">Who can contribute</h2>
    <p class="lead" id="accessLead"></p>

    <div class="dests">
      <div class="dest">
        <label>
          <input type="radio" name="contribute" value="open">
          <span>Everybody</span>
        </label>
      </div>
      <div class="dest">
        <label>
          <input type="radio" name="contribute" value="invite" checked>
          <span>Only these people</span>
        </label>
        <div class="sub" id="accessSub">
          <div id="accessList"></div>
        </div>
      </div>
    </div>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="accessSubmit">Save</button>
      <button type="button" class="link-btn quiet" id="accessCancel">Cancel</button>
      <span class="msg" id="accessMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="rewardDialog">
  <form class="sheet" id="rewardForm" method="dialog">
    <h2 id="rewardHeading">Reward</h2>
    <p class="lead">Offer money for finishing this task. Nothing is taken and
      nothing is paid here &mdash; this records that you said you would.</p>

    <div id="rewardSoFar"></div>

    <label class="field">
      <span>Amount</span>
      <input id="rw-amount" type="number" min="0.01" step="0.01" placeholder="250">
    </label>

    <label class="field">
      <span>Note (optional)</span>
      <input id="rw-note" type="text" maxlength="300" placeholder="On a working demo">
    </label>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="rewardSubmit">Offer</button>
      <button type="button" class="link-btn quiet" id="rewardCancel">Close</button>
      <span class="msg" id="rewardMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="shareDialog">
  <form class="sheet" id="shareForm" method="dialog">
    <h2>Where does this go?</h2>

    <div class="dests">
      <div class="dest">
        <label>
          <input type="radio" name="dest" value="keep" checked>
          <span>Keep it to myself</span>
        </label>
      </div>

      <div class="dest">
        <label>
          <input type="radio" name="dest" value="network">
          <span>My network</span>
        </label>
        <div class="sub" id="networkSub" hidden>
          <div id="networkList"></div>
          <button type="button" class="link-btn quiet" id="mineNew">+ Create community</button>
        </div>
      </div>

      <div class="dest">
        <label>
          <input type="radio" name="dest" value="global">
          <span>Global communities</span>
        </label>
        <div class="sub" id="globalSub" hidden>
          <div id="globalList"></div>
          <span class="warn">Once a record is in a global community it stays there. This cannot be changed.</span>
        </div>
      </div>

      <div class="dest">
        <label>
          <input type="radio" name="dest" value="news">
          <span>News</span>
        </label>
        <div class="sub" id="newsSub" hidden>
          <div id="newsList"></div>
          <span class="warn">Once a record is in News it stays there. This cannot be changed.</span>
        </div>
      </div>
    </div>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="shareSubmit">Done</button>
      <button type="button" class="link-btn quiet" id="shareCancel">Cancel</button>
      <span class="msg" id="shareMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="helpDialog">
  <div class="sheet">
    <h2>How does this work?</h2>
    <p class="para">You write records in <strong>My Intelligence</strong>, where they are entirely private: you make them, delete them, and share them at your full discretion. There are three different types of communities you can share a record to. <strong>My Network</strong> are yours — communities or news that you create, others have created, or that you belong to. <strong>Global Communities</strong> are larger-scale projects aimed at advancing science and technology — these records can never be removed by an individual. <strong>News</strong> are aimed towards information dispersion — these records can also never be removed by an individual.</p>
    <div class="sheet-foot">
      <button type="button" class="submit" id="helpClose">Close</button>
    </div>
  </div>
</dialog>

<dialog id="fixDialog">
  <form class="sheet" id="fixForm" method="dialog">
    <h2>Correct this record</h2>
    <p class="lead">What it said before is kept, whatever you change it to.</p>

    <div class="grid">
      <div class="field">
        <label for="fx-fn">Function</label>
        <input type="text" id="fx-fn" maxlength="60">
      </div>
      <div class="field wide">
        <label for="fx-title">Title <span class="opt">optional</span></label>
        <input type="text" id="fx-title" maxlength="300">
      </div>
    </div>

    <div id="fixPieces"></div>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="fixSubmit">Save</button>
      <button type="button" class="link-btn quiet" id="fixCancel">Cancel</button>
      <span class="msg" id="fixMsg"></span>
    </div>
  </form>
</dialog>

<dialog id="recordDialog">
  <form class="sheet" id="recordForm" method="dialog">
    <div class="sheet-head">
      <span id="recordKicker">New record</span>
      <span id="recordStamp"></span>
    </div>

    <div class="answering" id="answering" hidden></div>

    <div class="grid">
      <div class="field">
        <label for="f-fn">Function</label>
        <select id="f-fn" required></select>
      </div>
      <div class="field" id="fnOtherField" hidden>
        <label for="f-fn-other">Name the function</label>
        <input type="text" id="f-fn-other" placeholder="Reframe">
      </div>
      <div class="field wide">
        <label for="f-title">Title <span class="opt">optional</span></label>
        <input type="text" id="f-title" placeholder="A Theory of Biology">
      </div>
      <div class="field wide" id="placeField" hidden>
        <label for="f-place" id="placeLabel">File</label>
        <select id="f-place"></select>
      </div>
    </div>

    <div class="field">
      <span class="lbl">What it produced</span>
      <div class="adders">
        <button class="adder" type="button" data-add="link">+ Link</button>
        <button class="adder" type="button" data-add="file">+ File</button>
        <button class="adder" type="button" data-add="text">+ Note</button>
      </div>
      <span class="hint">Add as many as you like, in any mix.</span>
    </div>

    <div class="pieces" id="pieces"></div>

    <div class="sheet-foot">
      <button type="submit" class="submit" id="recordSubmit">Add to ledger</button>
      <button type="button" class="link-btn quiet" id="recordCancel">Cancel</button>
      <span class="msg" id="recordMsg"></span>
    </div>
  </form>
</dialog>

<script>
(function () {
  "use strict";

  var FUNCTIONS = ["Thought", "Critique", "Expand", "Research", "Connect",
                   "Formalize", "Verify", "Synthesize", "Predict",
                   "News", "Paper", "Opinion", "Other..."];

  var MAX_FILE = 25 * 1024 * 1024;
  var NEW_USER = "__new__";

  // A global community is permanent and everybody's, so for now only one
  // person may start one. The server enforces this; this only hides the button.
  // The server writes the operator's name in here each time it sends the page.
  var GLOBAL_FOUNDER = __GLOBAL_FOUNDER__;

  function isGlobalFounder() {
    return !!user && String(user.name).trim().toLowerCase() ===
                     GLOBAL_FOUNDER.trim().toLowerCase();
  }

  var TEXT_EXT = ("txt md markdown json csv tsv js jsx ts tsx py rb go rs java c h cpp hpp " +
    "cs php html htm css scss sass yml yaml toml ini sh bash zsh sql r m swift kt xml log tex " +
    "lisp clj hs ml pl lua vim cfg conf env gitignore makefile dockerfile").split(" ");
  var IMG_EXT = "png jpg jpeg gif webp svg avif bmp".split(" ");

  var user = null;
  var scope = "home";
  var entries = [];
  var knownUsers = [];
  var folders = [];      // organizational files, Personal
  var groupings = [];    // whatever sits at the current level of the Collective
  var CONSENT = "Communities and channels can only be removed by the consent "
              + "of all parties that have ever contributed.";

  // The Collective has three doors. My Network is one screen holding two
  // lists, one above the other; the other two are lists in their own right.
  // A section knows its name, what sits above it, and its line at the bottom.
  var SECTIONS = {
    "network": { label: "My Network", parent: "", foot: CONSENT },
    "global":  { label: "Global Communities", parent: "",
                 foot: "Nothing here can ever be removed." },
    "news":    { label: "News", parent: "",
                 foot: "Nothing here can ever be removed." }
  };

  // The only screen of doors is the first one.
  var DOORS = { "": ["network", "global", "news"] };

  // The two halves of My Network, stacked in this order.
  var HALVES = [
    { kind: "Community", label: "My Communities",
      make: "+ Create community", browse: "Browse communities",
      drop: "Remove community", how: "browse" },
    { kind: "Channel", label: "My News",
      make: "+ Create channel", browse: "Browse news",
      drop: "Remove news", how: "browsenews" }
  ];

  // The two kinds that hold other things. Everything else holds only records.
  var HOLDS = { Community: true, Channel: true };

  function section(key) { return SECTIONS[key] || null; }
  function isNewsRealm(key) { return key === "news"; }

  var realm = "";        // "" = the three doors; otherwise a key of SECTIONS
  var trail = [];        // [] = the community list, [community], [community, project]
  var placeFilter = "";  // Personal only: "" = everything, otherwise a file id
  var kind = "link";
  var replyTo = null;
  var writingInto = null;   // the community, channel, project or task a new
                            // record is being written straight into
  var open = {};
  var loaded = false;
  var timer = null;
  var pendingGo = null;

  var $ = function (id) { return document.getElementById(id); };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // Every call goes through here so a stopped server reads as a sentence
  // rather than the browser's own "Failed to fetch".
  function api(url, opts) {
    return fetch(url, opts).then(
      function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) throw new Error(data.error || "Something went wrong.");
          return data;
        });
      },
      function () {
        throw new Error("The site is not responding. Check that the black Start window is still open, then try again.");
      }
    );
  }

  /* -------------------------------------------------------- formatting -- */

  function stamp(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return { time: "", date: "" };
    var h = d.getHours();
    var ampm = h >= 12 ? "PM" : "AM";
    h = h % 12; if (h === 0) h = 12;
    return {
      time: h + ":" + String(d.getMinutes()).padStart(2, "0") + ampm,
      date: (d.getMonth() + 1) + "/" + d.getDate() + "/" + String(d.getFullYear()).slice(-2)
    };
  }

  function bytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(0) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function ext(name) {
    var p = String(name || "").toLowerCase().split(".");
    return p.length > 1 ? p.pop() : "";
  }

  /* ---------------------------------------------------------- identity -- */

  // Who you are is the server's to say: it reads the sign-in cookie, which
  // this script cannot see. The page only remembers the answer for display.
  function signedIn(data) {
    user = data && data.id ? { id: data.id, name: data.name } : null;
    if (data && typeof data.operator === "string") GLOBAL_FOUNDER = data.operator;
    paintIdentity();
  }

  function signOut() {
    api("/api/session/end", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    })
      .catch(function () {})
      .then(function () {
        user = null;
        paintIdentity();
        if (scope === "personal") go("home");
        else if (scope !== "home") { loadPlaces(); refresh(); }
        openGate();
      });
  }

  // The operator sets a new password for someone who has forgotten theirs,
  // and tells them it. Two plain questions, because this is rare.
  function resetSomeone() {
    var name = window.prompt("Whose password? Type their name exactly.");
    if (name === null || !name.trim()) return;
    var pass = window.prompt("New password for " + name.trim() +
                             " (at least 8 characters). Tell them it yourself.");
    if (pass === null) return;
    api("/api/users/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), password: pass })
    })
      .then(function () { window.alert("Done. " + name.trim() + " can sign in with the new password."); })
      .catch(function (err) { window.alert(err.message); });
  }

  function paintIdentity() {
    [$("whoHome"), $("whoView")].forEach(function (host) {
      host.textContent = "";
      if (user) {
        host.appendChild(el("span", null, "You are " + user.name + "."));
        var out = el("button", "link-btn", "Sign out");
        out.type = "button";
        out.addEventListener("click", signOut);
        host.appendChild(out);
        if (isGlobalFounder()) {
          var fix = el("button", "link-btn quiet", "Reset a password");
          fix.type = "button";
          fix.addEventListener("click", resetSomeone);
          host.appendChild(fix);
        }
      } else {
        host.appendChild(el("span", null, "Viewing only."));
        var b = el("button", "link-btn", "Sign in");
        b.type = "button";
        b.addEventListener("click", function () { openGate(); });
        host.appendChild(b);
      }
    });
  }

  // At home the box offers every name in this copy. On the internet the
  // server sends no list, and the box is simply a name and a password.
  function paintUserOptions() {
    var pick = $("g-pick");
    pick.textContent = "";

    knownUsers.forEach(function (u) {
      var o = document.createElement("option");
      o.value = u.name;
      o.textContent = u.name;
      pick.appendChild(o);
    });

    var add = document.createElement("option");
    add.value = NEW_USER;
    add.textContent = knownUsers.length ? "+ Add a new user" : "+ Add the first user";
    pick.appendChild(add);

    var mine = user && knownUsers.some(function (u) { return u.name === user.name; });
    pick.value = mine ? user.name : (knownUsers.length ? knownUsers[0].name : NEW_USER);

    $("pickField").hidden = knownUsers.length === 0;
    syncGateFields();
  }

  function syncGateFields() {
    var adding = $("g-pick").value === NEW_USER || knownUsers.length === 0;
    $("nameField").hidden = !adding;
    $("g-name").required = adding;
    $("nameLabel").textContent = knownUsers.length ? "New name" : "Name";
  }

  $("g-pick").addEventListener("change", function () {
    syncGateFields();
    $("gateMsg").textContent = "";
    if (!$("nameField").hidden) $("g-name").focus();
    else $("g-pass").focus();
  });

  function openGate() {
    $("gateMsg").textContent = "";
    $("g-name").value = "";
    $("g-pass").value = "";
    if (!$("gate").open) $("gate").showModal();

    api("/api/users")
      .then(function (list) {
        knownUsers = Array.isArray(list) ? list : [];
        paintUserOptions();
        setTimeout(function () {
          ($("nameField").hidden ? $("g-pass") : $("g-name")).focus();
        }, 20);
      })
      .catch(function (err) {
        knownUsers = [];
        paintUserOptions();
        $("gateMsg").textContent = err.message;
      });
  }

  $("gateSkip").addEventListener("click", function () { $("gate").close(); });

  $("gateForm").addEventListener("submit", function (e) {
    e.preventDefault();

    var adding = $("nameField").hidden === false;
    var name = adding ? $("g-name").value.trim() : $("g-pick").value;
    var pass = $("g-pass").value;

    if (name.length < 2) { $("gateMsg").textContent = "A name needs at least two characters."; return; }
    if (!pass) { $("gateMsg").textContent = "Enter your password."; return; }

    $("gateSubmit").disabled = true;
    $("gateMsg").textContent = "";

    api("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, password: pass })
    })
      .then(function (data) {
        $("g-pass").value = "";
        signedIn(data);
        $("gateSubmit").disabled = false;
        $("gate").close();
        if (pendingGo) { var next = pendingGo; pendingGo = null; go(next); }
        else if (scope !== "home") { loadPlaces(); refresh(); }
      })
      .catch(function (err) {
        $("gateSubmit").disabled = false;
        $("gateMsg").textContent = err.message;
      });
  });

  /* -------------------------------------------------------- navigation -- */

  document.querySelectorAll(".gate-btn").forEach(function (b) {
    b.addEventListener("click", function () { go(b.dataset.go); });
  });

  $("backBtn").addEventListener("click", function () { go("home"); });

  function go(where) {
    scope = where;
    if (timer) { clearInterval(timer); timer = null; }

    if (where === "home") {
      $("home").hidden = false;
      $("view").hidden = true;
      return;
    }

    if (where === "personal" && !user) {
      pendingGo = "personal";
      scope = "home";
      openGate();
      $("gateMsg").textContent = "My Intelligence needs a name.";
      return;
    }

    $("home").hidden = true;
    $("view").hidden = false;

    entries = [];
    loaded = false;
    open = {};
    placeFilter = "";
    if (where === "collective") { trail = []; realm = ""; }
    $("filter").value = "";

    paintView();
    render();
    loadPlaces();
    refresh();
    // Check for new records every half minute -- but only while this tab is
    // actually being looked at. A tab left open in the background costs the
    // site nothing.
    timer = setInterval(function () { if (!document.hidden) refresh(); }, 30000);
  }

  function here() { return trail.length ? trail[trail.length - 1] : null; }

  function paintView() {
    var personal = scope === "personal";
    var spot = here();

    $("colophon").hidden = false;
    $("colophon").textContent = personal
      ? "Nothing here can be edited once entered. Only removed."
      : "Nothing here can ever be removed.";

    if (personal) {
      $("crumbs").hidden = true;
      setTitle("My Intelligence", user ? user.name : "");
      $("viewNote").textContent = "Private until you share a record to the Collective.";
      $("addBtn").hidden = false;
      $("groups").hidden = true;
      $("chips").hidden = false;
      $("bar").hidden = false;
      $("colophon").textContent = "Nothing here can be edited once entered. Only removed.";
      return;
    }

    $("chips").hidden = true;
    $("groups").hidden = false;
    $("addBtn").hidden = true;

    // The line at the bottom belongs to the section you are standing in.
    var sec = section(realm);
    var foot = sec ? sec.foot : "";
    $("colophon").textContent = foot;
    $("colophon").hidden = !foot;

    // Collective Intelligence: pick a section, then walk the tree. A community
    // holds communities, projects and tasks; a news channel holds only more
    // channels; a project or task is the end of a branch and holds records.
    if (!realm || DOORS[realm]) {
      $("crumbs").hidden = !realm;
      if (realm) paintCrumbs();
      setTitle(sec ? sec.label : "Collective Intelligence", "");
      $("viewNote").textContent = realm ? ""
        : "Publicly accessible, permanent knowledge.";
      $("bar").hidden = true;
      $("addBtn").hidden = true;
    } else if (!spot) {
      paintCrumbs();
      setTitle(sec ? sec.label : "", "");
      $("viewNote").textContent = "";
      $("bar").hidden = true;
      $("addBtn").hidden = true;
    } else {
      var holds = HOLDS[spot.kind] === true;
      paintCrumbs();
      // Say plainly whether you may only look here, or may also put things in.
      setTitle(spot.name, "", spot.canContribute === false ? "Viewable" : "Editable");
      $("viewNote").textContent = holds
        ? ""
        : "Records in this " + String(spot.kind).toLowerCase() + ".";
      $("bar").hidden = false;
      $("groups").hidden = !holds;
      // Anyone who may contribute here may write a record straight into it.
      $("addBtn").hidden = !user || spot.canContribute === false;
    }
  }

  /* ------------------------------------------------------------ signature -- */

  // The heading of a space, with the signer's name after it in their own hand
  // when the space belongs to somebody.
  function setTitle(text, signedBy, state) {
    var host = $("viewTitle");
    host.textContent = text;
    if (signedBy) {
      host.appendChild(document.createTextNode(" "));
      host.appendChild(el("span", "sig-inline", "(" + signedBy + ")"));
    }
    if (state) {
      host.appendChild(document.createTextNode(" "));
      host.appendChild(el("span", "state", "(" + state + ")"));
    }
  }

  function paintCrumbs() {
    var host = $("crumbs");
    host.hidden = false;
    host.textContent = "";

    var root = el("button", null, "Collective Intelligence");
    root.type = "button";
    root.addEventListener("click", function () { realm = ""; trail = []; enterCollective(); });
    host.appendChild(root);

    // Every section above the one you are in, so My News reads
    // Collective Intelligence / My Network / My News.
    var chain = [], key = realm;
    while (key) { chain.unshift(key); key = (section(key) || {}).parent; }

    chain.forEach(function (step, i) {
      var last = (i === chain.length - 1) && !trail.length;
      host.appendChild(el("span", "sep", "/"));
      if (last) {
        host.appendChild(el("span", null, SECTIONS[step].label));
      } else {
        var lvl = el("button", null, SECTIONS[step].label);
        lvl.type = "button";
        lvl.addEventListener("click", function () {
          realm = step; trail = []; enterCollective();
        });
        host.appendChild(lvl);
      }
    });

    trail.forEach(function (step, i) {
      host.appendChild(el("span", "sep", "/"));
      if (i === trail.length - 1) {
        host.appendChild(el("span", null, step.name));
      } else {
        var b = el("button", null, step.name);
        b.type = "button";
        b.addEventListener("click", function () {
          trail = trail.slice(0, i + 1);
          enterCollective();
        });
        host.appendChild(b);
      }
    });
  }

  function enterCollective() {
    seeking = "";
    results = [];
    removing = "";
    entries = [];
    loaded = false;
    open = {};
    $("filter").value = "";
    paintView();
    render();
    loadPlaces();
    refresh();
  }

  /* ---------------------------------- files, communities, projects, tasks -- */

  function loadPlaces() {
    if (scope === "personal") {
      return api("/api/folders?userId=" + encodeURIComponent(user ? user.id : ""))
        .then(function (list) { folders = Array.isArray(list) ? list : []; paintChips(); })
        .catch(function () { paintChips(); });
    }

    // A screen of doors, and anything that is a leaf, hold no children.
    var at = here();
    if (!realm || DOORS[realm] || (at && HOLDS[at.kind] !== true)) {
      groupings = [];
      paintGroups();
      return Promise.resolve();
    }

    var spot = here();
    // The userId matters on both: what is inside a community depends on who
    // is asking, now that a community can be shut to some people.
    var who = "&userId=" + encodeURIComponent(user ? user.id : "");
    // My Network is one screen holding both halves, so it fetches both.
    var url = spot
      ? "/api/groupings?parent=" + encodeURIComponent(spot.id) + who
      : "/api/groupings?reach=" + realm + who;
    if (!spot && realm === "network") url = "/api/groupings?reach=network" + who;

    return api(url)
      .then(function (list) { groupings = Array.isArray(list) ? list : []; paintGroups(); })
      .catch(function () { paintGroups(); });
  }

  function placeLabel(pl) { return pl.name; }

  /* -- Personal: the files chip row -- */

  function paintChips() {
    var host = $("chips");
    host.textContent = "";
    if (!user || scope !== "personal") return;

    var all = el("button", "chip", "All records");
    all.type = "button";
    all.setAttribute("aria-pressed", String(placeFilter === ""));
    all.addEventListener("click", function () { placeFilter = ""; paintChips(); render(); });
    host.appendChild(all);

    folders.forEach(function (pl) {
      var c = el("button", "chip", pl.name);
      c.type = "button";
      c.setAttribute("aria-pressed", String(placeFilter === pl.id));
      c.addEventListener("click", function () { placeFilter = pl.id; paintChips(); render(); });
      host.appendChild(c);
    });

    var add = el("button", "chip add", "+ Create file");
    add.type = "button";
    add.addEventListener("click", openFolderDialog);
    host.appendChild(add);

    if (placeFilter) {
      var chosen = folders.filter(function (f) { return f.id === placeFilter; })[0];
      var drop = el("button", "chip", "Remove this file");
      drop.type = "button";
      drop.addEventListener("click", function () {
        if (drop.textContent !== "Remove this file") {
          api("/api/folders/" + placeFilter + "/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ userId: user.id })
          }).then(function () {
            placeFilter = "";
            loadPlaces();
            refresh();
          }).catch(function (err) { drop.textContent = err.message; });
        } else {
          drop.textContent = "Remove " + (chosen ? chosen.name : "it") + "? The records stay.";
        }
      });
      host.appendChild(drop);
    }
  }

  /* -- Collective: the list of communities, or of projects and tasks -- */

  var removing = "";     // which half of My Network is offering a way off
  var seeking = "";      // what is typed in a section's search box
  var results = [];      // what came back for it
  var seekTimer = null;

  function seekBox() {
    var wrap = el("div", "seek");
    var box = document.createElement("input");
    box.type = "search";
    box.placeholder = realm === "news" ? "Search News" : "Search Global Communities";
    box.value = seeking;
    box.addEventListener("input", function () {
      seeking = box.value.trim();
      clearTimeout(seekTimer);
      seekTimer = setTimeout(runSeek, 200);
    });
    wrap.appendChild(box);
    // Repainting the list replaces this node, so put the caret back.
    setTimeout(function () {
      if (document.activeElement !== box && seeking) {
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
      }
    }, 0);
    return wrap;
  }

  function runSeek() {
    var asked = seeking;
    if (!asked) { results = []; paintGroups(); return; }
    api("/api/groupings?reach=" + realm + "&q=" + encodeURIComponent(asked)
        + "&userId=" + encodeURIComponent(user ? user.id : ""))
      .then(function (list) {
        if (seeking !== asked) return;      // a later keystroke already won
        results = Array.isArray(list) ? list : [];
        paintGroups();
      })
      .catch(function () { results = []; paintGroups(); });
  }

  // One row in a list of communities, channels, projects or tasks.
  function groupRow(g, showState) {
    var rowEl = el("button", "group-row" + (showState ? " stated" : ""));
    rowEl.type = "button";
    // Only a project or task needs saying. A community or a channel is
    // obvious from where you are, at the top and nested alike.
    if (HOLDS[g.kind] !== true) {
      rowEl.appendChild(el("span", "k", String(g.kind).toUpperCase()));
    }
    rowEl.appendChild(el("span", "n", g.name));
    // In your own network, say what you may do in each without opening it.
    if (showState) {
      rowEl.appendChild(el("span", "state",
        g.canContribute === false ? "(Viewable)" : "(Editable)"));
    }
    if (g.path && g.path.length > 1) {
      rowEl.appendChild(el("span", "path",
        g.path.slice(0, -1).map(function (n) { return n.name; }).join(" / ")));
    }
    if (g.reward && g.reward.offers) {
      rowEl.appendChild(el("span", "k", money(g.reward.total) + " OFFERED"));
    }
    rowEl.appendChild(el("span", "go", "\u2192"));
    rowEl.addEventListener("click", function () {
      if (g.path) {
        // A search hit: walk to where it actually lives.
        trail = g.path.map(function (n) {
          return n.id === g.id
            ? { id: g.id, kind: g.kind, name: g.name, isFounder: g.isFounder,
                canContribute: g.canContribute }
            : { id: n.id, kind: n.kind, name: n.name };
        });
        seeking = "";
      } else {
        trail = trail.concat([{ id: g.id, kind: g.kind, name: g.name,
                                isFounder: g.isFounder, canContribute: g.canContribute,
                                reward: g.reward }]);
      }
      enterCollective();
    });
    return rowEl;
  }

  // While removing, every row gets a way off your list beside it.
  function withRemove(rowEl, g) {
    var line = el("div", "group-line");
    line.appendChild(rowEl);
    var off = el("button", "link-btn drop-btn", "Remove");
    off.type = "button";
    off.addEventListener("click", function () {
      off.disabled = true;
      api("/api/groupings/" + g.id + "/feed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: user.id })
      })
        .then(function () { return loadPlaces(); })
        .catch(function (err) { off.disabled = false; off.textContent = err.message; });
    });
    line.appendChild(off);
    return line;
  }

  function actionBar(host) {
    var wrap = el("div", "group-add");
    host.appendChild(wrap);
    return function (label, go, cls) {
      var b = el("button", "link-btn" + (cls ? " " + cls : ""), label);
      b.type = "button";
      b.addEventListener("click", go);
      wrap.appendChild(b);
      return b;
    };
  }

  // My Network: both lists on one screen, one above the other, each in its
  // own box that grows with what is in it.
  function paintNetwork(host) {
    HALVES.forEach(function (half) {
      var box = el("div", "box");
      box.appendChild(el("p", "half", half.label));

      var rows = groupings.filter(function (g) { return g.kind === half.kind; });
      var off = removing === half.kind;
      rows.forEach(function (g) {
        var rowEl = groupRow(g, true);
        box.appendChild(off ? withRemove(rowEl, g) : rowEl);
      });
      if (!rows.length) box.appendChild(el("p", "empty", "None yet."));

      if (user) {
        var act = actionBar(box);
        act(half.make, function () { openGroupDialog("community", half.kind); });
        act(half.browse, function () { openBrowse(half.how); });
        // Press it and every row in THIS box offers a way off your list;
        // press it again and they go quiet.
        if (rows.length) {
          act(off ? "Done" : half.drop, function () {
            removing = off ? "" : half.kind;
            paintGroups();
          });
        }
      }
      host.appendChild(box);
    });
  }

  function paintGroups() {
    var host = $("groups");
    host.textContent = "";
    host.classList.remove("boxed");
    $("colophon").classList.remove("bare");
    var at = here();
    if (scope !== "collective") return;

    // A project or task holds records, not places. The only thing to offer
    // there is a reward, and only on a task.
    if (at && HOLDS[at.kind] !== true) {
      if (String(at.kind).toLowerCase() !== "task") return;
      var purse = el("div", "group-add");
      if (at.reward && at.reward.offers) {
        purse.appendChild(el("span", "hint", money(at.reward.total) + " offered so far."));
      }
      if (user) {
        var give = el("button", "link-btn", "Reward");
        give.type = "button";
        give.addEventListener("click", function () { openReward(at); });
        purse.appendChild(give);
      }
      host.appendChild(purse);
      return;
    }

    // The one screen of doors: the three sections.
    if (DOORS[realm]) {
      DOORS[realm].forEach(function (key) {
        var pick = el("button", "group-row");
        pick.type = "button";
        pick.appendChild(el("span", "n", SECTIONS[key].label));
        pick.appendChild(el("span", "go", "\u2192"));
        pick.addEventListener("click", function () {
          if (key === "network" && !user) {
            openGate();
            $("gateMsg").textContent = "Your own network needs a name.";
            return;
          }
          realm = key;
          trail = [];
          enterCollective();
        });
        host.appendChild(pick);
      });
      return;
    }

    if (realm === "network" && !trail.length) {
      host.classList.add("boxed");
      $("colophon").classList.add("bare");
      paintNetwork(host);
      return;
    }

    // The two permanent public sections can be searched, at any depth.
    if (!trail.length) host.appendChild(seekBox());

    var listing = seeking ? results : groupings;
    listing.forEach(function (g) { host.appendChild(groupRow(g, false)); });

    if (seeking && !listing.length) {
      host.appendChild(el("p", "empty", "Nothing here is called that."));
      return;
    }

    // At the top of a section, say there is nothing yet. Inside one, say
    // nothing at all: the buttons below already show what can go here.
    if (!listing.length && !seeking && !trail.length) {
      host.appendChild(el("p", "empty", "None yet."));
    }

    if (!user) return;

    var spot = here();
    var action = actionBar(host);

    if (!spot) {
      // The top of a permanent public section. Only one person founds here.
      if (isGlobalFounder()) {
        action(realm === "news" ? "+ Create channel" : "+ Create global community",
               function () { openGroupDialog("community"); });
      }
    } else {
      // Inside one. Founding another belongs to whoever founded this one, or
      // anything above it. A news channel holds only more channels; a
      // community also holds projects and tasks. Any contributor writes
      // records into either.
      if (spot.isFounder) {
        action(spot.kind === "Channel" ? "+ Create channel" : "+ Create community",
               function () { openGroupDialog("community"); });
      }
      if (spot.kind !== "Channel" && spot.canContribute !== false) {
        action("+ Create project or task", function () { openGroupDialog("child"); });
      }
      if (spot.isFounder) {
        action("Who can view", function () { openAccess(spot, "view"); });
        action("Who can contribute", function () { openAccess(spot, "contribute"); });
      }
      // The operator may correct a name or take the whole thing down.
      if (isOperator()) {
        action("Rename", function () { openRename(spot); });
        var kill = action("Take down", function () {
          if (kill.textContent === "Take down") {
            kill.textContent = "Take down " + spot.name + "?";
            return;
          }
          kill.disabled = true;
          api("/api/groupings/" + spot.id + "/takedown", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ userId: user.id })
          })
            .then(function () { trail = trail.slice(0, -1); enterCollective(); })
            .catch(function (err) { kill.disabled = false; kill.textContent = err.message; });
        }, "quiet");
      }
    }
  }

  /* -- the operator: one person who may correct or take down anything -- */

  function isOperator() { return isGlobalFounder(); }

  function openRename(spot) {
    var name = window.prompt("Rename this", spot.name);
    if (name === null) return;
    name = name.trim();
    if (!name) return;
    api("/api/groupings/" + spot.id + "/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, name: name })
    })
      .then(function () {
        if (trail.length) trail[trail.length - 1].name = name;
        enterCollective();
      })
      .catch(function (err) { window.alert(err.message); });
  }

  /* -- new file (Personal) -- */

  function openFolderDialog() {
    $("folderForm").reset();
    $("folderMsg").textContent = "";
    $("folderDialog").showModal();
    setTimeout(function () { $("fo-name").focus(); }, 30);
  }

  $("folderCancel").addEventListener("click", function () { $("folderDialog").close(); });

  $("folderForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var name = $("fo-name").value.trim();
    if (!name) { $("folderMsg").textContent = "A file needs a name."; return; }

    $("folderSubmit").disabled = true;
    api("/api/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, name: name })
    })
      .then(function () {
        $("folderSubmit").disabled = false;
        $("folderDialog").close();
        return loadPlaces();
      })
      .catch(function (err) {
        $("folderSubmit").disabled = false;
        $("folderMsg").textContent = err.message;
      });
  });

  /* -- browse: communities somebody else opened to everybody -- */

  function openBrowse(which) {
    if (!user) { openGate(); return; }
    var channels = which === "browsenews";
    $("browseHeading").textContent = channels ? "Browse news" : "Browse communities";
    $("browseLead").textContent = channels
      ? "News channels other people have opened to everybody. Joining one puts "
        + "it in My News, and reaches every channel inside it."
      : "Communities other people have opened to everybody, global ones "
        + "included. Joining one puts it in My Communities, and reaches "
        + "everything inside it.";
    $("browseMsg").textContent = "";
    var host = $("browseList");
    host.textContent = "";
    host.appendChild(el("span", "hint", "Looking..."));
    $("browseDialog").showModal();

    api("/api/groupings?reach=" + (channels ? "browsenews" : "browse")
        + "&userId=" + encodeURIComponent(user.id))
      .then(function (list) {
        var open = Array.isArray(list) ? list : [];
        host.textContent = "";
        if (!open.length) {
          host.appendChild(el("span", "hint", channels
            ? "Nothing to join. A channel shows up here once the person who founded it opens it to everybody."
            : "Nothing to join. A community shows up here once the person who founded it opens it to everybody."));
          return;
        }
        var box = el("div", "checks");
        open.forEach(function (g) {
          var row = el("div", "browse-row");
          row.appendChild(el("span", "n", g.name));
          var join = el("button", "link-btn", "Join");
          join.type = "button";
          join.addEventListener("click", function () {
            join.disabled = true;
            join.textContent = "Joining...";
            api("/api/groupings/" + g.id + "/join", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ userId: user.id })
            })
              .then(function () { row.remove(); loadPlaces(); })
              .catch(function (err) { join.disabled = false; join.textContent = err.message; });
          });
          row.appendChild(join);
          box.appendChild(row);
        });
        host.appendChild(box);
      })
      .catch(function (err) {
        host.textContent = "";
        host.appendChild(el("span", "hint", err.message));
      });
  }

  $("browseClose").addEventListener("click", function () { $("browseDialog").close(); });

  /* -- who can contribute to a community -- */

  var governing = null;
  var governKind = "contribute";

  function syncAccess() {
    var picked = $("accessForm").querySelector('input[name="contribute"]:checked');
    $("accessSub").hidden = !picked || picked.value !== "invite";
  }

  $("accessForm").querySelectorAll('input[name="contribute"]').forEach(function (radio) {
    radio.addEventListener("change", syncAccess);
  });

  function openAccess(spot, kind) {
    governing = spot;
    governKind = kind === "view" ? "view" : "contribute";
    $("accessHeading").textContent =
      (governKind === "view" ? "Who can view " : "Who can contribute to ") + spot.name;
    $("accessLead").textContent =
      "This covers " + spot.name + " and everything inside it, and nothing above it."
      + (governKind === "view"
          ? " Taking viewing away takes contributing with it."
          : " Anyone who can contribute can also view.");
    $("accessMsg").textContent = "";
    var host = $("accessList");
    host.textContent = "";
    host.appendChild(el("span", "hint", "Loading..."));
    $("accessDialog").showModal();

    api("/api/groupings/" + spot.id + "/access?userId=" + encodeURIComponent(user.id))
      .then(function (info) {
        var mode = (governKind === "view" ? info.viewing : info.contribute) || "invite";
        $("accessForm").querySelector('input[value="' + mode + '"]').checked = true;
        syncAccess();

        host.textContent = "";
        var others = (info.users || []).filter(function (u) { return u.id !== user.id; });
        var already = {};
        var ids = (governKind === "view" ? info.viewIds : info.contributeIds) || [];
        ids.forEach(function (id) { already[id] = true; });

        var box = el("div", "checks");
        function tick(value, text, on) {
          var label = document.createElement("label");
          var input = document.createElement("input");
          input.type = "checkbox";
          input.value = value;
          input.checked = on;
          label.appendChild(input);
          label.appendChild(document.createTextNode(text));
          box.appendChild(label);
        }
        others.forEach(function (u) { tick(u.id, u.name, !!already[u.id]); });
        host.appendChild(box);

        // Anyone not listed is added by typing their name exactly.
        var add = el("div", "group-add");
        var field = document.createElement("input");
        field.type = "text";
        field.placeholder = "Add someone by their exact name";
        field.style.flex = "1 1 220px";
        var go = el("button", "link-btn", "Add");
        go.type = "button";
        function addTyped() {
          var name = field.value.trim();
          if (name.length < 2) return;
          tick("name:" + name, name, true);
          field.value = "";
          field.focus();
        }
        go.addEventListener("click", addTyped);
        field.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); addTyped(); }
        });
        add.appendChild(field);
        add.appendChild(go);
        host.appendChild(add);
      })
      .catch(function (err) {
        host.textContent = "";
        host.appendChild(el("span", "hint", err.message));
      });
  }

  $("accessCancel").addEventListener("click", function () { $("accessDialog").close(); });

  $("accessForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!governing || !user) return;

    var picked = $("accessForm").querySelector('input[name="contribute"]:checked');
    var mode = picked ? picked.value : "invite";
    var ticked = [].slice.call($("accessList").querySelectorAll("input[type=checkbox]:checked"))
      .map(function (i) { return i.value; });
    var chosen = ticked.filter(function (v) { return v.indexOf("name:") !== 0; });
    var named = ticked.filter(function (v) { return v.indexOf("name:") === 0; })
      .map(function (v) { return v.slice(5); });

    $("accessSubmit").disabled = true;
    api("/api/groupings/" + governing.id + "/access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, kind: governKind,
                             mode: mode, memberIds: chosen, memberNames: named })
    })
      .then(function () {
        $("accessSubmit").disabled = false;
        $("accessDialog").close();
        governing = null;
        loadPlaces();
      })
      .catch(function (err) {
        $("accessSubmit").disabled = false;
        $("accessMsg").textContent = err.message;
      });
  });

  /* -- a reward offered for finishing a task -- */

  var rewarding = null;

  function money(n) {
    return "$" + Number(n || 0).toLocaleString(undefined,
      { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function openReward(spot) {
    if (!user) { openGate(); return; }
    rewarding = spot;
    $("rewardHeading").textContent = "Reward for " + spot.name;
    $("rewardMsg").textContent = "";
    $("rw-amount").value = "";
    $("rw-note").value = "";
    var host = $("rewardSoFar");
    host.textContent = "";
    $("rewardDialog").showModal();

    api("/api/groupings/" + spot.id + "/rewards")
      .then(function (info) {
        host.textContent = "";
        var offers = info.offers || [];
        if (!offers.length) {
          host.appendChild(el("span", "hint", "Nothing offered yet."));
          return;
        }
        host.appendChild(el("p", "hint",
          money(info.total) + " offered, across " + offers.length
          + (offers.length === 1 ? " offer." : " offers.")));
        var box = el("div", "checks");
        offers.forEach(function (o) {
          box.appendChild(el("div", "browse-row",
            money(o.amount) + " \u2014 " + o.author + (o.note ? " (" + o.note + ")" : "")));
        });
        host.appendChild(box);
      })
      .catch(function (err) {
        host.textContent = "";
        host.appendChild(el("span", "hint", err.message));
      });

    setTimeout(function () { $("rw-amount").focus(); }, 30);
  }

  $("rewardCancel").addEventListener("click", function () { $("rewardDialog").close(); });

  $("rewardForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!rewarding || !user) return;
    var amount = parseFloat($("rw-amount").value);
    if (!(amount > 0)) { $("rewardMsg").textContent = "Put in an amount."; return; }

    $("rewardSubmit").disabled = true;
    api("/api/groupings/" + rewarding.id + "/rewards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, amount: amount,
                             note: $("rw-note").value.trim() })
    })
      .then(function () {
        $("rewardSubmit").disabled = false;
        $("rewardDialog").close();
        rewarding = null;
        loadPlaces();
      })
      .catch(function (err) {
        $("rewardSubmit").disabled = false;
        $("rewardMsg").textContent = err.message;
      });
  });

  /* -- new community, project or task (Collective) -- */

  $("gr-kind").addEventListener("change", function () {
    var own = $("gr-kind").value === "__own__";
    $("grKindOther").hidden = !own;
    if (own) $("gr-kind-other").focus();
  });

  var groupMode = "community";   // "community" = found one, "child" = project or task
  var makingKind = "";           // which half of My Network asked, when it did

  function openGroupDialog(mode, halfKind) {
    groupMode = mode || "community";
    makingKind = halfKind || "";
    var inside = here();
    var channel = inside ? inside.kind === "Channel"
                         : (halfKind ? halfKind === "Channel" : isNewsRealm(realm));
    var word = channel ? "channel" : "community";
    $("groupForm").reset();
    $("grKindOther").hidden = true;
    $("grKindField").hidden = groupMode !== "child";
    $("groupHeading").textContent =
      groupMode === "child" ? "Create project or task"
        : (inside ? "Create " + word + " inside " + inside.name
                  : (realm === "global" ? "Create global community"
                                        : "Create " + word));
    $("gr-name").placeholder = channel ? "Oncology" : "Cancer Research";
    $("groupMsg").textContent = "";
    $("groupDialog").showModal();
    setTimeout(function () { $("gr-name").focus(); }, 30);
  }

  $("groupCancel").addEventListener("click", function () { $("groupDialog").close(); });

  $("groupForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var inside = here();
    var kindValue = (inside ? inside.kind === "Channel"
                            : (makingKind ? makingKind === "Channel" : isNewsRealm(realm)))
      ? "Channel" : "Community";

    if (groupMode === "child") {
      kindValue = $("gr-kind").value === "__own__"
        ? $("gr-kind-other").value.trim() : $("gr-kind").value;
      if (!kindValue) { $("groupMsg").textContent = "Say what kind of thing this is."; return; }
    }

    var name = $("gr-name").value.trim();
    if (!name) { $("groupMsg").textContent = "It must be named."; return; }

    $("groupSubmit").disabled = true;
    api("/api/groupings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, kind: kindValue, name: name,
                             parentId: inside ? inside.id : "",
                             reach: inside ? "" : (realm === "network" ? "mine" : realm) })
    })
      .then(function () {
        $("groupSubmit").disabled = false;
        $("groupDialog").close();
        return loadPlaces();
      })
      .catch(function (err) {
        $("groupSubmit").disabled = false;
        $("groupMsg").textContent = err.message;
      });
  });

  /* ----------------------------------------------------------- loading -- */

  function refresh() {
    var spot = here();

    if (scope === "collective" && !spot) {   // the list of communities has no records
      entries = [];
      loaded = true;
      render();
      return Promise.resolve();
    }

    var url = scope === "personal"
      ? "/api/entries?scope=personal&userId=" + encodeURIComponent(user ? user.id : "")
      : "/api/entries?scope=collective&groupId=" + encodeURIComponent(spot.id);

    // Tell the server which version of this list the page already holds.
    // If nothing changed it answers with nothing at all (204), and the page
    // keeps what it has -- the whole list travels only when it is new.
    var headers = {};
    if (known.url === url && known.tag) headers["X-Known"] = known.tag;

    return fetch(url, { headers: headers })
      .then(function (res) {
        if (res.status === 204) { loaded = true; render(); return; }
        return res.json().catch(function () { return {}; }).then(function (rows) {
          if (!res.ok) throw new Error(rows.error || "Something went wrong.");
          known = { url: url, tag: res.headers.get("X-Version") || "" };
          entries = Array.isArray(rows) ? rows : [];
          loaded = true;
          render();
        });
      }, function () {
        throw new Error("The site is not responding. Check your connection, then try again.");
      })
      .catch(function (err) {
        known = { url: "", tag: "" };
        loaded = true;
        render(err.message);
      });
  }

  var known = { url: "", tag: "" };   // the version of the record list on screen

  // Coming back to a tab that sat in the background: catch up at once.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && scope !== "home") refresh();
  });

  /* --------------------------------------------------------- rendering -- */

  $("filter").addEventListener("input", function () { render(); });

  function matches(r, q) {
    if (!q) return true;
    var s = stamp(r.createdAt);
    var bits = [r.author, r.fn, r.title, s.time, s.date];
    (r.pieces || []).forEach(function (pc) {
      bits.push(pc.url, pc.text, pc.fileName);
    });
    return bits.join(" ").toLowerCase().indexOf(q) !== -1;
  }

  function render(problem) {
    var host = $("ledger");
    var q = $("filter").value.trim().toLowerCase();
    host.textContent = "";

    var byId = {};
    entries.forEach(function (r) { byId[r.id] = r; });

    // A response hangs under whatever it answers, however deep that goes.
    var roots = [];
    var kids = {};
    entries.forEach(function (r) {
      if (r.replyTo && byId[r.replyTo]) (kids[r.replyTo] = kids[r.replyTo] || []).push(r);
      else roots.push(r);
    });

    function subtree(r) {
      var out = [r];
      (kids[r.id] || []).forEach(function (c) { out = out.concat(subtree(c)); });
      return out;
    }

    // Filtering keeps whole chains intact: if anything in a chain matches,
    // the chain is shown, so a response never floats loose from its parent.
    function keep(root) {
      var chain = subtree(root);
      var textOk = !q || chain.some(function (r) { return matches(r, q); });
      var placeOk = !placeFilter
        || chain.some(function (r) { return r.folderId === placeFilter; });
      return textOk && placeOk;
    }

    var total = entries.length;
    var shown = 0;

    function draw(r, depth) {
      host.appendChild(row(r, depth));
      shown += 1;
      (kids[r.id] || []).forEach(function (c) { draw(c, depth + 1); });
    }

    roots.forEach(function (root) { if (keep(root)) draw(root, 0); });

    $("count").textContent = (q || placeFilter)
      ? shown + " / " + total
      : total + (total === 1 ? " record" : " records");

    if (!shown) host.appendChild(emptyNote(q, problem));
  }

  function emptyNote(q, problem) {
    var e = el("p", "empty");
    if (problem) e.textContent = problem;
    else if (!loaded) e.textContent = "Reading...";
    else if (q) e.textContent = "Nothing matches “" + q + "”.";
    else if (placeFilter) e.textContent = "Nothing has been put in this file yet. Open a record and choose it from the list at the bottom.";
    else if (scope === "personal") e.textContent = "None yet.";
    // Inside the Collective, an empty place says nothing at all. The buttons
    // below it already show what can go there.
    else e.textContent = "";
    return e;
  }

  function row(r, depth) {
    var art = el("article", "rec" + (depth ? " reply" : ""));
    // Indent by depth, but stop widening after a few levels so a long chain
    // never runs off the side of the page.
    if (depth) art.style.marginLeft = Math.min(depth, 5) * 26 + "px";

    var btn = el("button", "line");
    btn.type = "button";

    var s = stamp(r.createdAt);
    var t = el("span", "rec-text");
    t.appendChild(el("span", "stamp", s.time));
    t.appendChild(document.createTextNode(", "));
    t.appendChild(el("span", "stamp", s.date));
    t.appendChild(document.createTextNode(", "));
    t.appendChild(el("span", "who-name", r.author || "Unattributed"));
    t.appendChild(document.createTextNode(", "));
    t.appendChild(el("span", "fn", r.fn || ""));
    if (r.title) {
      t.appendChild(document.createTextNode(", "));
      t.appendChild(el("span", "ttl", r.title));
    }
    btn.appendChild(t);

    var tags = el("span", "tags");
    if (scope === "personal" && r.shared) tags.appendChild(el("span", "tag on", "SHARED"));
    // One tag per sort of thing the record carries, in a steady order.
    ["link", "file", "text"].forEach(function (k) {
      var n = (r.pieces || []).filter(function (pc) { return pc.kind === k; }).length;
      if (!n) return;
      tags.appendChild(el("span", "tag",
        (PIECE_LABEL[k] || k).toUpperCase() + (n > 1 ? " ×" + n : "")));
    });
    btn.appendChild(tags);

    var body = el("div", "body");
    body.hidden = !open[r.id];
    btn.setAttribute("aria-expanded", String(!!open[r.id]));

    btn.addEventListener("click", function () {
      open[r.id] = body.hidden;
      body.hidden = !body.hidden;
      btn.setAttribute("aria-expanded", String(!body.hidden));
      if (!body.hidden && !body.dataset.filled) fill(body, r);
    });

    if (open[r.id]) fill(body, r);

    art.appendChild(btn);
    art.appendChild(body);
    return art;
  }

  function fill(body, r) {
    body.dataset.filled = "1";
    body.textContent = "";

    (r.pieces || []).forEach(function (piece) {
      var pay = el("div", "payload");

      if (piece.kind === "link") {
        var a = el("a", null, piece.url);
        a.href = piece.url; a.target = "_blank"; a.rel = "noopener noreferrer";
        pay.appendChild(a);
      } else if (piece.kind === "text") {
        pay.appendChild(el("pre", null, piece.text));
      } else {
        pay.appendChild(el("div", "meta", piece.fileName + "  ·  " + bytes(piece.fileSize)));
        pay.appendChild(preview(piece));
        var dl = el("a", "link-btn", "Save file");
        dl.href = piece.fileUrl + "?download";
        dl.setAttribute("download", piece.fileName);
        pay.appendChild(dl);
      }

      body.appendChild(pay);
    });

    body.appendChild(rowActions(r));
  }

  function rowActions(r) {
    var wrap = el("div", "actions");
    var mine = user && r.userId === user.id;

    if (scope === "personal" && mine) {
      var share = el("button", "link-btn",
        r.shared ? "Share to more communities" : "Share");
      share.type = "button";
      share.addEventListener("click", function () { openShare(r); });
      wrap.appendChild(share);
    }

    if (scope === "collective") {
      var respond = el("button", "link-btn", "Respond");
      respond.type = "button";
      respond.addEventListener("click", function () {
        if (!user) { openGate(); $("gateMsg").textContent = "Responding needs a name."; return; }
        openRecord(r);
      });
      wrap.appendChild(respond);
    }

    // Personal: which file it is in.
    if (scope === "personal" && mine && folders.length) {
      wrap.appendChild(el("span", "meta", "File"));
      var pick = document.createElement("select");
      pick.style.width = "auto";
      pick.style.fontSize = "12px";

      var none = document.createElement("option");
      none.value = "";
      none.textContent = "— none —";
      pick.appendChild(none);

      folders.forEach(function (pl) {
        var o = document.createElement("option");
        o.value = pl.id;
        o.textContent = pl.name;
        pick.appendChild(o);
      });

      pick.value = r.folderId || "";
      pick.addEventListener("change", function () {
        pick.disabled = true;
        api("/api/entries/" + r.id + "/place", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userId: user.id, folderId: pick.value })
        })
          .then(function () { pick.disabled = false; refresh(); })
          .catch(function () { pick.disabled = false; pick.value = r.folderId || ""; });
      });
      wrap.appendChild(pick);
    }

    // Inside a community: move a record down into something it holds.
    if (scope === "collective" && mine && here() && here().kind === "Community" && groupings.length) {
      wrap.appendChild(el("span", "meta", "Move into"));
      var into = document.createElement("select");
      into.style.width = "auto";
      into.style.fontSize = "12px";

      var stay = document.createElement("option");
      stay.value = "";
      stay.textContent = "— stays here —";
      into.appendChild(stay);

      groupings.forEach(function (g) {
        var o = document.createElement("option");
        o.value = g.id;
        o.textContent = g.kind + " · " + g.name;
        into.appendChild(o);
      });

      into.addEventListener("change", function () {
        if (!into.value) return;
        into.disabled = true;
        api("/api/entries/" + r.id + "/move", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userId: user.id, fromGroupId: here().id, toGroupId: into.value })
        })
          .then(function () { into.disabled = false; refresh(); })
          .catch(function () { into.disabled = false; into.value = ""; });
      });
      wrap.appendChild(into);
    }

    // Where a shared record ended up, shown in Personal so you can see it.
    if (scope === "personal" && r.places.length) {
      wrap.appendChild(el("span", "meta",
        "In " + r.places.map(function (p) { return p.name; }).join(", ")));
    }

    // Removal lives only in My Intelligence.
    if (scope === "personal" && mine) {
      var drop = el("button", "link-btn danger", "Remove");
      drop.type = "button";
      drop.addEventListener("click", function () {
        if (drop.textContent === "Remove") {
          drop.textContent = r.shared
            ? "Remove from Personal? It stays in the Collective."
            : "Remove for good?";
          return;
        }
        drop.disabled = true;
        api("/api/entries/" + r.id + "/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userId: user.id })
        })
          .then(function () { refresh(); })
          .catch(function (err) { drop.disabled = false; drop.textContent = err.message; });
      });
      wrap.appendChild(drop);
    }

    // The operator may correct a record or take it down. Everyone else cannot.
    if (isOperator()) {
      var fix = el("button", "link-btn", "Correct");
      fix.type = "button";
      fix.addEventListener("click", function () { openFix(r); });
      wrap.appendChild(fix);

      var down = el("button", "link-btn quiet", "Take down");
      down.type = "button";
      down.addEventListener("click", function () {
        if (down.textContent === "Take down") {
          down.textContent = "Take it down? Responses stay.";
          return;
        }
        down.disabled = true;
        api("/api/entries/" + r.id + "/takedown", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ userId: user.id })
        })
          .then(function () { refresh(); })
          .catch(function (err) { down.disabled = false; down.textContent = err.message; });
      });
      wrap.appendChild(down);
    }

    var st = stamp(r.createdAt);
    wrap.appendChild(el("span", "meta", "Recorded " + st.date + " " + st.time
      + (r.editedAt ? "  ·  corrected since" : "")));
    return wrap;
  }

  /* -- correcting a record: the operator's alone -- */

  var fixing = null;

  function openFix(r) {
    fixing = r;
    $("fixMsg").textContent = "";
    $("fx-fn").value = r.fn;
    $("fx-title").value = r.title || "";

    var host = $("fixPieces");
    host.textContent = "";
    (r.pieces || []).forEach(function (piece, i) {
      if (piece.kind === "file") return;      // a file is what it is
      var field = el("div", "field");
      field.appendChild(el("label", null, (piece.kind === "link" ? "Link " : "Note ") + (i + 1)));
      var input = piece.kind === "link"
        ? document.createElement("input")
        : document.createElement("textarea");
      if (piece.kind === "link") { input.type = "url"; input.value = piece.url || ""; }
      else { input.rows = 4; input.value = piece.text || ""; }
      input.dataset.pieceId = piece.id;
      input.dataset.kind = piece.kind;
      field.appendChild(input);
      host.appendChild(field);
    });
    if (!host.children.length) {
      host.appendChild(el("span", "hint", "This record carries only files, which cannot be corrected."));
    }

    $("fixDialog").showModal();
    setTimeout(function () { $("fx-title").focus(); }, 30);
  }

  $("fixCancel").addEventListener("click", function () { $("fixDialog").close(); });

  $("fixForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!fixing || !user) return;
    var fn = $("fx-fn").value.trim();
    if (!fn) { $("fixMsg").textContent = "Every record needs a function."; return; }

    var pieces = [].slice.call($("fixPieces").querySelectorAll("[data-piece-id]"))
      .map(function (i) {
        return i.dataset.kind === "link"
          ? { id: i.dataset.pieceId, url: i.value.trim() }
          : { id: i.dataset.pieceId, text: i.value };
      });

    $("fixSubmit").disabled = true;
    api("/api/entries/" + fixing.id + "/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, fn: fn,
                             title: $("fx-title").value.trim(), pieces: pieces })
    })
      .then(function () {
        $("fixSubmit").disabled = false;
        $("fixDialog").close();
        fixing = null;
        refresh();
      })
      .catch(function (err) {
        $("fixSubmit").disabled = false;
        $("fixMsg").textContent = err.message;
      });
  });

  /* ------------------------------------------------- share to communities -- */

  var sharing = null;

  function destChosen() {
    var picked = $("shareForm").querySelector('input[name="dest"]:checked');
    return picked ? picked.value : "keep";
  }

  var DEST_LISTS = { network: "networkList", global: "globalList", news: "newsList" };

  function syncDest() {
    var d = destChosen();
    $("networkSub").hidden = d !== "network";
    $("globalSub").hidden = d !== "global";
    $("newsSub").hidden = d !== "news";
  }

  $("shareForm").querySelectorAll('input[name="dest"]').forEach(function (radio) {
    radio.addEventListener("change", function () { syncDest(); $("shareMsg").textContent = ""; });
  });

  // The whole tree, indented, so a record can be sent straight to whichever
  // branch it belongs on — a community, one nested inside it, or a task.
  function paintShareList(host, tree, already) {
    host.textContent = "";
    if (!tree.length) {
      host.appendChild(el("span", "hint", "None yet."));
      return;
    }
    var box = el("div", "checks");
    (function walk(nodes, depth) {
      nodes.forEach(function (g) {
        box.appendChild(shareRow(g, already, depth));
        if (g.children && g.children.length) walk(g.children, depth + 1);
      });
    })(tree, 0);
    host.appendChild(box);
  }

  function shareRow(g, already, depth) {
    var label = document.createElement("label");
    if (depth) label.style.paddingLeft = (depth * 22) + "px";
    var input = document.createElement("input");
    input.type = "checkbox";
    input.value = g.id;
    if (already[g.id]) { input.checked = true; input.disabled = true; }
    label.appendChild(input);
    label.appendChild(document.createTextNode(
      (depth ? g.kind + " · " : "") + g.name + (already[g.id] ? "  (already there)" : "")));
    return label;
  }

  // Fetch children depth-first. The tree is small, and this keeps the dialog
  // honest about where a record can actually go.
  function withChildren(node, depth) {
    if (HOLDS[node.kind] !== true || depth > 5) {
      node.children = [];
      return Promise.resolve(node);
    }
    return api("/api/groupings?parent=" + encodeURIComponent(node.id)
               + "&userId=" + encodeURIComponent(user ? user.id : ""))
      .then(function (kids) {
        var list = Array.isArray(kids) ? kids : [];
        // Only offer places this person is actually allowed to put things in.
        list = list.filter(function (k) { return k.canContribute !== false; });
        return Promise.all(list.map(function (k) { return withChildren(k, depth + 1); }))
          .then(function (built) { node.children = built; return node; });
      })
      .catch(function () { node.children = []; return node; });
  }

  function loadShareOptions(reachName, host) {
    if (!user) return Promise.resolve();
    host.textContent = "";
    host.appendChild(el("span", "hint", "Loading..."));

    return api("/api/groupings?reach=" + reachName + "&userId=" + encodeURIComponent(user.id))
      .then(function (list) {
        var roots = (Array.isArray(list) ? list : [])
          .filter(function (c) { return c.canContribute !== false; });
        return Promise.all(roots.map(function (c) { return withChildren(c, 0); }));
      })
      .then(function (tree) {
        var already = {};
        if (sharing) sharing.places.forEach(function (p) { already[p.id] = true; });
        paintShareList(host, tree, already);
      })
      .catch(function (err) {
        host.textContent = "";
        host.appendChild(el("span", "hint", err.message));
      });
  }

  function openShare(r) {
    sharing = r;
    $("shareMsg").textContent = "";
    $("shareSubmit").disabled = false;
    $("shareForm").querySelector('input[value="keep"]').checked = true;
    syncDest();
    $("shareDialog").showModal();
    loadShareOptions("network", $("networkList"));
    loadShareOptions("global", $("globalList"));
    loadShareOptions("news", $("newsList"));
  }

  // A community of your own can be made right here, without leaving.
  $("mineNew").addEventListener("click", function () {
    var name = window.prompt("Name this community");
    if (name === null) return;
    name = name.trim();
    if (!name) { $("shareMsg").textContent = "It must be named."; return; }

    api("/api/groupings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, name: name, reach: "mine" })
    })
      .then(function () { return loadShareOptions("network", $("networkList")); })
      .catch(function (err) { $("shareMsg").textContent = err.message; });
  });

  $("shareCancel").addEventListener("click", function () { $("shareDialog").close(); });

  $("shareForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!sharing || !user) return;

    var d = destChosen();
    if (d === "keep") {          // the default: nothing leaves My Intelligence
      $("shareDialog").close();
      sharing = null;
      return;
    }

    var host = $(DEST_LISTS[d] || "networkList");
    var chosen = [].slice.call(host.querySelectorAll("input:checked"))
      .filter(function (i) { return !i.disabled; })
      .map(function (i) { return i.value; });

    if (!chosen.length) {
      $("shareMsg").textContent = "Choose where it goes, or keep it to yourself.";
      return;
    }

    $("shareSubmit").disabled = true;
    api("/api/entries/" + sharing.id + "/share", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: user.id, groupIds: chosen })
    })
      .then(function () {
        $("shareSubmit").disabled = false;
        $("shareDialog").close();
        sharing = null;
        refresh();
      })
      .catch(function (err) {
        $("shareSubmit").disabled = false;
        $("shareMsg").textContent = err.message;
      });
  });

  function preview(r) {
    var e = ext(r.fileName);
    var slot = el("div");

    if (IMG_EXT.indexOf(e) !== -1 || String(r.fileMime).indexOf("image/") === 0) {
      var img = el("img");
      img.alt = r.fileName;
      img.src = r.fileUrl;
      slot.appendChild(img);
    } else if (e === "pdf" || r.fileMime === "application/pdf") {
      var show = el("button", "link-btn", "Show PDF");
      show.type = "button";
      show.addEventListener("click", function () {
        show.remove();
        var f = document.createElement("iframe");
        f.src = r.fileUrl; f.title = r.fileName;
        slot.appendChild(f);
      });
      slot.appendChild(show);
    } else if (TEXT_EXT.indexOf(e) !== -1 || String(r.fileMime).indexOf("text/") === 0
               || r.fileMime === "application/json") {
      var pre = el("pre", "code", "Loading...");
      slot.appendChild(pre);
      fetch(r.fileUrl).then(function (res) { return res.text(); })
        .then(function (txt) { pre.textContent = txt; })
        .catch(function () { pre.textContent = "The file could not be read."; });
    } else {
      slot.appendChild(el("span", "hint", "Binary file - save it to read it."));
    }

    return slot;
  }

  /* -------------------------------------------------------- new record -- */

  var sel = $("f-fn");
  FUNCTIONS.forEach(function (f) {
    var o = document.createElement("option");
    o.value = f; o.textContent = f;
    sel.appendChild(o);
  });

  sel.addEventListener("change", function () {
    $("fnOtherField").hidden = sel.value !== "Other...";
    if (sel.value === "Other...") $("f-fn-other").focus();
  });

  /* -- the piece builder -------------------------------------------------
     A record is a function plus as many links, files and notes as you want.
     Each one gets a row here; the rows are read back on submit.            */

  var PIECE_LABEL = { link: "Link", file: "File", text: "Note" };

  function addPiece(kindName) {
    var wrap = el("div", "piece");
    wrap.dataset.kind = kindName;

    var head = el("div", "piece-head");
    head.appendChild(el("span", null, PIECE_LABEL[kindName]));
    var drop = el("button", "piece-drop", "Remove");
    drop.type = "button";
    drop.addEventListener("click", function () { wrap.remove(); });
    head.appendChild(drop);
    wrap.appendChild(head);

    if (kindName === "link") {
      var url = document.createElement("input");
      url.type = "url";
      url.className = "piece-input";
      url.placeholder = "https://claude.ai/share/...";
      wrap.appendChild(url);
    } else if (kindName === "file") {
      var file = document.createElement("input");
      file.type = "file";
      file.className = "piece-input";
      wrap.appendChild(file);
      wrap.appendChild(el("span", "hint", "PDF, code, text, image. Up to 25 MB — link anything larger."));
    } else {
      var note = document.createElement("textarea");
      note.className = "piece-input";
      note.placeholder = "The thought itself, unformatted.";
      wrap.appendChild(note);
    }

    $("pieces").appendChild(wrap);
    var input = wrap.querySelector(".piece-input");
    if (input && kindName !== "file") input.focus();
    return wrap;
  }

  document.querySelectorAll(".adder").forEach(function (b) {
    b.addEventListener("click", function () { addPiece(b.dataset.add); });
  });

  $("addBtn").addEventListener("click", function () {
    if (!user) { openGate(); $("gateMsg").textContent = "Adding a record needs a name."; return; }
    openRecord(null);
  });

  $("recordCancel").addEventListener("click", function () { $("recordDialog").close(); });

  function openRecord(parent) {
    replyTo = parent;
    $("recordForm").reset();
    $("fnOtherField").hidden = true;
    $("pieces").textContent = "";
    addPiece("link");           // one row to start; add or remove freely
    $("recordMsg").textContent = "";

    var s = stamp(new Date().toISOString());
    $("recordStamp").textContent = s.time + ", " + s.date;
    $("recordKicker").textContent = parent ? "Response" : "New record";

    // Written from inside a community, channel, project or task, a record goes
    // straight in there. It is still yours: it appears in My Intelligence too.
    var into = (!parent && scope === "collective") ? here() : null;
    writingInto = into;

    var ans = $("answering");
    if (parent) {
      ans.hidden = false;
      ans.textContent = "Responding to " + parent.author + " — " + (parent.title || parent.fn);
    } else if (into) {
      ans.hidden = false;
      ans.textContent = "Going into " + into.name + ", and into your My Intelligence.";
    } else {
      ans.hidden = true;
    }

    // A file can be chosen while writing, but only in My Intelligence
    // and only for a new record — a response goes where its parent already is.
    var pick = $("f-place");
    pick.textContent = "";
    var offer = !parent && scope === "personal" && folders.length;
    $("placeField").hidden = !offer;
    if (offer) {
      $("placeLabel").textContent = "File (optional)";
      var none = document.createElement("option");
      none.value = "";
      none.textContent = "— none —";
      pick.appendChild(none);
      folders.forEach(function (pl) {
        var o = document.createElement("option");
        o.value = pl.id;
        o.textContent = pl.name;
        pick.appendChild(o);
      });
      pick.value = placeFilter || "";
    }

    $("recordDialog").showModal();
    setTimeout(function () { $("f-title").focus(); }, 30);
  }

  function readB64(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result).split(",")[1] || ""); };
      r.onerror = function () { reject(new Error("That file could not be read.")); };
      r.readAsDataURL(file);
    });
  }

  $("recordForm").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!user) { $("recordMsg").textContent = "Choose a name first."; return; }

    var fn = sel.value === "Other..." ? $("f-fn-other").value.trim() : sel.value;
    if (!fn) { $("recordMsg").textContent = "Name the function, or pick one from the list."; return; }

    var payload = {
      userId: user.id,
      fn: fn,
      title: $("f-title").value.trim(),   // optional
      replyTo: replyTo ? replyTo.id : ""
    };

    if (!$("placeField").hidden && $("f-place").value) {
      payload.folderId = $("f-place").value;
    }

    if (writingInto) payload.groupId = writingInto.id;

    // Read every row of the builder. Empty rows are simply ignored.
    var rows = [].slice.call($("pieces").querySelectorAll(".piece"));
    var jobs = [];
    var problem = "";

    rows.forEach(function (rowEl) {
      var k = rowEl.dataset.kind;
      var input = rowEl.querySelector(".piece-input");

      if (k === "link") {
        var url = input.value.trim();
        if (url) jobs.push(Promise.resolve({ kind: "link", url: url }));
      } else if (k === "text") {
        if (input.value.trim()) jobs.push(Promise.resolve({ kind: "text", text: input.value }));
      } else {
        var f = input.files[0];
        if (!f) return;
        if (f.size > MAX_FILE) {
          problem = f.name + " is " + bytes(f.size) + ". The limit is 25 MB — link it instead.";
          return;
        }
        jobs.push(readB64(f).then(function (b64) {
          return { kind: "file",
                   file: { name: f.name, mime: f.type || "application/octet-stream", b64: b64 } };
        }));
      }
    });

    if (problem) { $("recordMsg").textContent = problem; return; }
    if (!jobs.length) {
      $("recordMsg").textContent = "Add at least one link, file or note.";
      return;
    }

    $("recordSubmit").disabled = true;
    $("recordMsg").textContent = "Adding...";

    Promise.all(jobs)
      .then(function (built) {
        payload.pieces = built;
        return api("/api/entries", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
      })
      .then(function () {
        $("recordSubmit").disabled = false;
        $("recordMsg").textContent = "";
        $("recordDialog").close();
        replyTo = null;
        writingInto = null;
        return refresh();
      })
      .catch(function (err) {
        $("recordSubmit").disabled = false;
        $("recordMsg").textContent = err.message;
      });
  });

  /* ------------------------------------------------------------- boot -- */

  // The build number is off the page entirely now. It still prints in the
  // console window and answers at /api/version, which is where to look if a
  // change ever seems not to have arrived.
  $("helpBtn").addEventListener("click", function () { $("helpDialog").showModal(); });
  $("helpClose").addEventListener("click", function () { $("helpDialog").close(); });

  // Ask the server who this browser is signed in as. Only if nobody, ask.
  paintIdentity();
  api("/api/me")
    .then(function (me) {
      if (typeof me.operator === "string") GLOBAL_FOUNDER = me.operator;
      signedIn(me.user ? { id: me.user.id, name: me.user.name } : null);
      if (!user) openGate();
    })
    .catch(function () { openGate(); });
})();
</script>
</body>
</html>
"""


def page_for(conn):
    """The page, with the operator's name written into its script. The name
    can be anything somebody typed, so it goes in as a JSON string with < made
    harmless -- a name like </script> must stay a name."""
    name = json.dumps(operator_name(conn)).replace("<", "\\u003c")
    return PAGE.replace("__GLOBAL_FOUNDER__", name)



# ===========================================================================
# DATABASE
# ===========================================================================

def connect():
    """A connection for the current thread. SQLite wants one per thread."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def setup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA)

    # Upgrade a data folder written by an earlier version.
    for table, columns in LATER_COLUMNS.items():
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        for column, kind in columns:
            if column not in existing:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, kind))

    # Records used to sit in one group. Carry those into placements once.
    conn.execute(
        """INSERT OR IGNORE INTO placements (entry_id, group_id, created_at)
           SELECT id, group_id, created_at FROM entries
           WHERE group_id IS NOT NULL AND group_id <> ''""")

    # A record used to carry exactly one thing. Turn each into its first
    # attachment. The attachment keeps the record's own id, so files already
    # written to data/uploads/<record id>/ are still found where they are.
    #
    # Only for records that have no attachments at all. Every record written
    # since attachments arrived still carries a legacy entries.kind of 'text',
    # so without this guard each upgrade would staple an empty note onto every
    # record in the file.
    conn.execute(
        """INSERT OR IGNORE INTO attachments
             (id, entry_id, position, kind, url, body, file_name, file_mime,
              file_size, created_at)
           SELECT e.id, e.id, 0, e.kind, e.url, e.body, e.file_name, e.file_mime,
                  e.file_size, e.created_at
           FROM entries e
           WHERE e.kind IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.entry_id = e.id)""")

    # Clean up any empty notes a previous upgrade stapled on, but only where
    # the record still has something real to show.
    conn.execute(
        """DELETE FROM attachments WHERE id IN (
             SELECT a.id FROM attachments a
             WHERE a.id = a.entry_id AND a.kind = 'text'
               AND (a.body IS NULL OR TRIM(a.body) = '')
               AND EXISTS (SELECT 1 FROM attachments o
                           WHERE o.entry_id = a.entry_id AND o.id <> a.id))""")

    # The very first version had no communities: sharing simply moved a record
    # into one Collective. Those records point at no community, so nothing
    # would show them. Put them in the oldest global community, which is the
    # only place they could have meant. If there is no global community at all
    # there is nowhere they belong, and they stay in their author's hands.
    conn.execute(
        """INSERT OR IGNORE INTO placements (entry_id, group_id, created_at)
           SELECT e.id,
                  (SELECT g.id FROM groupings g
                    WHERE IFNULL(g.reach, 'global') = 'global'
                      AND (g.parent_id IS NULL OR g.parent_id = '')
                    ORDER BY g.created_at ASC LIMIT 1),
                  e.created_at
             FROM entries e
            WHERE e.shared = 1
              AND NOT EXISTS (SELECT 1 FROM placements p WHERE p.entry_id = e.id)
              AND EXISTS (SELECT 1 FROM groupings g
                           WHERE IFNULL(g.reach, 'global') = 'global'
                             AND (g.parent_id IS NULL OR g.parent_id = ''))""")

    # Communities that predate the My / Global split were visible to everyone.
    conn.execute("UPDATE groupings SET reach = 'global' WHERE reach IS NULL OR reach = ''")

    # Before contributor lists existed, anyone could share into a global
    # community and a personal one was the creator's alone. Keep both true.
    conn.execute("UPDATE groupings SET contribute = CASE "
                 "WHEN reach IN ('global', 'news') THEN 'open' ELSE 'invite' END "
                 "WHERE contribute IS NULL OR contribute = ''")

    # Viewing arrived after contributing. A global community was visible to
    # everyone; a personal one was its owner's alone.
    conn.execute("UPDATE groupings SET viewing = CASE "
                 "WHEN reach IN ('global', 'news') THEN 'open' ELSE 'invite' END "
                 "WHERE viewing IS NULL OR viewing = ''")

    # Everyone already listed was listed in order to contribute.
    conn.execute("UPDATE members SET role = 'contribute' WHERE role IS NULL OR role = ''")

    # Deliberately the plain journal, not WAL. Once a record is written, the
    # whole database is one file with nothing alongside it, so the data folder
    # can be copied or zipped at any moment and arrive complete.
    problem = ensure_operator(conn)
    METER.load(conn)

    conn.execute("PRAGMA journal_mode = DELETE")
    conn.commit()
    conn.close()
    return problem


def piece_to_json(a):
    file_url = ""
    if a["kind"] == "file" and a["file_name"]:
        file_url = "/files/{}/{}".format(a["id"], a["file_name"])
    return {
        "id": a["id"],
        "kind": a["kind"],
        "url": a["url"] or "",
        "text": a["body"] or "",
        "fileName": a["file_name"] or "",
        "fileMime": a["file_mime"] or "",
        "fileSize": a["file_size"] or 0,
        "fileUrl": file_url,
    }


def row_to_entry(r, places=None, pieces=None):
    return {
        "id": r["id"],
        "createdAt": r["created_at"],
        "userId": r["user_id"],
        "author": r["author"],
        "fn": r["fn"],
        "title": r["title"] or "",
        "shared": bool(r["shared"]),
        "replyTo": r["reply_to"] or "",
        "folderId": r["folder_id"] or "",
        "places": places or [],    # every community / project / task it sits in
        "pieces": pieces or [],    # the links, files and notes it carries
        "editedAt": (r["edited_at"] if "edited_at" in r.keys() else None) or "",
    }


# ===========================================================================
# HELPERS
# ===========================================================================

def like_escape(text):
    """So a name containing % or _ searches for itself, not for anything."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def clean(value, limit):
    return ("" if value is None else str(value)).strip()[:limit]


def safe_name(name):
    """Strip anything that could climb out of the uploads folder."""
    base = os.path.basename(str(name or "file")).replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip(".")
    return (cleaned or "file")[:120]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def root_grouping(conn, group_id):
    """Walk up to the top-level community a grouping belongs to. Guards against
    a cycle, which the create path forbids but a hand-edited file could hold."""
    seen = set()
    current = group_id
    while current and current not in seen:
        seen.add(current)
        row = conn.execute("SELECT parent_id FROM groupings WHERE id = ?", (current,)).fetchone()
        if row is None or not row["parent_id"]:
            return current
        current = row["parent_id"]
    return group_id


def founder_of(conn, group_id):
    """Who started the tree this grouping belongs to. Sub-communities are the
    founder's to arrange; everyone else contributes into what exists."""
    root = root_grouping(conn, group_id)
    row = conn.execute("SELECT created_by FROM groupings WHERE id = ?", (root,)).fetchone()
    return row["created_by"] if row else ""


def ancestry(conn, group_id):
    """This grouping and every community above it, nearest first."""
    chain = []
    seen = set()
    current = group_id
    while current and current not in seen:
        seen.add(current)
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (current,)).fetchone()
        if row is None:
            break
        chain.append(row)
        current = row["parent_id"]
    return chain


def granted(conn, group_id, user_id, want):
    """Access reaches downward. Being named on Metastasis covers Metastasis and
    everything inside it; it says nothing about Cancer Research above it. So the
    coarsest community you are named on is as far up as you can go."""
    # Without a name you may look at what is open to everybody -- the
    # "Just view" door -- but never put anything in.
    if not user_id and want == "contribute":
        return False

    for node in ancestry(conn, group_id):
        if user_id and node["created_by"] == user_id:
            return True

        mode = (node["contribute"] if want == "contribute" else node["viewing"]) or "invite"
        if mode == "open":
            return True

        if not user_id:
            continue
        row = conn.execute("SELECT role FROM members WHERE group_id = ? AND user_id = ?",
                           (node["id"], user_id)).fetchone()
        if row:
            role = row["role"] or "contribute"
            if want == "view" or role == "contribute":
                return True

    return False


def place_is_up(conn, group_id):
    """False if the operator took this place, or anything above it, down."""
    return not any(node["deleted_at"] for node in ancestry(conn, group_id))


def may_read_place(conn, group_id, user_id):
    """May this person read what is inside this place? The operator may read
    everything, so that they can find what needs taking down."""
    if may_operate(conn, user_id):
        return True
    return place_is_up(conn, group_id) and may_view(conn, group_id, user_id)


def may_contribute(conn, group_id, user_id):
    """Can this person put a record, project or task into this community?"""
    return granted(conn, group_id, user_id, "contribute")


def may_view(conn, group_id, user_id):
    """Anyone who can contribute can obviously also look."""
    return granted(conn, group_id, user_id, "view") or granted(conn, group_id, user_id, "contribute")


def operator_name(conn):
    """Who the operator is in this copy: the GLOBAL_FOUNDER line if it names
    someone, otherwise the first name ever added here. Empty until then.
    On the internet there is no 'first name': a stranger could be first. There
    the operator is the host's OPERATOR setting, or nobody at all."""
    if PUBLIC:
        row = conn.execute("SELECT name FROM users WHERE is_operator = 1 "
                           "ORDER BY created_at LIMIT 1").fetchone()
        return row["name"] if row else ""
    if GLOBAL_FOUNDER.strip():
        return GLOBAL_FOUNDER.strip()
    row = conn.execute("SELECT name FROM users "
                       "ORDER BY created_at ASC, rowid ASC LIMIT 1").fetchone()
    return (row["name"] or "").strip() if row else ""


def is_global_founder(conn, user_id):
    """Only one person may start a global community for now. A name, because a
    name is all identity is here yet."""
    if not user_id:
        return False
    row = conn.execute("SELECT name, is_operator FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    if row is None:
        return False
    if PUBLIC:
        return bool(row["is_operator"])
    boss = operator_name(conn).lower()
    return bool(boss) and (row["name"] or "").strip().lower() == boss


def may_operate(conn, user_id):
    """The one person who may edit or take down anything, anywhere. Same name
    as founds the permanent sections, because for now they are one role."""
    return is_global_founder(conn, user_id)


def log_edit(conn, target, target_id, action, field, was, now_value, user_id, name):
    """Write down what changed and what it said before. Nothing here destroys
    what was written; this table is what makes that claim true of edits too."""
    conn.execute(
        "INSERT INTO edits (id, target, target_id, action, field, was, now, "
        "                   by_user, by_name, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), target, target_id, action, field,
         None if was is None else str(was),
         None if now_value is None else str(now_value),
         user_id, name, now_iso()))


def feed_hides(conn, user_id):
    """Communities and channels this person has taken off their own list."""
    if not user_id:
        return set()
    return {r["group_id"] for r in
            conn.execute("SELECT group_id FROM feed_hidden WHERE user_id = ?", (user_id,))}


def governs(conn, group_id, user_id):
    """Whoever founded this community, or any community above it, may say who
    views it and who contributes to it."""
    if not user_id:
        return False
    return any(node["created_by"] == user_id for node in ancestry(conn, group_id))


def reward_total(conn, group_id):
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS offers "
                       "FROM rewards WHERE group_id = ?", (group_id,)).fetchone()
    return {"total": row["total"] or 0, "offers": row["offers"] or 0}


def inside(directory, path):
    directory = os.path.realpath(directory)
    path = os.path.realpath(path)
    return path == directory or path.startswith(directory + os.sep)


# ---------------------------------------------------------------- sign-in --

def hash_password(password):
    """A slow, salted, one-way hash. Standard library only."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (HASH_ROUNDS, salt.hex(), digest.hex())


def password_matches(password, stored):
    try:
        scheme, rounds, salt, digest = (stored or "").split("$")
        if scheme != "pbkdf2_sha256":
            return False
        mine = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                   bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(mine.hex(), digest)
    except (ValueError, TypeError):
        return False


def key_hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def start_session(conn, user_id):
    """Make a new sign-in key for this person. Returns the key itself, which
    goes to the browser and is never stored here."""
    key = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO sessions (key_hash, user_id, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?)",
                 (key_hash(key), user_id, now_iso(),
                  (now + timedelta(days=SESSION_DAYS)).isoformat()))
    # Old, expired keys are tidied away whenever somebody signs in.
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    return key


def session_user(conn, key):
    """The user a sign-in key belongs to, or None."""
    if not key or len(key) > 200:
        return None
    row = conn.execute(
        "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.key_hash = ? AND s.expires_at > ?",
        (key_hash(key), datetime.now(timezone.utc).isoformat())).fetchone()
    return row


class Limiter:
    """Counts what each address does inside a sliding window, so one script
    cannot fill the disk or guess passwords all day. Kept in memory: a
    restart forgets, which is fine -- it only has to slow a flood down.

    When it has too much to remember it forgets the least active entries
    first, never everything at once -- so a flood of junk cannot wipe the
    count against an address that is busy guessing a password."""

    CAP = 100000

    def __init__(self):
        self.lock = threading.Lock()
        self.seen = {}          # (bucket, who) -> [window seconds, [(time, cost), ...]]

    def _tidy(self, now):
        for key in [k for k, (window, hits) in self.seen.items()
                    if not hits or now - hits[-1][0] >= window]:
            del self.seen[key]
        if len(self.seen) > self.CAP:
            # Forget the least active first: an address one hit in is
            # cheap to forget, one close to its limit is the one that matters.
            quietest = sorted(self.seen, key=lambda k: (sum(c for _, c in self.seen[k][1]),
                                                        self.seen[k][1][-1][0]))
            for key in quietest[:len(quietest) // 5]:
                del self.seen[key]

    def allow(self, bucket, who, limit, seconds, cost=1):
        now = time.monotonic()
        with self.lock:
            if len(self.seen) > self.CAP:
                self._tidy(now)
            window, hits = self.seen.get((bucket, who), [seconds, []])
            hits = [(t, c) for (t, c) in hits if now - t < seconds]
            if sum(c for _, c in hits) + cost > limit:
                self.seen[(bucket, who)] = [seconds, hits]
                return False
            hits.append((now, cost))
            self.seen[(bucket, who)] = [seconds, hits]
            return True


LIMITS = Limiter()


class Meter:
    """Counts every byte the site sends, month by month, and says when the
    month's allowance is used up. Saved to the database every few megabytes
    so a restart does not reset the count."""

    SAVE_EVERY = 2 * 1024 * 1024

    def __init__(self):
        self.lock = threading.Lock()
        self.month = ""
        self.bytes = 0
        self.unsaved = 0
        self.saved_at = time.monotonic()

    @staticmethod
    def this_month():
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def load(self, conn):
        self.month = self.this_month()
        row = conn.execute("SELECT bytes FROM usage WHERE month = ?", (self.month,)).fetchone()
        self.bytes = row["bytes"] if row else 0

    def _save(self):
        conn = connect()
        conn.execute("INSERT OR REPLACE INTO usage (month, bytes) VALUES (?, ?)",
                     (self.month, self.bytes))
        conn.commit()
        conn.close()
        self.unsaved = 0
        self.saved_at = time.monotonic()

    def flush(self):
        with self.lock:
            if self.unsaved and self.month:
                self._save()

    def add(self, count):
        with self.lock:
            month = self.this_month()
            if month != self.month:               # a new month starts from nothing
                if self.unsaved:
                    self._save()
                self.month, self.bytes, self.unsaved = month, 0, 0
            self.bytes += count
            self.unsaved += count
            if self.unsaved >= self.SAVE_EVERY or time.monotonic() - self.saved_at > 30:
                self._save()

    def used_up(self):
        if BANDWIDTH_GB <= 0:
            return False
        with self.lock:
            if self.this_month() != self.month:
                return False
            return self.bytes >= BANDWIDTH_GB * 1024 ** 3


METER = Meter()

PAUSED_PAGE = (b"<!doctype html><meta charset=utf-8><title>Cognaut</title>"
               b"<body style='font:15px Georgia,serif;max-width:34em;margin:20vh auto;padding:0 1em'>"
               b"<h1 style='font-weight:700'>Cognaut is resting</h1>"
               b"<p>It has used this month's allowance of traffic, so it is paused until the "
               b"1st of next month. Nothing has been lost.</p>")

# Per visitor: how many bytes of uploaded files they may download in an hour.
DOWNLOAD_PER_HOUR = 300 * 1024 * 1024

# (how many, per how many seconds). Generous for a person, tight for a script.
RATE = {
    "write":   (120, 60),                     # any change, per minute
    "signin":  (20, 300),                     # password attempts, per 5 minutes
    "newname": (20, 3600),                    # new accounts, per hour
    "upload":  (200 * 1024 * 1024, 3600),     # bytes of files, per hour
}


def ensure_operator(conn):
    """On a host, make the operator's account, with its password, before the
    site takes a single visitor -- so nobody else can register that name
    first. The account is marked, and only a marked account is the operator:
    a name alone never is. Returns a reason it could not, or ""."""
    if not PUBLIC:
        return ""
    name = GLOBAL_FOUNDER.strip()
    first = os.environ.get("OPERATOR_PASSWORD", "")
    if not name:
        return "OPERATOR is not set. Set it to your name in the host's settings."
    row = conn.execute("SELECT * FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
    if row is not None and row["is_operator"]:
        return ""                                   # made on an earlier start
    if len(first) < MIN_PASSWORD:
        return ("OPERATOR_PASSWORD is missing or shorter than %d characters."
                % MIN_PASSWORD)
    if row is None:
        conn.execute("INSERT INTO users (id, name, name_key, created_at, pass_hash, "
                     "is_operator) VALUES (?, ?, ?, ?, ?, 1)",
                     (str(uuid.uuid4()), name, name.lower(), now_iso(), hash_password(first)))
        return ""
    if row["pass_hash"]:
        # Somebody already signed up with this name on this site, with their
        # own password. They are not made operator by sharing a name.
        return ("Someone already has an account called %r here. Choose a different "
                "OPERATOR name." % name)
    # A name carried over from before passwords: claim it for the operator.
    conn.execute("UPDATE users SET pass_hash = ?, is_operator = 1 WHERE id = ?",
                 (hash_password(first), row["id"]))
    return ""


# ===========================================================================
# SERVER
# ===========================================================================

class SiteServer(ThreadingHTTPServer):
    """The standard threaded server, with a ceiling on how many visitors are
    served at once. Past it, new connections are turned away rather than
    each given a thread until memory runs out."""

    daemon_threads = True
    MAX_AT_ONCE = 64

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.MAX_AT_ONCE)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(timeout=5):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


# Only two large uploads are read into memory at a time, so a crowd of big
# uploads arriving together waits its turn instead of exhausting memory.
BIG_BODIES = threading.BoundedSemaphore(2)
BIG_BODY = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "Cognaut/0.4"
    # A connection that sends nothing for this long is dropped, so a slow
    # trickle of half-requests cannot tie the site up.
    timeout = 30

    def log_message(self, fmt, *args):
        code = str(args[1]) if len(args) > 1 else ""
        if not code.startswith(("2", "3")):
            sys.stderr.write("  %s %s\n" % (self.client_ip(), fmt % args))

    # -- who is asking ---------------------------------------------------

    def client_ip(self):
        """The visitor's real address. On a host every request arrives through
        the host's front door, so the connection itself shows only the door.
        Each host writes the real address into one header that a visitor
        cannot forge: Render's comes from Cloudflare (True-Client-IP), and
        Railway overwrites X-Real-IP. X-Forwarded-For is never trusted -- a
        visitor can put anything there. At home there is no front door, so
        no header is believed at all."""
        if PUBLIC and CLIENT_IP_HEADER:
            value = (self.headers.get(CLIENT_IP_HEADER) or "").strip()
            if value:
                return value[:64]
        return self.client_address[0]

    def sign_in_key(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:
            return ""
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def who(self):
        """The signed-in user's row, or None. Worked out from the sign-in
        cookie and nothing else: whatever id the page sends is ignored."""
        if not hasattr(self, "_who"):
            key = self.sign_in_key()
            self._who = None
            if key:
                conn = connect()
                self._who = session_user(conn, key)
                conn.close()
        return self._who

    def who_id(self):
        row = self.who()
        return row["id"] if row else ""

    def query(self, parsed):
        """The query string, with userId replaced by whoever is signed in."""
        q = parse_qs(parsed.query)
        q["userId"] = [self.who_id()]
        return q

    # -- replies ---------------------------------------------------------

    def no_cache(self, keep=False):
        """Never let a browser reuse an older copy of this site. Without this
        a change to the code can sit on disk while the tab keeps showing what
        it downloaded last time. The page itself may be KEPT, but only on the
        condition that the browser asks every time whether it changed -- so
        an update still arrives at once, and an unchanged page costs almost
        nothing to confirm."""
        if keep:
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        # Plain safety for every reply: never guess a file's type, never be
        # framed by another site, never tell other sites which page linked them.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")

    def cookie_header(self, key, max_age):
        parts = ["%s=%s" % (SESSION_COOKIE, key), "Path=/", "HttpOnly",
                 "SameSite=Lax", "Max-Age=%d" % max_age]
        if PUBLIC:
            parts.append("Secure")
        return "; ".join(parts)

    def squeeze(self, body, mime):
        """Compress text before sending it, when the browser accepts that.
        Pages and lists shrink to about a quarter, which is a quarter of the
        traffic the host counts. Pictures and PDFs are compressed already."""
        if (len(body) < 1024 or len(body) > 8 * 1024 * 1024
                or "gzip" not in (self.headers.get("Accept-Encoding") or "")):
            return body, False
        if not (mime.startswith("text/") or mime.startswith("application/json")
                or mime.startswith("image/svg")):
            return body, False
        return gzip.compress(body, 6), True

    def send_json(self, status, payload, cookie=None, extra=None):
        body, squeezed = self.squeeze(json.dumps(payload).encode("utf-8"), "application/json")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if squeezed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.no_cache()
        for name, value in (extra or []):
            self.send_header(name, value)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)
        METER.add(len(body) + 400)          # 400: a fair allowance for the headers

    def fail(self, status, message):
        self.send_json(status, {"error": message})

    def send_bytes(self, body, mime, download_as=None, extra=None, status=200, keep=False):
        body, squeezed = self.squeeze(body, mime)
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        if squeezed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.no_cache(keep)
        for name, value in (extra or []):
            self.send_header(name, value)
        if download_as:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % download_as)
        self.end_headers()
        self.wfile.write(body)
        METER.add(len(body) + 400)

    def paused(self, path):
        """The month's traffic is used up: say so in as few bytes as possible."""
        if path in ("/", "", "/index.html"):
            self.send_bytes(PAUSED_PAGE, "text/html; charset=utf-8", status=503)
        else:
            self.send_json(503, {"error": "Cognaut is paused until the 1st of next month."})

    def read_json(self):
        """Always drain the body before replying, or the browser sees a reset.
        Whatever userId the page put in the body is replaced by whoever is
        actually signed in, so no handler below can be fooled by it."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length < 0 or length > MAX_BODY_BYTES:
            return None
        if length > BIG_BODY:
            if not BIG_BODIES.acquire(timeout=60):
                return None
            try:
                raw = self.rfile.read(length)
            finally:
                BIG_BODIES.release()
        else:
            raw = self.rfile.read(length) if length else b""
        payload = {}
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
            if not isinstance(payload, dict):
                return None
        payload["userId"] = self.who_id()
        return payload

    # -- GET -------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if METER.used_up():
            self.paused(path)
            return

        if path in ("/", "", "/index.html"):
            conn = connect()
            page = page_for(conn).encode("utf-8")
            conn.close()
            # The browser keeps the page and asks each time whether it has
            # changed. Unchanged, the answer is a few hundred bytes instead of
            # the whole page -- and a new build is still picked up at once.
            tag = '"%s"' % hashlib.sha256(page).hexdigest()[:24]
            if self.headers.get("If-None-Match") == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                METER.add(300)
                return
            self.send_bytes(page, "text/html; charset=utf-8",
                            extra=[("ETag", tag)], keep=True)
            return

        if path == "/api/users":
            # At home the name box offers everyone in this copy. On the
            # internet it does not: a public list of every name is a list of
            # accounts to guess passwords for.
            if PUBLIC:
                self.send_json(200, [])
                return
            conn = connect()
            rows = conn.execute("SELECT id, name FROM users ORDER BY name COLLATE NOCASE ASC").fetchall()
            conn.close()
            self.send_json(200, [{"id": r["id"], "name": r["name"]} for r in rows])
            return

        if path == "/api/me":
            # Who this browser is signed in as, and who the operator is.
            me = self.who()
            conn = connect()
            boss = operator_name(conn)
            conn.close()
            self.send_json(200, {"user": {"id": me["id"], "name": me["name"]} if me else None,
                                 "operator": boss})
            return

        if path == "/api/version":
            about = {"version": VERSION, "built": BUILD_DATE}
            if not PUBLIC:
                about["folder"] = HERE        # where it runs from: useful at home only
            self.send_json(200, about)
            return

        if path == "/api/folders":
            user_id = self.who_id()
            if not UUID_RE.match(user_id):
                self.send_json(200, [])
                return
            conn = connect()
            rows = conn.execute(
                "SELECT id, name FROM folders WHERE user_id = ? ORDER BY name COLLATE NOCASE ASC",
                (user_id,)).fetchall()
            conn.close()
            self.send_json(200, [{"id": r["id"], "name": r["name"]} for r in rows])
            return

        if path == "/api/groupings":
            # No parent = the communities. A parent = that community's
            # projects and tasks.
            q = self.query(parsed)
            parent = (q.get("parent") or [""])[0]
            reach = (q.get("reach") or [""])[0]
            owner = (q.get("userId") or [""])[0]
            look = clean((q.get("q") or [""])[0], 120)
            if not UUID_RE.match(owner):
                owner = ""

            conn = connect()
            hidden = feed_hides(conn, owner)

            if look and reach in ("global", "news"):
                # Search a whole section, at any depth, and say where each hit
                # lives so pressing it can walk you there.
                rows = conn.execute(
                    "SELECT * FROM groupings WHERE reach = ? AND deleted_at IS NULL "
                    "AND name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "ORDER BY name COLLATE NOCASE LIMIT 200",
                    (reach, "%" + like_escape(look) + "%")).fetchall()
                rows = [r for r in rows if may_view(conn, r["id"], owner)]
                found = []
                for r in rows:
                    chain = [n for n in ancestry(conn, r["id"])][::-1]
                    if any(n["deleted_at"] for n in chain):
                        continue
                    found.append({
                        "id": r["id"], "kind": r["kind"], "name": r["name"],
                        "parentId": r["parent_id"] or "",
                        "reach": r["reach"] or "global",
                        "viewing": r["viewing"] or "invite",
                        "contribute": r["contribute"] or "invite",
                        "founder": founder_of(conn, r["id"]),
                        "isFounder": governs(conn, r["id"], owner) if owner else False,
                        "isOwner": r["created_by"] == owner if owner else False,
                        "canContribute": may_contribute(conn, r["id"], owner),
                        "path": [{"id": n["id"], "kind": n["kind"], "name": n["name"]}
                                 for n in chain],
                    })
                conn.close()
                self.send_json(200, found)
                return

            if parent:
                if not UUID_RE.match(parent) or not place_is_up(conn, parent):
                    conn.close()
                    self.send_json(200, [])
                    return
                rows = conn.execute(
                    "SELECT * FROM groupings WHERE parent_id = ? AND deleted_at IS NULL "
                    "ORDER BY kind COLLATE NOCASE, name COLLATE NOCASE", (parent,)).fetchall()
                rows = [r for r in rows if may_view(conn, r["id"], owner)]

            elif reach in ("mine", "mynews", "network"):
                # Your network: every root of your own, plus everything you have
                # been named on, at whatever depth it sits. A community you were
                # given halfway down a tree stands on its own here, because that
                # is as far up as your access goes. "mine" is the communities
                # half, "mynews" the channels half, "network" both together.
                if not owner:
                    conn.close()
                    self.send_json(200, [])
                    return
                if reach == "network":
                    want = list(HOLDERS)
                else:
                    want = ["Channel" if reach == "mynews" else "Community"]
                marks = ",".join("?" * len(want))
                rows = conn.execute(
                    "SELECT * FROM groupings WHERE (parent_id IS NULL OR parent_id = '') "
                    "AND created_by = ? AND IFNULL(reach, 'global') = 'mine' "
                    "AND deleted_at IS NULL "
                    "AND kind IN (%s) ORDER BY name COLLATE NOCASE" % marks,
                    [owner] + want).fetchall()
                joined = conn.execute(
                    "SELECT g.* FROM groupings g JOIN members m ON m.group_id = g.id "
                    "WHERE m.user_id = ? AND g.kind IN (%s) AND g.created_by <> ? "
                    "AND g.deleted_at IS NULL "
                    "ORDER BY g.name COLLATE NOCASE" % marks,
                    [owner] + want + [owner]).fetchall()
                # What you have taken off your own list stays off it. Nobody
                # else's view changes, and Browse offers it back.
                rows = [r for r in list(rows) + list(joined) if r["id"] not in hidden]

            elif reach in ("browse", "browsenews"):
                # Ones somebody else founded that are open to you but that you
                # have not taken onto your own list yet.
                if not owner:
                    conn.close()
                    self.send_json(200, [])
                    return
                want = "Channel" if reach == "browsenews" else "Community"
                rows = conn.execute(
                    "SELECT g.* FROM groupings g WHERE g.kind = ? AND g.deleted_at IS NULL "
                    "AND ((g.created_by <> ? "
                    "      AND (IFNULL(g.contribute, 'invite') = 'open' "
                    "           OR IFNULL(g.viewing, 'invite') = 'open') "
                    "      AND NOT EXISTS (SELECT 1 FROM members m WHERE m.group_id = g.id "
                    "                      AND m.user_id = ?)) "
                    "     OR EXISTS (SELECT 1 FROM feed_hidden h WHERE h.group_id = g.id "
                    "                AND h.user_id = ?)) "
                    "ORDER BY g.name COLLATE NOCASE",
                    (want, owner, owner, owner)).fetchall()
                # Only the coarsest one in a branch: joining that covers
                # everything below it, so offering the children is noise. One
                # you took off your own list is always offered back, whatever
                # sits above it.
                rows = [r for r in rows
                        if r["id"] in hidden
                        or not (r["parent_id"] and may_view(conn, r["parent_id"], owner))]

            elif reach in ("global", "news"):
                rows = conn.execute(
                    "SELECT * FROM groupings WHERE (parent_id IS NULL OR parent_id = '') "
                    "AND reach = ? AND deleted_at IS NULL ORDER BY name COLLATE NOCASE",
                    (reach,)).fetchall()
                rows = [r for r in rows if may_view(conn, r["id"], owner)]

            else:
                # Everywhere this person may put something.
                rows = conn.execute(
                    "SELECT * FROM groupings WHERE (parent_id IS NULL OR parent_id = '') "
                    "AND deleted_at IS NULL ORDER BY name COLLATE NOCASE").fetchall()
                rows = [r for r in rows if may_contribute(conn, r["id"], owner)]

            out = []
            for r in rows:
                founder = founder_of(conn, r["id"])
                item = {
                    "id": r["id"], "kind": r["kind"], "name": r["name"],
                    "parentId": r["parent_id"] or "",
                    "reach": r["reach"] or "global",
                    "viewing": r["viewing"] or "invite",
                    "contribute": r["contribute"] or "invite",
                    "founder": founder,
                    "isFounder": governs(conn, r["id"], owner) if owner else False,
                    "isOwner": r["created_by"] == owner if owner else False,
                    "canContribute": may_contribute(conn, r["id"], owner),
                }
                if r["kind"] != "Community":
                    item["reward"] = reward_total(conn, r["id"])
                out.append(item)
            conn.close()
            self.send_json(200, out)
            return

        access = re.match(r"^/api/groupings/([a-f0-9-]{36})/access$", path, re.I)
        if access:
            self.read_access(access.group(1), self.query(parsed))
            return

        purse = re.match(r"^/api/groupings/([a-f0-9-]{36})/rewards$", path, re.I)
        if purse:
            self.read_rewards(purse.group(1), self.who_id())
            return

        if path == "/api/entries":
            self.list_entries(self.query(parsed))
            return

        if path.startswith("/files/"):
            self.serve_upload(path, parsed.query)
            return

        self.fail(404, "Not found.")

    def read_access(self, group_id, query):
        """Who can see this community, who can put things in it, and may the
        asker change either. Both settings belong to THIS community, not to
        the top of its tree: being let into Metastasis lets you into
        Metastasis and everything below it, and nothing above it."""
        viewer = (query.get("userId") or [""])[0]
        if not UUID_RE.match(viewer):
            viewer = ""

        conn = connect()
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That community does not exist.")
            return

        rows = conn.execute("SELECT user_id, role FROM members WHERE group_id = ?",
                            (group_id,)).fetchall()
        viewers = [m["user_id"] for m in rows]
        writers = [m["user_id"] for m in rows if (m["role"] or "contribute") == "contribute"]

        # At home the dialog lists everyone in this copy to tick. On the
        # internet it lists only who is already let in -- a list of every
        # account would be handed to anyone who founds a community -- and
        # others are added by typing their exact name.
        if PUBLIC:
            listed = conn.execute(
                "SELECT u.id, u.name FROM users u JOIN members m ON m.user_id = u.id "
                "WHERE m.group_id = ? ORDER BY u.name COLLATE NOCASE", (group_id,))
        else:
            listed = conn.execute("SELECT id, name FROM users ORDER BY name COLLATE NOCASE")
        everyone = [{"id": u["id"], "name": u["name"]} for u in listed]
        manage = bool(viewer) and governs(conn, group_id, viewer)
        if not manage:
            # Who has been let in is the founder's business, not everyone's.
            conn.close()
            self.fail(403, "Only the person who founded this can see who it is open to.")
            return
        conn.close()

        self.send_json(200, {
            "groupId": group_id,
            "name": row["name"],
            "contribute": row["contribute"] or "invite",
            "viewing": row["viewing"] or ("open" if row["reach"] == "global" else "invite"),
            "contributeIds": writers,
            "viewIds": viewers,
            "users": everyone,
            "canManage": manage,
        })

    def write_access(self, group_id):
        """Set one of the two settings. The other is left exactly as it was."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)
        kind = clean(payload.get("kind"), 20) or "contribute"
        if kind not in ("contribute", "view"):
            self.fail(400, "There are two settings: who can view, and who can contribute.")
            return

        conn = connect()
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That community does not exist.")
            return

        if not (UUID_RE.match(user_id) and governs(conn, group_id, user_id)):
            conn.close()
            self.fail(403, "Only the person who founded a community can say who "
                           "may view it or contribute to it.")
            return

        mode = clean(payload.get("mode"), 10) or clean(payload.get("contribute"), 10)
        if mode not in ("open", "invite"):
            conn.close()
            self.fail(400, "A community is open to everybody, or to named people.")
            return

        wanted = payload.get("memberIds")
        wanted = [clean(m, 40) for m in wanted[:200]] if isinstance(wanted, list) else []
        wanted = [m for m in wanted if UUID_RE.match(m) and m != user_id]
        wanted = [m for m in wanted
                  if conn.execute("SELECT 1 FROM users WHERE id = ?", (m,)).fetchone()]

        # People added by typing their name. Every name must be exactly
        # someone's, or nothing is saved and the dialog says which was not.
        typed = payload.get("memberNames")
        for raw in (typed[:50] if isinstance(typed, list) else []):
            name = clean(raw, 120)
            if not name:
                continue
            found = conn.execute("SELECT id FROM users WHERE name_key = ?",
                                 (name.lower(),)).fetchone()
            if found is None:
                conn.close()
                self.fail(400, "Nobody here is called %s." % name)
                return
            if found["id"] != user_id and found["id"] not in wanted:
                wanted.append(found["id"])

        column = "contribute" if kind == "contribute" else "viewing"
        conn.execute("UPDATE groupings SET %s = ? WHERE id = ?" % column, (mode, group_id))

        current = {m["user_id"]: (m["role"] or "contribute") for m in
                   conn.execute("SELECT user_id, role FROM members WHERE group_id = ?",
                                (group_id,))}
        stamp = now_iso()

        if kind == "contribute":
            # Ticked here means contribute. Unticked means they keep whatever
            # viewing they had; take that away in the other dialog.
            for member in wanted:
                if member in current:
                    conn.execute("UPDATE members SET role = 'contribute' "
                                 "WHERE group_id = ? AND user_id = ?", (group_id, member))
                else:
                    conn.execute("INSERT INTO members (group_id, user_id, role, added_at) "
                                 "VALUES (?, ?, 'contribute', ?)", (group_id, member, stamp))
            for member, role in current.items():
                if role == "contribute" and member not in wanted:
                    conn.execute("UPDATE members SET role = 'view' "
                                 "WHERE group_id = ? AND user_id = ?", (group_id, member))
        else:
            # Taking viewing away takes contributing with it. You cannot put
            # something into a place you are not allowed to look at.
            for member in wanted:
                if member not in current:
                    conn.execute("INSERT INTO members (group_id, user_id, role, added_at) "
                                 "VALUES (?, ?, 'view', ?)", (group_id, member, stamp))
            for member in current:
                if member not in wanted:
                    conn.execute("DELETE FROM members WHERE group_id = ? AND user_id = ?",
                                 (group_id, member))

        conn.commit()
        rows = conn.execute("SELECT user_id, role FROM members WHERE group_id = ?",
                            (group_id,)).fetchall()
        conn.close()
        self.send_json(200, {
            "groupId": group_id,
            "mode": mode,
            "kind": kind,
            "contributeIds": [m["user_id"] for m in rows
                              if (m["role"] or "contribute") == "contribute"],
            "viewIds": [m["user_id"] for m in rows],
        })

    def join_grouping(self, group_id):
        """Take a community you are allowed into onto your own list. You join
        the community you clicked, and that reaches down into everything
        inside it — never up into whatever holds it."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)
        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name first.")
            return

        conn = connect()
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That community does not exist.")
            return
        if not may_view(conn, group_id, user_id) or not place_is_up(conn, group_id):
            conn.close()
            self.fail(403, "That community is not open to you.")
            return

        role = "contribute" if may_contribute(conn, group_id, user_id) else "view"
        conn.execute("INSERT OR IGNORE INTO members (group_id, user_id, role, added_at) "
                     "VALUES (?, ?, ?, ?)", (group_id, user_id, role, now_iso()))
        # Taking it back onto your list draws the curtain again.
        conn.execute("DELETE FROM feed_hidden WHERE user_id = ? AND group_id = ?",
                     (user_id, group_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"joined": True, "groupId": group_id, "role": role})

    def operator(self, conn, payload):
        """Returns the operator's user row, or None. The caller closes conn."""
        user_id = clean(payload.get("userId"), 40)
        if not UUID_RE.match(user_id):
            return None
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not may_operate(conn, user_id):
            return None
        return row

    def edit_entry(self, entry_id):
        """The operator may correct a record: its function, its title, and the
        text of any note or the address of any link on it. What it said before
        is copied into edits first, so nothing written is ever lost."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        conn = connect()
        who = self.operator(conn, payload)
        if who is None:
            boss = operator_name(conn) or "the operator"
            conn.close()
            self.fail(403, "Only %s can change a record." % boss)
            return

        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That record does not exist.")
            return

        stamp = now_iso()
        changed = 0

        fn = clean(payload.get("fn"), 60)
        if fn and fn != row["fn"]:
            log_edit(conn, "entry", entry_id, "edit", "fn", row["fn"], fn,
                     who["id"], who["name"])
            conn.execute("UPDATE entries SET fn = ? WHERE id = ?", (fn, entry_id))
            changed += 1

        if "title" in payload:
            title = clean(payload.get("title"), 300)
            if title != (row["title"] or ""):
                log_edit(conn, "entry", entry_id, "edit", "title", row["title"], title,
                         who["id"], who["name"])
                conn.execute("UPDATE entries SET title = ? WHERE id = ?", (title, entry_id))
                changed += 1

        # Only notes and links. A file is what it is; replacing one would be a
        # different record, so the operator takes the record down instead.
        for spec in (payload.get("pieces") or [])[:25]:
            if not isinstance(spec, dict):
                continue
            piece_id = clean(spec.get("id"), 40)
            if not UUID_RE.match(piece_id):
                continue
            piece = conn.execute(
                "SELECT * FROM attachments WHERE id = ? AND entry_id = ?",
                (piece_id, entry_id)).fetchone()
            if piece is None:
                continue

            if piece["kind"] == "text" and "text" in spec:
                body = ("" if spec.get("text") is None else str(spec["text"]))[:MAX_TEXT_CHARS]
                if not body.strip():
                    conn.close()
                    self.fail(400, "A note cannot be emptied. Take the record down instead.")
                    return
                if body != (piece["body"] or ""):
                    log_edit(conn, "entry", entry_id, "edit", "note", piece["body"], body,
                             who["id"], who["name"])
                    conn.execute("UPDATE attachments SET body = ? WHERE id = ?",
                                 (body, piece_id))
                    changed += 1

            elif piece["kind"] == "link" and "url" in spec:
                url = clean(spec.get("url"), 2000)
                if not URL_RE.match(url):
                    conn.close()
                    self.fail(400, "That is not a URL the ledger can open.")
                    return
                if url != (piece["url"] or ""):
                    log_edit(conn, "entry", entry_id, "edit", "link", piece["url"], url,
                             who["id"], who["name"])
                    conn.execute("UPDATE attachments SET url = ? WHERE id = ?", (url, piece_id))
                    changed += 1

        if changed:
            conn.execute("UPDATE entries SET edited_at = ? WHERE id = ?", (stamp, entry_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"edited": changed})

    def hide_entry(self, entry_id):
        """The operator takes a record down. The row stays and so does every
        response hanging off it; reading filters it out."""
        payload = self.read_json() or {}
        conn = connect()
        who = self.operator(conn, payload)
        if who is None:
            boss = operator_name(conn) or "the operator"
            conn.close()
            self.fail(403, "Only %s can take a record down." % boss)
            return

        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That record does not exist.")
            return

        back = clean(payload.get("restore"), 6) == "yes"
        if back:
            log_edit(conn, "entry", entry_id, "takedown", "restored",
                     row["hidden_at"], None, who["id"], who["name"])
            conn.execute("UPDATE entries SET hidden_at = NULL WHERE id = ?", (entry_id,))
        else:
            log_edit(conn, "entry", entry_id, "takedown", None,
                     row["title"] or row["fn"], None, who["id"], who["name"])
            conn.execute("UPDATE entries SET hidden_at = ? WHERE id = ?",
                         (now_iso(), entry_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"hidden": not back})

    def edit_grouping(self, group_id):
        """The operator may rename a community, channel, project or task."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        conn = connect()
        who = self.operator(conn, payload)
        if who is None:
            boss = operator_name(conn) or "the operator"
            conn.close()
            self.fail(403, "Only %s can rename this." % boss)
            return

        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That does not exist.")
            return

        name = clean(payload.get("name"), 120)
        if not name:
            conn.close()
            self.fail(400, "It must be named.")
            return

        if name != row["name"]:
            log_edit(conn, "grouping", group_id, "edit", "name", row["name"], name,
                     who["id"], who["name"])
            conn.execute("UPDATE groupings SET name = ?, edited_at = ? WHERE id = ?",
                         (name, now_iso(), group_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"id": group_id, "name": name})

    def hide_grouping(self, group_id):
        """The operator takes a community, channel, project or task down. What
        was inside it stays written; it simply stops being listed."""
        payload = self.read_json() or {}
        conn = connect()
        who = self.operator(conn, payload)
        if who is None:
            boss = operator_name(conn) or "the operator"
            conn.close()
            self.fail(403, "Only %s can take this down." % boss)
            return

        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That does not exist.")
            return

        back = clean(payload.get("restore"), 6) == "yes"
        if back:
            log_edit(conn, "grouping", group_id, "takedown", "restored",
                     row["deleted_at"], None, who["id"], who["name"])
            conn.execute("UPDATE groupings SET deleted_at = NULL WHERE id = ?", (group_id,))
        else:
            log_edit(conn, "grouping", group_id, "takedown", None, row["name"], None,
                     who["id"], who["name"])
            conn.execute("UPDATE groupings SET deleted_at = ? WHERE id = ?",
                         (now_iso(), group_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"hidden": not back})

    def hide_from_feed(self, group_id):
        """Take a community or channel off your own list. Nobody else's view
        changes, and Browse offers it back whenever you want it."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)
        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name first.")
            return

        conn = connect()
        if (conn.execute("SELECT 1 FROM groupings WHERE id = ?", (group_id,)).fetchone() is None
                or not may_view(conn, group_id, user_id)):
            conn.close()
            self.fail(404, "That does not exist.")
            return

        if clean(payload.get("restore"), 6) == "yes":
            conn.execute("DELETE FROM feed_hidden WHERE user_id = ? AND group_id = ?",
                         (user_id, group_id))
        else:
            conn.execute("INSERT OR IGNORE INTO feed_hidden (user_id, group_id, hidden_at) "
                         "VALUES (?, ?, ?)", (user_id, group_id, now_iso()))
        conn.commit()
        conn.close()
        self.send_json(200, {"ok": True})

    def offer_reward(self, group_id):
        """Pledge money for finishing a task. Nothing is taken and nothing is
        paid — this records that somebody said they would."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)
        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name before offering a reward.")
            return

        try:
            amount = round(float(payload.get("amount")), 2)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0 or amount > 100000000:
            self.fail(400, "A reward has to be an amount above nothing.")
            return

        note = clean(payload.get("note"), 300)

        conn = connect()
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That does not exist.")
            return
        if row["kind"] == "Community":
            conn.close()
            self.fail(400, "A reward belongs to a task, not to a whole community.")
            return
        if not may_view(conn, group_id, user_id) or not place_is_up(conn, group_id):
            conn.close()
            self.fail(403, "You cannot see that task.")
            return

        author = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        if author is None:
            conn.close()
            self.fail(401, "Choose a name before offering a reward.")
            return

        conn.execute("INSERT INTO rewards (id, group_id, user_id, author, amount, note, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), group_id, user_id, author["name"],
                      amount, note, now_iso()))
        conn.commit()
        totals = reward_total(conn, group_id)
        conn.close()
        self.send_json(201, totals)

    def read_rewards(self, group_id, viewer=""):
        conn = connect()
        row = conn.execute("SELECT * FROM groupings WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That does not exist.")
            return
        if not may_read_place(conn, group_id, viewer):
            conn.close()
            self.fail(403, "That is not open to you.")
            return
        offers = [{"author": r["author"], "amount": r["amount"],
                   "note": r["note"] or "", "at": r["created_at"]}
                  for r in conn.execute(
                      "SELECT * FROM rewards WHERE group_id = ? ORDER BY created_at ASC",
                      (group_id,))]
        totals = reward_total(conn, group_id)
        conn.close()
        totals["offers"] = offers
        totals["count"] = len(offers)
        self.send_json(200, totals)

    def list_entries(self, query):
        scope = (query.get("scope") or ["collective"])[0]
        conn = connect()

        if scope == "personal":
            user_id = (query.get("userId") or [""])[0]
            if not UUID_RE.match(user_id):
                conn.close()
                self.fail(400, "Choose a name before opening My Intelligence.")
                return
            rows = conn.execute(
                "SELECT * FROM entries WHERE user_id = ? AND removed_at IS NULL "
                "AND hidden_at IS NULL ORDER BY created_at ASC", (user_id,)).fetchall()
        else:
            group_id = (query.get("groupId") or [""])[0]
            viewer = (query.get("userId") or [""])[0]
            if not UUID_RE.match(group_id):
                conn.close()
                self.send_json(200, [])
                return
            if not may_read_place(conn, group_id, viewer):
                conn.close()
                self.fail(403, "That is not open to you.")
                return
            # Everything placed in this community, project or task. Responses
            # inherit their parent's placements, so a chain arrives whole.
            rows = conn.execute(
                "SELECT e.* FROM entries e JOIN placements p ON p.entry_id = e.id "
                "WHERE p.group_id = ? AND e.hidden_at IS NULL "
                "ORDER BY e.created_at ASC", (group_id,)).fetchall()

        # One query each for placements and attachments, rather than one per record.
        ids = [r["id"] for r in rows]
        places, pieces = {}, {}
        if ids:
            marks = ",".join("?" * len(ids))
            for p in conn.execute(
                    "SELECT p.entry_id, g.id, g.kind, g.name, g.parent_id "
                    "FROM placements p JOIN groupings g ON g.id = p.group_id "
                    "WHERE p.entry_id IN (%s)" % marks, ids):
                places.setdefault(p["entry_id"], []).append(
                    {"id": p["id"], "kind": p["kind"], "name": p["name"],
                     "parentId": p["parent_id"] or ""})
            for a in conn.execute(
                    "SELECT * FROM attachments WHERE entry_id IN (%s) "
                    "ORDER BY position ASC" % marks, ids):
                pieces.setdefault(a["entry_id"], []).append(piece_to_json(a))

        if places:
            # A record can sit in several places at once. Whoever reads it is
            # told only of the places they could open themselves.
            reader = (query.get("userId") or [""])[0]
            allowed = {}
            for entry_id in list(places):
                kept = []
                for p in places[entry_id]:
                    if p["id"] not in allowed:
                        allowed[p["id"]] = may_read_place(conn, p["id"], reader)
                    if allowed[p["id"]]:
                        kept.append(p)
                places[entry_id] = kept

        conn.close()
        listing = [row_to_entry(r, places.get(r["id"], []), pieces.get(r["id"], []))
                   for r in rows]
        # The page re-asks for this list every half minute while it is open.
        # It says which version it already holds; if nothing has changed the
        # answer is empty, rather than the whole list again.
        tag = hashlib.sha256(json.dumps(listing, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        if self.headers.get("X-Known") == tag:
            self.send_response(204)
            self.send_header("X-Version", tag)
            self.no_cache()
            self.end_headers()
            METER.add(300)
            return
        self.send_json(200, listing, extra=[("X-Version", tag)])

    def serve_upload(self, path, query):
        parts = path.split("/")
        if len(parts) != 4:
            self.fail(404, "Not found.")
            return
        piece_id, name = parts[2], safe_name(parts[3])
        if not UUID_RE.match(piece_id):
            self.fail(404, "Not found.")
            return

        target = os.path.join(UPLOAD_DIR, piece_id, name)
        if not inside(UPLOAD_DIR, target) or not os.path.isfile(target):
            self.fail(404, "Not found.")
            return

        # A file is as private as the record it belongs to: its author, the
        # operator, or anyone who may look in a place the record sits in.
        viewer = self.who_id()
        conn = connect()
        row = conn.execute(
            "SELECT a.entry_id, e.user_id, e.hidden_at FROM attachments a "
            "JOIN entries e ON e.id = a.entry_id WHERE a.id = ?", (piece_id,)).fetchone()
        allowed = False
        if row is not None:
            if viewer and (row["user_id"] == viewer or may_operate(conn, viewer)):
                allowed = True
            elif not row["hidden_at"]:
                for p in conn.execute("SELECT group_id FROM placements WHERE entry_id = ?",
                                      (row["entry_id"],)):
                    if may_read_place(conn, p["group_id"], viewer):
                        allowed = True
                        break
        conn.close()
        if not allowed:
            self.fail(404, "Not found.")      # not "forbidden": do not confirm it exists
            return

        # What a file is served AS is decided here, from its name, never from
        # what the uploader claimed. Pictures and PDFs show in the page; text
        # of any kind, web pages included, shows as plain text, which cannot
        # run; everything else is a download. And whatever it is, it is told
        # it may not run scripts or reach anything else on this site.
        guessed = mimetypes.guess_type(name)[0] or ""
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        extra = []
        download = "download" in query
        if guessed in SHOW_AS_IS:
            mime = guessed
        elif guessed.startswith("text/") or extension in TEXT_FILES or guessed in (
                "application/json", "application/javascript", "application/xml"):
            mime = "text/plain; charset=utf-8"
        else:
            mime = "application/octet-stream"
            download = True
        if guessed != "application/pdf":
            # A browser's PDF reader refuses to open under this rule, and a PDF
            # cannot reach the page anyway; everything else gets it.
            extra.append(("Content-Security-Policy",
                          "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"))

        # Each visitor may download only so much an hour, so one script -- or
        # one very popular file -- cannot run up the host's traffic bill.
        size = os.path.getsize(target)
        if not LIMITS.allow("download", self.client_ip(), DOWNLOAD_PER_HOUR, 3600, cost=size):
            self.fail(429, "That is a lot of downloading for one hour. Try again later.")
            return

        with open(target, "rb") as f:
            body = f.read()
        self.send_bytes(body, mime, name if download else None, extra)

    # -- POST ------------------------------------------------------------

    def do_POST(self):
        path = unquote(urlparse(self.path).path)

        if METER.used_up():
            self.read_json()
            self.paused(path)
            return

        # Every change arrives as JSON from this site's own page. A form on
        # some other website cannot send JSON without the browser asking
        # permission first, which this server never grants, so this one check
        # stops other sites from acting on behalf of a signed-in visitor.
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            self.read_json()
            self.fail(415, "Changes must be sent as JSON.")
            return

        if not LIMITS.allow("write", self.client_ip(), *RATE["write"]):
            self.read_json()
            self.fail(429, "That is a lot of changes at once. Wait a minute and try again.")
            return

        if path == "/api/users":
            self.create_user()
            return

        if path == "/api/session/end":
            self.end_session()
            return

        if path == "/api/users/reset":
            self.reset_password()
            return

        if path == "/api/entries":
            self.create_entry()
            return

        if path == "/api/folders":
            self.create_folder()
            return

        if path == "/api/groupings":
            self.create_grouping()
            return

        access = re.match(r"^/api/groupings/([a-f0-9-]{36})/access$", path, re.I)
        if access:
            self.write_access(access.group(1))
            return

        purse = re.match(r"^/api/groupings/([a-f0-9-]{36})/rewards$", path, re.I)
        if purse:
            self.offer_reward(purse.group(1))
            return

        edit_g = re.match(r"^/api/groupings/([a-f0-9-]{36})/edit$", path, re.I)
        if edit_g:
            self.edit_grouping(edit_g.group(1))
            return

        gone_g = re.match(r"^/api/groupings/([a-f0-9-]{36})/takedown$", path, re.I)
        if gone_g:
            self.hide_grouping(gone_g.group(1))
            return

        unfeed = re.match(r"^/api/groupings/([a-f0-9-]{36})/feed$", path, re.I)
        if unfeed:
            self.hide_from_feed(unfeed.group(1))
            return

        edit_e = re.match(r"^/api/entries/([a-f0-9-]{36})/edit$", path, re.I)
        if edit_e:
            self.edit_entry(edit_e.group(1))
            return

        gone_e = re.match(r"^/api/entries/([a-f0-9-]{36})/takedown$", path, re.I)
        if gone_e:
            self.hide_entry(gone_e.group(1))
            return

        joining = re.match(r"^/api/groupings/([a-f0-9-]{36})/join$", path, re.I)
        if joining:
            self.join_grouping(joining.group(1))
            return

        share = re.match(r"^/api/entries/([a-f0-9-]{36})/share$", path, re.I)
        if share:
            self.share_entry(share.group(1))
            return

        place = re.match(r"^/api/entries/([a-f0-9-]{36})/place$", path, re.I)
        if place:
            self.place_entry(place.group(1))
            return

        move = re.match(r"^/api/entries/([a-f0-9-]{36})/move$", path, re.I)
        if move:
            self.move_entry(move.group(1))
            return

        drop = re.match(r"^/api/entries/([a-f0-9-]{36})/remove$", path, re.I)
        if drop:
            self.remove_entry(drop.group(1))
            return

        drop_folder = re.match(r"^/api/folders/([a-f0-9-]{36})/remove$", path, re.I)
        if drop_folder:
            self.remove_folder(drop_folder.group(1))
            return

        self.read_json()   # drain the body first
        self.fail(404, "Not found.")

    def create_folder(self):
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)
        name = clean(payload.get("name"), 120)
        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name before making a file.")
            return
        if not name:
            self.fail(400, "A file needs a name.")
            return

        conn = connect()
        existing = conn.execute(
            "SELECT id, name FROM folders WHERE user_id = ? AND name = ? COLLATE NOCASE",
            (user_id, name)).fetchone()
        if existing:
            conn.close()
            self.send_json(200, {"id": existing["id"], "name": existing["name"]})
            return

        folder = {"id": str(uuid.uuid4()), "user_id": user_id,
                  "name": name, "created_at": now_iso()}
        conn.execute("INSERT INTO folders (id, user_id, name, created_at) "
                     "VALUES (:id, :user_id, :name, :created_at)", folder)
        conn.commit()
        conn.close()
        self.send_json(201, {"id": folder["id"], "name": folder["name"]})

    def create_grouping(self):
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)
        name = clean(payload.get("name"), 120)
        parent_id = clean(payload.get("parentId"), 40)

        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name before making one of these.")
            return
        if not name:
            self.fail(400, "It must be named.")
            return

        conn = connect()

        # A community holds communities, projects and tasks. A news channel
        # holds only more channels — no projects, no tasks — because a channel
        # is a place things are published to, not a place work is organised in.
        # Projects and tasks are the end of a branch either way.
        if parent_id:
            parent = (conn.execute("SELECT * FROM groupings WHERE id = ?", (parent_id,)).fetchone()
                      if UUID_RE.match(parent_id) else None)
            if parent is None or parent["kind"] not in HOLDERS:
                conn.close()
                self.fail(400, "Only a community or a news channel can hold other things.")
                return
            if len(ancestry(conn, parent_id)) >= MAX_DEPTH:
                conn.close()
                self.fail(400, "That is as deep as places go: %d levels." % MAX_DEPTH)
                return
            reach = parent["reach"] or "global"

            if parent["kind"] == "Channel":
                kind = "Channel"
            else:
                kind = clean(payload.get("kind"), 40) or "Project"
                if kind == "Channel":
                    conn.close()
                    self.fail(400, "News channels live in News, not inside a community.")
                    return

            if not may_contribute(conn, parent_id, user_id):
                conn.close()
                self.fail(403, "You are not a contributor to that %s."
                          % ("channel" if parent["kind"] == "Channel" else "community"))
                return

            # The shape of a community is the founder's to set. Everyone else
            # adds projects, tasks and records into what already exists.
            if kind in HOLDERS and not governs(conn, parent_id, user_id):
                conn.close()
                self.fail(403, "Only the person who founded this one can add another inside it.")
                return
        else:
            parent_id = None
            # Which section this is being made in. Everywhere else — including
            # while sharing — makes one of your own.
            reach = clean(payload.get("reach"), 10)
            if reach not in ("mine", "global", "news"):
                reach = "mine"

            # News holds channels; the other two hold communities. Inside your
            # own section you may found either, and My News says which.
            kind = clean(payload.get("kind"), 40)
            kind = "Channel" if (reach == "news" or kind == "Channel") else "Community"

            # For now the two permanent public sections are one person's to
            # found in. Remove this when accounts exist.
            if reach in ("global", "news") and not is_global_founder(conn, user_id):
                boss = operator_name(conn) or "the operator"
                conn.close()
                self.fail(403, "Only %s can start a %s for now."
                          % (boss,
                             "News channel" if reach == "news" else "global community"))
                return

        # Your own communities are yours; global ones are shared, so a name
        # collides only within the same reach and owner.
        if reach == "mine" and not parent_id:
            existing = conn.execute(
                "SELECT * FROM groupings WHERE name = ? COLLATE NOCASE AND reach = 'mine' "
                "AND kind = ? AND created_by = ? AND (parent_id IS NULL OR parent_id = '')",
                (name, kind, user_id)).fetchone()
        else:
            existing = conn.execute(
                "SELECT * FROM groupings WHERE name = ? COLLATE NOCASE "
                "AND IFNULL(parent_id, '') = ? AND IFNULL(reach, 'global') = ?",
                (name, parent_id or "", reach)).fetchone()

        if existing:
            conn.close()
            self.send_json(200, {"id": existing["id"], "kind": existing["kind"],
                                 "name": existing["name"],
                                 "parentId": existing["parent_id"] or "",
                                 "reach": existing["reach"] or "global"})
            return

        # A community you make for yourself starts private; a global one starts
        # open, which is how global communities behaved before this setting
        # existed. The founder can change either afterwards.
        # The two permanent public sections start open, which is how global
        # communities have always behaved. Anything of your own starts shut.
        top_of_global = reach in ("global", "news") and not parent_id
        contribute = "open" if top_of_global else "invite"
        viewing = "open" if top_of_global else "invite"

        grouping = {"id": str(uuid.uuid4()), "kind": kind, "name": name,
                    "parent_id": parent_id, "reach": reach, "contribute": contribute,
                    "viewing": viewing, "created_by": user_id, "created_at": now_iso()}
        conn.execute("INSERT INTO groupings "
                     "(id, kind, name, parent_id, reach, contribute, viewing, "
                     " created_by, created_at) "
                     "VALUES (:id, :kind, :name, :parent_id, :reach, :contribute, "
                     ":viewing, :created_by, :created_at)",
                     grouping)
        conn.commit()
        conn.close()
        self.send_json(201, {"id": grouping["id"], "kind": kind, "name": name,
                             "parentId": parent_id or "", "reach": reach})

    def place_entry(self, entry_id):
        """Move a record into (or out of) a file or a grouping. Organisation
        only — it never changes the record itself, and never removes it."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)

        conn = connect()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That record does not exist.")
            return
        if row["user_id"] != user_id:
            conn.close()
            self.fail(403, "Only the person who wrote a record can file it.")
            return

        folder_id = clean(payload.get("folderId"), 40) or None
        if folder_id:
            owned = conn.execute(
                "SELECT id FROM folders WHERE id = ? AND user_id = ?",
                (folder_id, user_id)).fetchone()
            if not owned:
                conn.close()
                self.fail(400, "That file does not exist.")
                return
        conn.execute("UPDATE entries SET folder_id = ? WHERE id = ?", (folder_id, entry_id))

        conn.commit()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        conn.close()
        self.send_json(200, row_to_entry(row))

    def create_user(self):
        """Sign in, or make a new name. One form does both: a name nobody has
        is created with the password given; a name that exists must match its
        password. The answer sets the sign-in cookie."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return

        name = clean(payload.get("name"), 120)
        password = "" if payload.get("password") is None else str(payload.get("password"))[:200]
        if len(name) < 2:
            self.fail(400, "A name needs at least two characters.")
            return
        if not password:
            self.fail(400, "Enter a password.")
            return

        ip = self.client_ip()
        key = name.lower()
        # Guessing is limited per address, and per address-and-name. Never
        # per name alone: then a stranger could lock the owner out of their
        # own account just by guessing wrong on purpose.
        if not (LIMITS.allow("signin", ip, *RATE["signin"])
                and LIMITS.allow("signin-name", (ip, key), 8, 300)):
            self.fail(429, "Too many tries. Wait a few minutes and try again.")
            return

        conn = connect()
        row = conn.execute("SELECT * FROM users WHERE name_key = ?", (key,)).fetchone()
        created = False

        if row is None:
            if len(password) < MIN_PASSWORD:
                conn.close()
                self.fail(400, "A new name needs a password of at least %d characters."
                          % MIN_PASSWORD)
                return
            if not LIMITS.allow("newname", ip, *RATE["newname"]):
                conn.close()
                self.fail(429, "Too many new names from here. Try again later.")
                return
            user_id = str(uuid.uuid4())
            conn.execute("INSERT INTO users (id, name, name_key, created_at, pass_hash) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (user_id, name, key, now_iso(), hash_password(password)))
            user = {"id": user_id, "name": name}
            created = True

        elif not row["pass_hash"]:
            # A name from before passwords existed. At home, a name was always
            # a claim, so whoever claims it now sets its password. On the
            # internet that would let a stranger take it, so the operator
            # sets one instead.
            if PUBLIC:
                conn.close()
                self.fail(403, "This name has no password yet. Ask the operator to set one.")
                return
            if len(password) < MIN_PASSWORD:
                conn.close()
                self.fail(400, "Choose a password of at least %d characters for this name."
                          % MIN_PASSWORD)
                return
            conn.execute("UPDATE users SET pass_hash = ? WHERE id = ?",
                         (hash_password(password), row["id"]))
            user = {"id": row["id"], "name": row["name"]}

        elif password_matches(password, row["pass_hash"]):
            user = {"id": row["id"], "name": row["name"]}

        else:
            conn.close()
            self.fail(401, "That name and password do not match.")
            return

        session = start_session(conn, user["id"])
        conn.commit()
        boss = operator_name(conn)
        conn.close()
        self.send_json(201 if created else 200,
                       {"id": user["id"], "name": user["name"], "created": created,
                        "operator": boss},
                       cookie=self.cookie_header(session, SESSION_DAYS * 86400))

    def end_session(self):
        """Sign out: forget this browser's key here and in the browser."""
        self.read_json()
        key = self.sign_in_key()
        if key:
            conn = connect()
            conn.execute("DELETE FROM sessions WHERE key_hash = ?", (key_hash(key),))
            conn.commit()
            conn.close()
        self.send_json(200, {"signedOut": True}, cookie=self.cookie_header("", 0))

    def reset_password(self):
        """The operator sets a new password for someone who forgot theirs.
        Every place that person was signed in is signed out."""
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That request could not be read.")
            return
        conn = connect()
        if self.operator(conn, payload) is None:
            conn.close()
            self.fail(403, "Only the operator can reset a password.")
            return
        name = clean(payload.get("name"), 120)
        password = "" if payload.get("password") is None else str(payload.get("password"))[:200]
        if len(password) < MIN_PASSWORD:
            conn.close()
            self.fail(400, "A password needs at least %d characters." % MIN_PASSWORD)
            return
        row = conn.execute("SELECT id FROM users WHERE name_key = ?", (name.lower(),)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "Nobody here is called that.")
            return
        conn.execute("UPDATE users SET pass_hash = ? WHERE id = ?",
                     (hash_password(password), row["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        conn.commit()
        conn.close()
        self.send_json(200, {"reset": True, "name": name})

    def create_entry(self):
        payload = self.read_json()
        if payload is None:
            self.fail(400, "That record is too large or could not be read.")
            return

        user_id = clean(payload.get("userId"), 40)
        if not UUID_RE.match(user_id):
            self.fail(401, "Choose a name before adding a record.")
            return

        conn = connect()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            conn.close()
            self.fail(401, "That name is no longer in this copy. Choose one again.")
            return

        entry = {
            "id": str(uuid.uuid4()),
            # Stamped here, always now. The browser never sends a time, which is
            # what makes backdating impossible rather than merely discouraged.
            "created_at": now_iso(),
            "user_id": user["id"],
            "author": user["name"],
            "fn": clean(payload.get("fn"), 60),
            "title": clean(payload.get("title"), 300),
            "kind": "text",   # kept for older readers; the pieces carry the truth
            "url": None, "body": None,
            "file_name": None, "file_mime": None, "file_size": None,
            "shared": 0, "shared_at": None, "reply_to": None,
            "folder_id": None, "group_id": None,
        }

        # A title is optional; the function is not. What was done is the record.
        if not entry["fn"]:
            conn.close()
            self.fail(400, "Every record needs a function.")
            return

        # A record carries as many links, files and notes as you like.
        raw_pieces = payload.get("pieces")
        if not isinstance(raw_pieces, list) or not raw_pieces:
            conn.close()
            self.fail(400, "Add at least one link, file or note.")
            return
        if len(raw_pieces) > 25:
            conn.close()
            self.fail(400, "That is more than 25 pieces on one record.")
            return

        pieces, blobs = [], {}
        for spec in raw_pieces:
            if not isinstance(spec, dict):
                continue
            piece = {"id": str(uuid.uuid4()), "entry_id": entry["id"],
                     "position": len(pieces), "kind": clean(spec.get("kind"), 10),
                     "url": None, "body": None, "file_name": None,
                     "file_mime": None, "file_size": None,
                     "created_at": entry["created_at"]}

            if piece["kind"] == "link":
                piece["url"] = clean(spec.get("url"), 2000)
                if not URL_RE.match(piece["url"]):
                    conn.close()
                    self.fail(400, "That is not a URL the ledger can open.")
                    return

            elif piece["kind"] == "text":
                piece["body"] = ("" if spec.get("text") is None
                                 else str(spec["text"]))[:MAX_TEXT_CHARS]
                if not piece["body"].strip():
                    conn.close()
                    self.fail(400, "One of the notes is empty.")
                    return

            elif piece["kind"] == "file":
                spec_file = spec.get("file") or {}
                if not spec_file.get("b64"):
                    conn.close()
                    self.fail(400, "One of the files did not arrive.")
                    return
                try:
                    data = base64.b64decode(spec_file["b64"], validate=True)
                except Exception:
                    conn.close()
                    self.fail(400, "One of the files could not be read.")
                    return
                if not data:
                    conn.close()
                    self.fail(400, "One of the files is empty.")
                    return
                if len(data) > MAX_FILE_BYTES:
                    conn.close()
                    self.fail(400, "A file is over the %d MB limit. Link it instead."
                              % (MAX_FILE_BYTES // (1024 * 1024)))
                    return
                piece["file_name"] = safe_name(spec_file.get("name"))
                piece["file_mime"] = clean(spec_file.get("mime"), 120) or "application/octet-stream"
                piece["file_size"] = len(data)
                blobs[piece["id"]] = (piece["file_name"], data)

            else:
                conn.close()
                self.fail(400, "A piece is a link, a file, or a note.")
                return

            pieces.append(piece)

        if not pieces:
            conn.close()
            self.fail(400, "Add at least one link, file or note.")
            return

        # Files are limited by how much each address uploads in an hour, so
        # one script cannot fill the disk.
        upload_bytes = sum(len(data) for _, data in blobs.values())
        if upload_bytes and not LIMITS.allow("upload", self.client_ip(),
                                             *RATE["upload"], cost=upload_bytes):
            conn.close()
            self.fail(429, "That is a lot of uploading for one hour. Try again later, "
                           "or link to the file instead.")
            return

        reply_to = clean(payload.get("replyTo"), 40)
        if reply_to:
            if not UUID_RE.match(reply_to):
                conn.close()
                self.fail(400, "That is not a record you can respond to.")
                return
            parent = conn.execute("SELECT shared, group_id, hidden_at FROM entries WHERE id = ?",
                                  (reply_to,)).fetchone()
            if parent is None or not parent["shared"] or parent["hidden_at"]:
                conn.close()
                self.fail(400, "You can only respond to a record in the Collective.")
                return
            # A response goes where the record it answers sits -- but only
            # into the places this person may put things. Somewhere they may
            # only look, or cannot see at all, it does not go.
            reply_places = [p["group_id"] for p in conn.execute(
                "SELECT group_id FROM placements WHERE entry_id = ?", (reply_to,))
                if may_contribute(conn, p["group_id"], user["id"])
                and place_is_up(conn, p["group_id"])]
            if not reply_places:
                conn.close()
                self.fail(403, "You may read that record but not respond to it there.")
                return
            entry["reply_to"] = reply_to
            entry["shared"] = 1
            entry["shared_at"] = entry["created_at"]

        # Written from inside a community, channel, project or task: the record
        # goes straight in there AND stays in the author's My Intelligence,
        # because every record is its author's first. Sharing is still the
        # deliberate act — this is simply doing it in the same breath.
        into = clean(payload.get("groupId"), 40)
        landing = None
        if into:
            if not UUID_RE.match(into):
                conn.close()
                self.fail(400, "That is not a place a record can go.")
                return
            landing = conn.execute("SELECT * FROM groupings WHERE id = ?", (into,)).fetchone()
            if landing is None:
                conn.close()
                self.fail(404, "That community no longer exists.")
                return
            if not may_contribute(conn, into, user["id"]):
                conn.close()
                self.fail(403, "You are not a contributor to that one.")
                return
            if entry["reply_to"]:
                # A response goes where the record it answers already sits.
                landing = None
            else:
                entry["shared"] = 1
                entry["shared_at"] = entry["created_at"]

        # Optional file chosen when the record was written (Personal only).
        folder_id = clean(payload.get("folderId"), 40)
        if folder_id and UUID_RE.match(folder_id):
            owned = conn.execute(
                "SELECT id FROM folders WHERE id = ? AND user_id = ?",
                (folder_id, user["id"])).fetchone()
            if owned:
                entry["folder_id"] = folder_id

        try:
            for piece_id, (name, data) in blobs.items():
                folder = os.path.join(UPLOAD_DIR, piece_id)
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(data)

            conn.execute(
                """INSERT INTO entries
                     (id, created_at, user_id, author, fn, title, kind, url, body,
                      file_name, file_mime, file_size, shared, shared_at, reply_to,
                      folder_id, group_id)
                   VALUES
                     (:id, :created_at, :user_id, :author, :fn, :title, :kind, :url, :body,
                      :file_name, :file_mime, :file_size, :shared, :shared_at, :reply_to,
                      :folder_id, :group_id)""",
                entry)

            for piece in pieces:
                conn.execute(
                    """INSERT INTO attachments
                         (id, entry_id, position, kind, url, body, file_name,
                          file_mime, file_size, created_at)
                       VALUES
                         (:id, :entry_id, :position, :kind, :url, :body, :file_name,
                          :file_mime, :file_size, :created_at)""", piece)

            # A response goes wherever the record it answers already sits.
            if entry["reply_to"]:
                for place in reply_places:
                    conn.execute(
                        "INSERT OR IGNORE INTO placements (entry_id, group_id, created_at) "
                        "VALUES (?, ?, ?)", (entry["id"], place, entry["created_at"]))
            elif landing is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO placements (entry_id, group_id, created_at) "
                    "VALUES (?, ?, ?)", (entry["id"], landing["id"], entry["created_at"]))

            conn.commit()
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry["id"],)).fetchone()
            stored = conn.execute(
                "SELECT * FROM attachments WHERE entry_id = ? ORDER BY position ASC",
                (entry["id"],)).fetchall()
            conn.close()
        except Exception:
            conn.close()
            traceback.print_exc()
            self.fail(500, "The record could not be written.")
            return

        self.send_json(201, row_to_entry(row, [], [piece_to_json(a) for a in stored]))

    def share_entry(self, entry_id):
        """Share a record into one or more communities. Sharing again adds
        communities; it never takes one away."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)
        wanted = payload.get("groupIds")
        if not isinstance(wanted, list):
            wanted = payload.get("communityIds")   # older name
        if not isinstance(wanted, list):
            wanted = []
        wanted = [clean(c, 40) for c in wanted[:50]]
        wanted = [c for c in wanted if UUID_RE.match(c)]

        conn = connect()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            conn.close()
            self.fail(404, "That record does not exist.")
            return
        if row["user_id"] != user_id:
            conn.close()
            self.fail(403, "Only the person who wrote a record can share it.")
            return
        if not wanted:
            conn.close()
            self.fail(400, "Choose at least one community to share this with.")
            return

        stamp = now_iso()
        placed = 0
        for group_id in wanted:
            # A community, or a project or task inside one — both are valid
            # destinations, so a thought can go straight where it belongs.
            ok = conn.execute("SELECT id FROM groupings WHERE id = ?", (group_id,)).fetchone()
            if not ok or not may_contribute(conn, group_id, user_id):
                continue
            conn.execute("INSERT OR IGNORE INTO placements (entry_id, group_id, created_at) "
                         "VALUES (?, ?, ?)", (entry_id, group_id, stamp))
            placed += 1

        if not placed:
            conn.close()
            self.fail(400, "That community does not exist.")
            return

        if not row["shared"]:
            conn.execute("UPDATE entries SET shared = 1, shared_at = ? WHERE id = ?",
                         (stamp, entry_id))
        conn.commit()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        conn.close()
        self.send_json(200, row_to_entry(row))

    def move_entry(self, entry_id):
        """Move a record between a community and one of its projects or tasks.
        Organisation only: it never leaves the Collective."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)
        source = clean(payload.get("fromGroupId"), 40)
        target = clean(payload.get("toGroupId"), 40)

        conn = connect()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None or row["user_id"] != user_id:
            conn.close()
            self.fail(403, "Only the person who wrote a record can move it.")
            return
        if not UUID_RE.match(source):
            conn.close()
            self.fail(400, "That is not somewhere a record can move from.")
            return

        src = conn.execute("SELECT * FROM groupings WHERE id = ?", (source,)).fetchone()
        if src is None:
            conn.close()
            self.fail(404, "That community does not exist.")
            return
        root = root_grouping(conn, source)

        if not conn.execute("SELECT 1 FROM placements WHERE entry_id = ? AND group_id = ?",
                            (entry_id, source)).fetchone():
            conn.close()
            self.fail(400, "That record is not there to move.")
            return

        if target:
            dest = conn.execute("SELECT * FROM groupings WHERE id = ?", (target,)).fetchone()
            if dest is None or root_grouping(conn, target) != root:
                conn.close()
                self.fail(400, "A record can only move within its own community.")
                return
            if not may_contribute(conn, target, user_id) or not place_is_up(conn, target):
                conn.close()
                self.fail(403, "You are not a contributor there.")
                return
        else:
            target = src["parent_id"] or root   # step back up one level

        conn.execute("DELETE FROM placements WHERE entry_id = ? AND group_id = ?",
                     (entry_id, source))
        conn.execute("INSERT OR IGNORE INTO placements (entry_id, group_id, created_at) "
                     "VALUES (?, ?, ?)", (entry_id, target, now_iso()))
        # Responses follow whatever they answer.
        for child in conn.execute("SELECT id FROM entries WHERE reply_to = ?", (entry_id,)):
            conn.execute("DELETE FROM placements WHERE entry_id = ? AND group_id = ?",
                         (child["id"], source))
            conn.execute("INSERT OR IGNORE INTO placements (entry_id, group_id, created_at) "
                         "VALUES (?, ?, ?)", (child["id"], target, now_iso()))
        conn.commit()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        conn.close()
        self.send_json(200, row_to_entry(row))

    def remove_entry(self, entry_id):
        """Take a record out of My Intelligence. If it was shared it
        stays in the Collective, where nothing is ever removed."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)

        conn = connect()
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None or row["user_id"] != user_id:
            conn.close()
            self.fail(403, "Only the person who wrote a record can remove it.")
            return

        conn.execute("UPDATE entries SET removed_at = ? WHERE id = ?", (now_iso(), entry_id))
        conn.commit()
        conn.close()
        self.send_json(200, {"removed": True, "stillInCollective": bool(row["shared"])})

    def remove_folder(self, folder_id):
        """Remove a file. The records that were in it are not touched; they
        simply stop being filed."""
        payload = self.read_json() or {}
        user_id = clean(payload.get("userId"), 40)

        conn = connect()
        row = conn.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        if row is None or row["user_id"] != user_id:
            conn.close()
            self.fail(403, "Only the person who made a file can remove it.")
            return

        conn.execute("UPDATE entries SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        conn.commit()
        conn.close()
        self.send_json(200, {"removed": True})


# ===========================================================================
# RUN
# ===========================================================================

def port_is_taken(port):
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def serve_hosted():
    """On a host: one exact address, no browser to open, and a refusal to run
    at all without a disk that survives restarts -- otherwise every restart
    would quietly wipe every record, which is the likeliest way to lose them."""
    if not (os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")):
        print("  Cognaut will not start on a host without a lasting disk.")
        print("  Attach a disk (Render) or volume (Railway) and set DATA_DIR to")
        print("  where it is mounted. Without one, every restart deletes everything.")
        sys.exit(1)
    problem = setup()
    if problem:
        # Better not to open at all than to open with the operator's name
        # free for the first stranger to take.
        print("  Cognaut will not start: " + problem)
        sys.exit(1)
    httpd = SiteServer((HOST, FIRST_PORT), Handler)
    conn = connect()
    boss = operator_name(conn)
    conn.close()
    print("  Cognaut -- %s, %s -- online, listening on %s:%d" % (VERSION, BUILD_DATE, HOST, FIRST_PORT))
    print("  Data in %s. Operator: %s" % (DATA_DIR, boss or "nobody (set OPERATOR)"))
    if BANDWIDTH_GB:
        print("  Traffic this month: %.2f of %g GB" % (METER.bytes / 1024 ** 3, BANDWIDTH_GB))
    sys.stdout.flush()

    # When the host stops or restarts the site, write down the month's
    # traffic count first, so the cap does not forget what was used.
    def stopping(signum, frame):
        METER.flush()
        sys.exit(0)
    signal.signal(signal.SIGTERM, stopping)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def serve():
    if PUBLIC:
        serve_hosted()
        return

    setup()

    moved = port_is_taken(FIRST_PORT)

    httpd = None
    port = FIRST_PORT
    for candidate in range(FIRST_PORT, FIRST_PORT + 20):
        try:
            httpd = SiteServer((HOST, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue

    if httpd is None:
        print("")
        print("  Could not find a free port between %d and %d." % (FIRST_PORT, FIRST_PORT + 19))
        print("  Another copy is probably already running. Close its window and try again.")
        print("")
        return

    url = "http://localhost:%d" % port

    print("")
    print("  Cognaut -- %s, %s" % (VERSION, BUILD_DATE))
    print("  Running from: %s" % HERE)
    print("")

    if moved:
        print("  ! ANOTHER COPY IS ALREADY RUNNING on port %d." % FIRST_PORT)
        print("  ! This one has opened at a DIFFERENT address, below. If you")
        print("  ! visit localhost:%d you will see the OLD copy instead." % FIRST_PORT)
        print("  ! Close the other black window, then start this one again.")
        print("")

    print("      %s" % url)
    print("")
    print("  Your browser should open by itself. If it does not, copy the")
    print("  address above into it.")
    print("")
    print("  If the page looks like an older version, press Ctrl+F5 in the")
    print("  browser to force a fresh copy. %s/api/version should read: %s"
          % (url, VERSION))
    print("")
    print("  Leave this window open. It IS the website. Closing it stops the")
    print("  site; nothing is lost, and you can press Start again any time.")
    print("")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("")
        print("  Stopped. Every record is safe in the data folder.")
        print("")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        print("")
        print("  Cognaut could not start. What went wrong:")
        print("")
        traceback.print_exc()
        print("")
        if PUBLIC:
            sys.exit(1)          # a host has no window to keep open; let it restart us
        input("  Press Enter to close this window. ")
