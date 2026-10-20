// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Passkeys in the browser (issue #107): turn the server's options (JSON with
 * base64url fields, py_webauthn's `options_to_json`) into the arguments of
 * `navigator.credentials.create/get`, and the resulting credential back into
 * JSON the server verifies.
 */

type Json = Record<string, unknown>;

function fromB64u(s: string): ArrayBuffer {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function toB64u(buf: ArrayBuffer | null | undefined): string | null {
  if (!buf) return null;
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Why passkeys cannot work on this page, or null when they can. */
export function passkeyUnavailableReason(): string | null {
  if (typeof window === "undefined") return "Not in a browser.";
  if (!window.isSecureContext) return "Passkeys need a secure (https) page with a trusted certificate.";
  if (!("PublicKeyCredential" in window)) return "This browser does not support passkeys.";
  if (/^\d{1,3}(\.\d{1,3}){3}$|^\[/.test(window.location.hostname)) {
    return "Passkeys need the server's name in the address bar, not its IP address.";
  }
  return null;
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return list.map((d: Json) => ({ ...d, id: fromB64u(String(d.id)) }) as PublicKeyCredentialDescriptor);
}

function serialize(cred: PublicKeyCredential): Json {
  const r = cred.response as AuthenticatorAttestationResponse & AuthenticatorAssertionResponse;
  const response: Json = { clientDataJSON: toB64u(r.clientDataJSON) };
  if ("attestationObject" in r && r.attestationObject) {
    response.attestationObject = toB64u(r.attestationObject);
    response.transports = typeof r.getTransports === "function" ? r.getTransports() : [];
  }
  if ("authenticatorData" in r && r.authenticatorData) {
    response.authenticatorData = toB64u(r.authenticatorData);
    response.signature = toB64u(r.signature);
    response.userHandle = toB64u(r.userHandle);
  }
  return {
    id: cred.id,
    rawId: toB64u(cred.rawId),
    type: cred.type,
    response,
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
  };
}

/** Create a passkey from registration options. */
export async function createPasskey(options: Json): Promise<Json> {
  const user = options.user as Json;
  const publicKey = {
    ...options,
    challenge: fromB64u(String(options.challenge)),
    user: { ...user, id: fromB64u(String(user.id)) },
    excludeCredentials: descriptors(options.excludeCredentials),
  } as unknown as PublicKeyCredentialCreationOptions;
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was created.");
  return serialize(cred);
}

/** Sign with a passkey from authentication options. */
export async function getPasskey(options: Json): Promise<Json> {
  const publicKey = {
    ...options,
    challenge: fromB64u(String(options.challenge)),
    allowCredentials: descriptors(options.allowCredentials),
  } as unknown as PublicKeyCredentialRequestOptions;
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was used.");
  return serialize(cred);
}

/** A cancelled or timed-out browser prompt, as words for the user. */
export function passkeyErrorText(err: unknown): string | null {
  if (err instanceof DOMException) {
    if (err.name === "NotAllowedError") return "The passkey prompt was cancelled or timed out.";
    if (err.name === "InvalidStateError") return "This passkey is already registered.";
    if (err.name === "SecurityError") return "This address cannot use passkeys (it needs the server's name and a trusted certificate).";
  }
  return null;
}
