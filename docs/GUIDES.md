# Help guides

The guides people read to set up and use Veyra. One source, two places:

* **In Veyra:** the **Help** link in the top bar opens the guide for the
  page you are on ("How do I…?"), or the list of guides at `/help/`.
  Administrators' guides are listed for people who can change something;
  everyone sees the guides for users.
* **On the GitHub wiki** (<https://github.com/manderson20/veyra/wiki>),
  published by `.github/workflows/wiki.yml` at every release. Each page
  starts with the release it reflects and its release date, and when the
  guide was last reviewed. The wiki is generated: edits made there are
  overwritten, so change the guides in the repository.

The developer and design documents in `docs/` stay as they are; guides are
written for administrators and users, not developers.

## Writing a guide

One Markdown file per task in `docs/guides/`, named with lower-case words
and dashes (the name is the guide's address: `/help/<name>/`). It starts
with front matter:

```markdown
---
title: Set up single sign-on
summary: One sentence on what the guide gets done.
audience: admin            # admin | user
section: Sign-in and security   # one of SECTIONS in tools/guides.py
order: 10                  # position within the section (default 50)
reviewed: 0.27.44          # the release this text was last checked against
pages:                     # web pages whose Help link opens this guide
  - /system/sign-in/
covers:                    # the code the guide describes (git globs)
  - frontend/src/app/(app)/system/sign-in/*
  - backend/veyra/api/v1/sso.py
---
```

The body uses headings from `##` down, paragraphs, lists (nested by two
spaces), tables, code, and notes: a quote starting with `**Note:**`,
`**Tip:**`, `**Important:**` or `**Warning:**`. Links:

| Write | In Veyra | On the wiki |
|---|---|---|
| `[text](guide:single-sign-on)` | the other guide | the other wiki page |
| `[System → Sign-in](app:/system/sign-in/)` | the page itself | the text in bold |
| `[text](repo:docs/INSTALLATION.md)` | the file on GitHub | the same |
| `[text](https://…)` | opens in a new tab | the same |

Style: plain words for people who are not telephony experts, the names
exactly as the screen shows them in bold, numbered steps for things done in
order, and what to check when it does not work.

`python3 tools/guides.py build` checks every guide (front matter, that each
`covers` glob matches a file, that each page and link exists) and writes
`frontend/src/generated/guides.json`, which is committed; CI fails when it
is out of date.

## Keeping guides current

Every guide says which code it describes (`covers`). When a commit changes
that code after the guide's own last commit, the guide is **stale**:
`python3 tools/guides.py stale` lists it with the files that changed.

* With every change to a feature, run `stale` and review each guide it
  lists against the change: update the text and set `reviewed:` to the
  version that ships the change. A guide that is still right gets
  `python3 tools/guides.py review <name>…`, which records `checked:` with
  today's date — that commit records the review.
* `release.sh` refuses to release while a guide is stale, and CI on `main`
  fails the same way, so the wiki and the Help pages never fall behind a
  release.
* The release script rebuilds `guides.json` after the CHANGELOG heading
  gets its date, so each guide shows the date of the release it was
  reviewed for.

`python3 tools/guides.py coverage` lists the web pages no guide covers yet
(information only, shown in CI).

## The wiki

GitHub creates a wiki's repository only when its first page is saved, so
before the first publish someone saves any page once (Wiki → *Create the
first page* → Save). After that the workflow replaces the whole wiki at
every release; it can also be run by hand (Actions → Wiki → Run workflow).
