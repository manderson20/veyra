// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "recording" | "done" | "unsupported" | "denied";

/**
 * Record from the microphone with MediaRecorder, up to `maxSeconds`: start,
 * stop, a preview URL and the recording. The microphone is released on stop
 * and on unmount.
 */
export function useRecorder(maxSeconds: number) {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number | null>(null);

  const stop = () => {
    if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
    const r = recorder.current;
    if (r && r.state !== "inactive") r.stop();
    r?.stream.getTracks().forEach((t) => t.stop());
  };
  const reset = () => {
    stop();
    recorder.current = null;
    chunks.current = [];
    setSeconds(0);
    setBlob(null);
    if (url) URL.revokeObjectURL(url);
    setUrl(null);
    setState("idle");
  };
  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    const r = recorder.current;
    if (r && r.state !== "inactive") r.stop();
    r?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  const start = async () => {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) { setState("unsupported"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m));
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      r.onstop = () => {
        const b = new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
        setBlob(b);
        setUrl(URL.createObjectURL(b));
        setState("done");
      };
      recorder.current = r;
      r.start(250);
      setSeconds(0);
      setState("recording");
      timer.current = window.setInterval(() => setSeconds((s) => {
        if (s + 1 >= maxSeconds) stop();
        return s + 1;
      }), 1000);
    } catch {
      setState("denied");
    }
  };

  return { state, seconds, blob, url, start, stop, reset };
}

/** A recording as base64 (no data: prefix), for JSON bodies. */
export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
