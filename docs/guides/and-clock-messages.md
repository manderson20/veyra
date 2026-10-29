---
title: Show messages on AND clocks
summary: Send text messages and alerts to Advanced Network Devices (AND) IP clocks and signs, now, later or with the bells.
audience: admin
section: Paging and bells
order: 40
reviewed: 0.27.44
covers:
  - modules/veyra-and-clocks/module.toml
  - modules/veyra-and-clocks/README.md
  - modules/veyra-and-clocks/backend/*
---

If your buildings have Advanced Network Devices (AND) IP clocks or message signs, the optional **AND Clock Messages** module lets Veyra put text on them: to every clock, to a group such as a building, or to one clock; now or at a set time; and automatically when a bell rings (for example *Period 2*).

The module is not part of every installation. Install it only where these clocks exist.

> **Warning:** Clock messages are not a life-safety notification system. Use them for information and drills alongside your fire alarm, not instead of it.

## Install the module

1. Open [System → Module Manager](app:/modules/).
2. Find **AND Clock Messages** and choose **Install**, then **Enable** if it is not enabled yet.
3. The module adds four pages to the **Modules** menu: **Clock Messages**, **Clocks**, **Clock Bell Messages** and **Clock Delivery**.

Organization administrators can manage everything; site administrators can send messages; technicians and read-only users can look.

## 1. Prepare the clocks

On each clock's own web page:

- Turn on **Allow inline text commands with InformaCast** (under the clock's server settings). Veyra sets colour and flashers with these commands; without the setting they appear as text on the clock.
- Note the clock's IP address (a DHCP reservation keeps it stable) and its HTTP control password, if one is set.

## 2. Describe how a clock takes a message (Clock Delivery)

AND does not publish a way for other systems to send messages, so Veyra copies what the clock's own web page does. You capture that once:

1. On a computer on the clocks' network, open one clock's web page and go to the page that sends a text message.
2. Press **F12** to open the browser's developer tools and choose the **Network** tab.
3. Send a short test message from the clock's page.
4. Click the request that appeared (usually a POST). Note the method, the path (the part of the address after the clock's address), the request body (*Payload*) and whether the browser asked for a user name and password.
5. In Veyra, open **Clock Delivery** and choose **Add**. Enter the **Method**, **Protocol** and **Path**, choose the **Body type** (*form* for bodies like `a=1&b=2`), and paste the body as the **Body template**. In the body, replace the message you typed with `{text}`, and the password, if it appears, with `{password}`.
6. Set **Sign-in** (none, basic or digest), the **User name** and the **Clock password**. The password is stored encrypted.

Other placeholders you can use: `{plain_text}` (the message without colour commands), `{xml}` (an AND XML message with priority and display time), `{color}`, `{seconds}`, `{priority}` and `{flashers}`. Saving the delivery setup again replaces it.

Until delivery is set up, messages are kept but not sent.

## 3. Add the clocks

In **Clocks**, choose **Add** for each clock: a **Name**, its **Address** (IP address or host name, optionally with `:port`), a **Group** such as the building, and the **Model**. Veyra checks every few minutes whether each clock is reachable and shows it in the **Reachable** column.

## Send a message

In **Clock Messages**, choose **Add**:

| Field | What to enter |
|---|---|
| **Message** | Up to 1,000 characters. |
| **Send to** | Blank or `all` for every clock, or the name of a group or of one clock. |
| **Colour** | The text colour. |
| **Show for (seconds)** | Default 60. 0 keeps the message until another one replaces it. |
| **Priority** | normal, high or emergency. A clock showing a higher-priority message ignores lower ones until it ends. |
| **Flashers** | For clocks with flasher lights. |
| **Send at** | Blank sends now. Or `YYYY-MM-DD HH:MM` in the organization's time zone. |

The list shows each message with its **Status** and **Result**. Deleting a scheduled message cancels it. A scheduled message that could not be sent within an hour of its time (for example, the server was down) is logged as not sent rather than shown late.

> **Tip:** Send a short test message to one clock first.

## Messages with the bells

In **Clock Bell Messages**, choose **Add** to show text whenever a [bell schedule](guide:bell-schedules) rings:

- **Bell schedule**: the schedule's name, or `*` for every schedule.
- **Text**: `{summary}` (the default) is the calendar event's name, such as *Period 2*.
- **Send to**, **Colour** and **Show for (seconds)** as for messages.

## If messages do not appear

- **Reachable** shows a problem: check the address and that the server can reach the clock's network.
- The result shows an error from the clock: compare the **Clock Delivery** setup with a new capture from the clock's web page, especially the path and the sign-in.
- Colour codes appear as text: turn on the inline text commands setting on the clock.
