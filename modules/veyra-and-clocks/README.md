# AND Clock Messages (`veyra.and-clocks`)

Text messages and alerts on Advanced Network Devices (AND) IP clocks and
signs, in the spirit of AND's Clockwise software: to every clock, a group
(a building, a wing) or one clock; now or at a set time; with colour,
flasher lights, a priority and a display time; and automatically with the
bells. Design: [docs/PAGING_RECORDINGS.md](../../docs/PAGING_RECORDINGS.md) §6.

The module is optional. Install it under **Modules** only where the clocks
exist; uninstalling it keeps its data unless you purge it.

## 1. Prepare the clocks

On each clock's web page (or in the clocks' configuration file):

* **Device Settings → Servers → Misc Server Options → Allow inline text
  commands with InformaCast = Yes** (configuration file:
  `<display allow_inline_commands_shorttext="1" />`). Veyra sets colour and
  flashers with AND's inline commands (application note AN049); without
  this setting they appear as text.
* Note the clock's IP address (a DHCP reservation keeps it stable) and the
  **HTTP Control Password** if one is set.

## 2. Describe how a clock takes a message (Modules → Clock Delivery)

AND does not publish an interface for other senders; the clock's own web
page posts the message to the clock. Capture that request once and enter it
here; Veyra then fills it in for every clock.

1. On a computer on the clocks' network, open one clock's web page and go
   to the page where a text message can be sent.
2. Open the browser's developer tools (F12) on the **Network** tab.
3. Send a short test message from the clock's page.
4. Click the request that appeared (usually a `POST`). Note the **method**,
   the **path** (the part of the address after the clock's address), the
   **request body** (Payload) and whether the browser asked for a user name
   and password (basic or digest sign-in).
5. In Veyra, **Clock Delivery → New**: enter the method and path, choose the
   body type (`form` for `a=1&b=2` bodies) and paste the body, replacing
   the message you typed with `{text}` (and the password, if it appears in
   the body, with `{password}`).

| Placeholder | Becomes |
|---|---|
| `{text}` | The message with AND inline commands for colour and flashers, e.g. `{color=red;flashers=FFF}Lockdown` |
| `{plain_text}` | The message without commands |
| `{xml}` | An AND `IPSpeakerMessage` document (application note AN050) with priority and display time |
| `{color}`, `{seconds}`, `{priority}`, `{flashers}` | The individual settings (priority 1 = highest … 100) |
| `{password}` | The stored clock password |

Values are escaped for the body type (form, XML, JSON) and in the path.
`POST /api/v1/ext/and-clocks/delivery/preview` with a message shows the
request one clock would receive (password masked). Saving the delivery
setup again replaces it; a blank password keeps the stored one.

If you share the capture for help, remove the password and anything that
identifies your site first.

## 3. Use it

* **Clocks**: add each clock by address, with a **group** (for example a
  building) to send to all its clocks at once. Reachability is checked
  every few minutes (TCP to the web port).
* **Clock Messages → New**: the message, who it goes to (blank or `all`, a
  group or a clock name), colour, display time (0 = until replaced),
  priority (normal, high, emergency; a clock ignores lower-priority
  messages while a higher one shows) and flashers. Leave **Send at** blank
  to send now or enter `YYYY-MM-DD HH:MM` in the organization's time zone.
  The list shows scheduled messages first, then the log with the result
  per message; deleting a scheduled message cancels it.
* **Clock Bell Messages**: when a bell schedule rings (by name, `*` for
  all), show text on the clocks; `{summary}` is the calendar event's name
  ("Period 2").

Scheduled and bell messages are sent by the `veyra-worker` service within
a few seconds; a scheduled message missed by more than an hour (server
down) is logged as not sent rather than shown late.

## Permissions

| Permission | Default roles | Allows |
|---|---|---|
| `and_clocks.read` | org admin, site admin, technician, read only | View clocks, messages and the log |
| `and_clocks.send` | org admin, site admin | Send, schedule and cancel messages |
| `and_clocks.write` | org admin | Clocks, bell messages, delivery setup |

## Not yet

Editing rows in place (delete and add again), clock models with HD images
or countdown timers, pixmaps, and InformaCast compatibility.
