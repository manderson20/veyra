---
title: Manage audio and hold music
summary: Record prompts from a phone, upload audio, add Veyra's built-in sounds, and build hold music sets.
audience: admin
section: Calls and call flows
order: 70
reviewed: 0.27.44
pages:
  - /prompts/
  - /hold-music/
covers:
  - frontend/src/app/(app)/prompts/*
  - frontend/src/app/(app)/hold-music/*
  - frontend/src/components/holdmusic/HoldMusicSelect.tsx
  - backend/veyra/api/v1/prompts.py
  - backend/veyra/api/v1/hold_music.py
  - backend/veyra/telephony/audio.py
---

Every recording callers hear lives in the organization's audio library: menu greetings, announcements, bells, voicemail greetings and hold music. You fill the library in three ways: record from a phone, upload a file, or copy one of Veyra's built-in sounds. Hold music *sets* then group music recordings into what callers hear on hold.

You need permission to change IVR menus, announcements and prompts (organization and site administrators by default).

## Record a prompt from a phone

A desk phone records clearer speech than most laptop microphones, and nothing has to be converted.

1. From any phone, dial `*95`.
2. After the tone, speak. Press `#` when you are done. A recording stops by itself after 5 seconds of silence or 5 minutes.
3. The phone plays the recording back. Press `1` to keep it, `2` to listen again, or `3` to record it again.
4. Open [Telephony → Audio](app:/prompts/). The recording is listed under **Recordings from phones** with the time and the extension it came from. Use the play button to listen.
5. Choose **Name and keep**, enter a **Name** (for example *After-hours greeting*) and optionally a **Description**, then **Create prompt**. Or discard it with the bin button.

The new prompt is now in the library list above and can be chosen in menus and announcements.

## Upload a file

1. On [Telephony → Audio](app:/prompts/), choose **Upload audio**.
2. Enter a **Name** and choose the **Kind**: **Menu prompt**, **Bell**, **Announcement**, **Greeting** or **Hold music**. The kind sorts the library; hold music sets offer recordings of the kind *Hold music* first.
3. Optionally enter a **Description**, a **Licence** (where the rights come from, for example *CC0* or *own recording*) and a **Credit**.
4. Choose the **Audio file** and **Upload**.

Veyra accepts WAV files, and MP3, OGG, FLAC and M4A when ffmpeg is installed on the server. A file can be at most 5 minutes long. It is converted to the format phones play (8 kHz mono).

## Built-in sounds

The **Built-in sounds** card lists bells, chimes, attention tones and hold music made by Veyra and free to use. Play one with its play button, and choose **Add to library** to copy it into the organization's library (with several organizations, first choose which one). After that, bell schedules, pages and menus can use it.

## Change or replace a recording

Choose **Edit** next to a recording to change its **Name** or **Description**, or to **Replace the audio** with a new file. The new audio plays at once wherever the recording is used; menus and announcements keep pointing at it, and no deployment is needed for the replaced sound.

A recording that a menu, an announcement or a hold music set uses cannot be deleted; the **Used by** column shows how many use it. Change those first.

> **Tip:** to change a greeting that was recorded from a phone, record the new one with `*95`, name it, choose it as the menu's **Menu prompt** (or the announcement's **Recording to play**) and deploy.

## Hold music sets

Callers on hold, waiting in a queue, waiting alone in a conference room, or ringing a ring group set to play music hear a hold music set. Anything without a set plays Veyra's built-in music, which needs no licence.

1. Upload or add the music to the library first, with the kind **Hold music**.
2. Open [Telephony → Hold Music](app:/hold-music/) and choose **New hold music set**.
3. Enter a **Name** and optionally a **Description**.
4. Choose the **Source**:
   - **Recordings from the audio library**: choose each recording and click **Add**, up to 50, and order them with the arrows. Tick **Offer every recording, not only those marked as hold music** to see other kinds. Tick **Shuffle** to play them in random order.
   - **An internet radio stream**: enter the **Stream address** (an `http://` or `https://` address of an MP3, AAC or Ogg station). The server needs ffmpeg. The recordings you add are played as a fallback while the station cannot be reached.
5. Choose **Create set**, then **Deploy changes** in the top bar.

Then choose the set where it should play:

- for calls put on hold, as the organization's default set on its page under [Directory → Organizations](app:/organizations/);
- for a queue or ring group, in its **Hold music set** field;
- for a conference room, in **Hold music while waiting alone**.

> **Warning:** commercial music and radio stations played to callers usually need a public performance licence, and a station may also need to give permission. Veyra's built-in music and Creative Commons or public-domain recordings do not. The licence you enter with each upload is shown in the set.

A set that a queue, ring group or organization uses cannot be deleted until they are changed. The recordings stay in the library when a set is deleted.

## When it does not work

- **No recording appears under Recordings from phones**: the recording was not kept (press `1` after listening), or it was made in another organization (choose the organization filter).
- **The upload is refused**: the file is longer than 5 minutes, too large, or in a format the server cannot convert without ffmpeg. Convert it to WAV and try again.
- **A set shows a warning**: it has no recordings, a recording's file is missing, or ffmpeg is not installed for a stream.
- **Callers still hear the old music**: deploy the changes.
