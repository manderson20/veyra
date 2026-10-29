---
title: Pick up a colleague's ringing phone
summary: Let people answer a call ringing on a nearby phone with *8 or ** and the extension, and set who may do it.
audience: admin
section: Calls and call flows
order: 30
reviewed: 0.27.44
pages:
  - /pickup-groups/
covers:
  - frontend/src/app/(app)/pickup-groups/*
  - frontend/src/components/groups/PickupGroupDialog.tsx
  - backend/veyra/api/v1/pickup_groups.py
---

When a phone rings at an empty desk, a colleague can answer the call from their own phone. There are two ways:

| Dial | What it answers |
|---|---|
| `*8` | Any call ringing on a phone in the same pickup group |
| `**` and the extension, for example `**2001` | The call ringing on that one phone |

These two codes are fixed and cannot be changed under Feature Codes.

## Who may pick up

- `*8` only works between phones in the same **pickup group**. A phone that is in no pickup group cannot use it.
- `**` and an extension works between any two phones of the organization, unless the organization is set to allow it only within pickup groups. That setting is on the organization's page under [Directory → Organizations](app:/organizations/), **Answer another phone's call**: **Any phone of the organization** or **Only phones in the same pickup group**. A change there needs a deployment.

## Create a pickup group

You need permission to change ring groups, queues and pickup groups. Organization and site administrators have it by default.

1. Open [Telephony → Pickup Groups](app:/pickup-groups/) and choose **New pickup group**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Front office*, and optionally a **Description**.
4. Under **Members**, choose each extension and click **Add**. A group has at most 64 members. An extension can be in several pickup groups.
5. Choose **Create group**.
6. Choose **Deploy changes** in the top bar.

Group the phones that sit together and cover for each other: an office, a wing, a reception desk and its back office.

A group needs at least two members to be useful; the **Status** column warns when it has fewer.

## Change or delete a group

- Click a group, or its **Edit** button, to change its name or members, then **Save changes** and deploy.
- The bin button deletes the group. Its members can no longer pick up each other's calls with `*8` after the next deployment.

## When it does not work

- **`*8` does nothing**: the two phones are not in the same pickup group, or the change has not been deployed. `*8` only picks up a call that is ringing right now.
- **Directed pickup does nothing** (`**` and the extension): the organization may allow it only within pickup groups (see above), or the phone belongs to another organization.
- **Ring groups**: phones ringing because of a ring group can be picked up the same way. The group's own number cannot be picked up; pick up one of its ringing member phones.
