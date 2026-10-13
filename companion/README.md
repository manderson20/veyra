# Veyra Companion

A Chrome and Edge extension (Manifest V3) that puts the Veyra phone system
next to the browser: sign in with your Veyra account, dial any number so your
desk phone rings first and then places the call, look people up in the
directory, see who is calling, keep personal speed dials and (optionally) make
`tel:` links on web pages ring your phone. Design and server API:
[`docs/COMPANION.md`](../docs/COMPANION.md).

## Build

Node 22 (or 20.9+) is required.

```sh
cd companion
npm ci
npm run build        # -> dist/
npm run typecheck    # tsc --noEmit
npm run test         # vitest
npm run zip          # -> veyra-companion-<version>.zip (from dist/)
```

`dist/` contains `manifest.json` (version taken from `package.json`),
`background.js` (service worker), `content.js` (tel: link handler),
`popup.html`, `options.html`, their assets and the generated icons. There are
no binary assets in the repository: `scripts/icons.mjs` renders the PNG icons
at build time (`npm run icons` writes them to `icons/` if you want to look at
them).

## Getting the extension from a Veyra server

An installed Veyra serves the packaged extension at
`https://<server>/downloads/veyra-companion.zip`; the account page (Connected
apps → Get the Veyra Companion extension) links to it with the steps below.

## Load unpacked

1. Open `chrome://extensions` (Edge: `edge://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose the `companion/dist` directory.
4. Pin the Veyra icon to the toolbar if you like.

After rebuilding, click the reload arrow on the extension's card.

## Signing in

Click the toolbar icon, enter the server address (`https://pbx.example.org`),
your email and password, and a second-factor code if your account requires
one. Users who must enrol a second factor are asked to do that in the web
interface first; the extension cannot show the QR code.

The server address must be **HTTPS with a certificate the operating system
trusts**. An extension cannot click through a certificate warning. If your
installation uses the installer's self-signed certificate, import it into the
machine's trust store (or use a certificate from your organization's CA).

Signing in creates a bearer token that can only dial from your own phones and
read the directory. You can see it, and revoke it, under *Connected apps* on
your account page in the web interface; *Sign out* in the extension revokes
it too.

## Permission prompts

The extension asks for as little as possible up front and requests the rest
when you turn on the feature that needs it:

| Prompt | When | Why |
|---|---|---|
| "Read and change your data on *your-server*" | When you sign in | Lets the extension talk to that one server (API calls and the call-event stream). No other site is touched. |
| "Read and change all your data on all websites" | When you turn on **Handle tel: links** in Options | Needed to notice clicks on `tel:` links on HTTPS pages. Leave the option off and this is never requested. |

Permissions declared at install (no prompt): `storage` (the token and a
cache of your settings), `notifications` (incoming and missed calls),
`contextMenus` ("Call … with Veyra" on selected text) and `alarms` (a
once-a-minute check that the event stream is still connected).

## Development notes

* Plain TypeScript and DOM, no frameworks; Vite builds four entries. The
  service worker and the content script must stay single files, so the pages
  import only types from the modules the worker uses (the build fails if a
  shared chunk appears).
* Everything personal (speed dials, dial prefix, notification toggles,
  default extension) is stored on the server through `/api/v1/me/preferences`
  and follows you to other browsers.
* Dependencies follow `docs/DEVELOPMENT.md` §6: exact versions, at least two
  weeks old, lockfile generated with
  `npx npm@11.6.2 install --before=<date>`.
