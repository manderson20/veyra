---
title: Your account and sign-in security
summary: Change your password, set up a passkey or an authenticator app, keep your recovery codes, and sign out devices you no longer use.
audience: user
section: Using Veyra
order: 30
reviewed: 0.27.44
pages:
  - /account/
covers:
  - frontend/src/app/(app)/account/*
  - frontend/src/components/account/PasswordFields.tsx
  - frontend/src/components/account/TwoFactorCard.tsx
  - frontend/src/components/account/TotpEnrolment.tsx
  - frontend/src/components/account/PasskeyEnrolment.tsx
  - frontend/src/components/account/TrustedBrowsersCard.tsx
  - frontend/src/components/account/SessionsTable.tsx
  - frontend/src/components/account/MissedCallEmailCard.tsx
  - backend/veyra/api/v1/auth.py
  - backend/veyra/api/v1/auth_mfa.py
  - backend/veyra/core/security/passwords.py
---

Your account page holds your sign-in settings. Open it from the menu with your name in the top bar, or go to [your account](app:/account/).

The **Profile** card shows your name, email address, how you sign in, whether two-factor authentication is on, and when you last signed in. Your name and email address are changed by an administrator.

## Change your password

> **Note:** If you sign in with **Sign in with Google** or **Microsoft**, you have no separate Veyra password: change your password with Google or Microsoft instead.

In **Change password**:

1. Enter your **Current password**.
2. Enter the **New password** twice. It needs at least 12 characters and must not contain your name or email address. A short sentence or a few unrelated words is easiest to remember.
3. Choose **Change password**.

Your other sessions are signed out, and browsers you trusted must enter the second step again.

**Forgot your password?** On the sign-in page, choose **Forgot your password?** and enter your email address; you get an email with a link to choose a new one.

## Two-factor authentication

With two-factor authentication, signing in needs your password **and** something you have: a **passkey** (your fingerprint, face, device PIN or a security key) or a 6-digit code from an **authenticator app** on your phone. Someone who learns your password still cannot sign in.

The **Two-factor authentication** card says whether it is **On** and whether your role requires it. If it is required, set it up before the date shown, or you will not be able to sign in.

### Add a passkey

1. Choose **Add a passkey**.
2. Give it a **Name**, for example *Work laptop Touch ID*.
3. Choose **Create passkey** and confirm with your fingerprint, face, device PIN or security key when the browser asks. Nothing biometric leaves your device.

If the browser refuses, Veyra must be opened by its host name with a certificate your computer trusts; ask your administrator, or use an authenticator app instead.

### Add an authenticator app

1. Choose **Use an authenticator app** (or **Add an authenticator app** if two-factor is already on).
2. Open an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy, 1Password and others work), add an account and scan the code. If you cannot scan, choose **Can't scan? Enter the key by hand**.
3. Optionally **Name this device**, enter the **Code from the app** and choose **Verify and enable**.

### Recovery codes

When you turn on two-factor authentication, Veyra shows 10 **recovery codes** once. **Download** or copy them and keep them somewhere safe, not on your phone. Each code signs you in once if you lose your phone or security key: on the sign-in page, choose **Lost your device? Use a recovery code**.

The card shows how many codes are left. **New codes** replaces them all (your old ones stop working).

### Manage your devices

Each passkey and authenticator app is listed with when it was added and last used. Rename it or remove it with the buttons on its row. Removing your only device turns two-factor authentication off. Removing a device or making new codes asks for your password again.

## Trusted browsers

At the second step of signing in, you may tick **Trust this browser for … days**. That browser then signs you in with the password only until the date shown. The **Trusted browsers** card lists them: forget one you no longer use, or **Forget all** if a computer was lost. Changing your password also forgets them.

## Active sessions

**Active sessions** lists everywhere you are signed in, with the **Device**, when you **Signed in**, when you were **Last active**, and when the session **Expires**. Sessions end after 12 hours, or after 60 minutes without activity.

- **Sign out** ends one session, for example on a shared computer you forgot to sign out of.
- **Sign out other sessions** ends all of them except the one you are using.

The browser extension has its own list: see **Connected apps** in [Use the Companion extension](guide:companion-for-users).

## Missed-call emails

Under **Missed calls**, turn on **Email me about missed calls** to get one email for each call to your phone that nobody answered. Calls that went to voicemail send the voicemail email instead.

## Voicemail

The **Voicemail** card lets you change your voicemail PIN and greeting keys: see [Your voicemail](guide:your-voicemail).
