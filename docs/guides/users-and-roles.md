---
title: Add users and give them roles
summary: Create accounts for the people who sign in to Veyra, give them roles, and help them when they are locked out.
audience: admin
section: Getting started
order: 40
reviewed: 0.27.44
pages:
  - /users/
  - /users/view/
covers:
  - frontend/src/app/(app)/users/*
  - frontend/src/app/(app)/users/view/*
  - backend/veyra/api/v1/users.py
  - backend/veyra/core/security/permissions.py
  - backend/veyra/core/security/passwords.py
---

A **user** is a person who signs in to Veyra: an administrator, a technician, or a staff member who checks their voicemail and changes their forwarding on My Phone. A user is not the same as an extension. You create the user here, then assign them to an extension (see [Add extensions](guide:extensions)).

What a user may do depends on their **roles**. A user without a role can sign in but sees nothing.

> **Tip:** If your school or company uses Google Workspace or Microsoft 365, set up [single sign-on](guide:single-sign-on) as well. People then sign in with their work account instead of a Veyra password.

## The roles

| Role | What it is for |
|---|---|
| **Platform Administrator** | Full control of this Veyra installation and every organization on it. |
| **Organization Administrator** | Manages users, telephony and devices within an organization. |
| **Site Administrator** | Manages extensions and devices at a site. |
| **Technician** | Maintains devices and views telephony configuration. |
| **Standard User** | Self-service access to their own phone and voicemail. |
| **Read-Only User** | Can view, but not change, configuration. |

Every role except Platform Administrator is given for one organization. Only a platform administrator can give the Platform Administrator role.

> **Note:** The **Assign role** dialog gives every role for a whole organization, including Site Administrator. It does not yet offer to limit a role to one site.

## Add a user

1. Open [Directory → Users](app:/users/) and choose **New user**.
2. Enter the **Full name** and **Email address**. The email address is what they sign in with, and it cannot be changed later.
3. Enter an **Initial password** of at least 12 characters. It is temporary: the user must choose their own at the first sign-in. Give it to them over a channel you trust.
4. Choose the **Organization**. A platform administrator can leave it empty for a platform-level account.
5. Choose **Create user**. Veyra opens the new user's page.
6. Under **Roles**, choose **Assign role**. Pick the **Role** and the **Organization**, then **Assign role**.

Veyra may ask for your password again before it assigns a role. This protects against someone using a computer you left signed in.

Veyra refuses passwords that contain the person's name or email address, have fewer than four different characters, or are a common word repeated.

## The user's page

Choose a user in the list to open their page.

- **Profile:** change the **Full name**, or switch **Account enabled** off. Disabling an account signs the person out everywhere; you cannot disable your own.
- **Account:** the sign-in method, the last sign-in, the password's state, whether two-factor sign-in is on, and whether the account is locked.
- **Roles:** the roles the user holds. Use the bin icon to remove one. At least one platform administrator must remain.
- **Sign-in:** accounts at sign-in providers (single sign-on) linked to this user. **Unlink** removes the link.
- **Active sessions:** where the account is signed in. **Sign out everywhere** ends them all without changing the password.
- **Connected apps (Companion):** browsers where the person signed in to the Companion extension.

## When someone is locked out

**They forgot their password.** Choose **Reset password** at the top of their page. Then pick one:

- **Create a one-time reset link** (recommended). Veyra shows a link that works once and expires. Choose **Copy link** and send it to the person. The link is shown only once.
- **Set a password now.** Enter a **New password**. It is temporary unless you switch on **Permanent password**.

Either way the person is signed out everywhere and any lockout is cleared. People can also use *Forgot password* on the sign-in page themselves, if email delivery is set up.

**Their account is locked** after too many failed sign-ins. The **Account** card says *Locked* until a certain time. Choose **Unlock now**.

**They lost the phone with their authenticator app.** Next to **Two-factor**, choose **Reset**, then **Reset two-factor**. Their authenticator devices and recovery codes are removed and they are signed out. They set up a new one at their next sign-in.

> **Note:** You cannot reset your own password or second factor here. Use your account page. If the last platform administrator loses their second factor, run `veyra users mfa-reset` on the server.

## If something doesn't work

- **"A user with this email address already exists":** each email address can belong to only one user. Search the list for it; the account may be disabled.
- **The user signs in but sees nothing:** they have no role. Assign one.
- **"Choose the user's organization":** only a platform administrator can create a user without an organization.
- **You cannot see the Roles card or the Assign role button:** your own role does not include managing roles. Ask an organization or platform administrator.
