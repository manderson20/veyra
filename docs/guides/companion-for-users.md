---
title: Use the Companion extension
summary: Call from your browser, see who is calling, look people up and listen to voicemail with the Veyra Companion.
audience: user
section: Companion extension
order: 20
reviewed: 0.27.44
pages:
  - /account/
covers:
  - frontend/src/components/account/ConnectedAppsCard.tsx
  - companion/src/*
---

The Veyra Companion is a small extension for Chrome and Edge. It puts your phone next to your browser:

- **Call any number with one click.** Your desk phone rings first. Pick it up, and Veyra then places the call.
- **See who is calling**, in a notification, with **Call back** for missed calls.
- **Look people up** in the directory and call them.
- **Listen to voicemail** and see your recent calls.
- **Call a number you see on a web page.** Select it, right-click, and choose *Call … with Veyra*.

## Getting it

Your school or company may already have installed it for you. Look for the Veyra icon in the browser toolbar, or in the puzzle-piece menu. If it is there, skip to *Signing in*.

If it is not there:

1. In Veyra, open [your account](app:/account/) and find **Connected apps → Get the Veyra Companion extension**.
2. Try **Add to Chrome** first. If the browser refuses, download **veyra-companion.zip** and unzip it into a folder you keep. Don't delete the folder afterwards: the browser loads the extension from it.
3. Type `chrome://extensions` (Edge: `edge://extensions`) in the address bar. Turn on **Developer mode** (top right), choose **Load unpacked** (top left) and pick the unzipped folder.
4. Pin the Veyra icon from the puzzle-piece menu so it is always visible.

> **Note:** An extension installed this way does not update itself. When your administrator tells you there is a new version, download the zip again and replace the folder's contents.

## Signing in

1. Click the Veyra icon.
2. If the server address is not filled in already, enter the address you use for Veyra, for example `https://pbx.example.org`.
3. Sign in with your Veyra e-mail and password and your authenticator code. If there is a **Sign in with Google** (or Microsoft) button, use that instead.

The Companion stays signed in while you use it, and signs out after 30 days without use. Every browser you sign in from is listed on [your account](app:/account/) under **Connected apps**. You can sign it out from there, for example if you lose a laptop.

## Making a call

- Type a number in the Companion and choose **Call**, or pick someone from your favourites, the directory or your recent calls.
- Your desk phone rings. Pick it up and the call goes out. Outside numbers get the outside-line prefix automatically.
- If you have more than one extension, choose which phone should ring.

## Settings

Right-click the Veyra icon and choose **Options** for:

- the outside-line prefix,
- which notifications you get,
- **Handle phone links**, so clicking a `tel:` link on a web page calls through Veyra instead of opening another app,
- your speed dials.

Settings are saved to your Veyra account, so they follow you to another computer.

## If something doesn't work

- **"Cannot reach the server" or a certificate error:** the computer does not trust the Veyra server's certificate. Ask your administrator. They can fix it for everyone.
- **The phone does not ring:** check on [My Phone](app:/my-phone/) that the phone is registered and that Do Not Disturb is off.
