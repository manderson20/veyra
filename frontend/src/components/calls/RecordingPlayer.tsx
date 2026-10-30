// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Icon } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE } from "@/lib/api";

/** Plays a call recording from the API (each listening is audited) with a download link. */
export function RecordingPlayer({ id }: { id: string }) {
  const src = `${API_BASE}/recordings/${encodeURIComponent(id)}/audio`;
  return (
    <div className="stack stack--sm">
      <audio controls preload="none" src={src} style={{ width: "100%" }}>
        Your browser cannot play Ogg Opus audio; download the file instead.
      </audio>
      <div><a className={buttonClass("secondary", "sm")} href={`${src}?download=true&format=mp3`} download><Icon name="download" size={14} /> Download MP3</a></div>
      <p className="subtle" style={{ margin: 0 }}>Listening and downloading are written to the audit log.</p>
    </div>
  );
}
