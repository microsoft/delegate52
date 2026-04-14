# <img src="../assets/domain_icons/calendar.svg" width="28" height="28" style="vertical-align: middle;"> Calendar

**Category:** Structured Records
**File format:** `.ics`
**Summary:** iCalendar (.ics) files with events, schedules, and conference sessions
**Work environments released:** 2 / 5

iCalendar files use the standard [iCalendar (RFC 5545)](https://datatracker.ietf.org/doc/html/rfc5545) format for representing calendar events. Each VEVENT contains a UID, start/end times, summary, categories (track/devroom), and location. This domain tests an LLM's ability to manipulate structured scheduling data — splitting by topic or venue, converting between formats, adjusting timezones, and performing constraint-based filtering across dozens of events.

**Domain implementation:** [`domain_calendar.py`](../domains/domain_calendar.py)

---

## Evaluation

The calendar domain evaluator parses iCalendar transformations using the `icalendar` library and scores reconstruction quality across four dimensions:

- **Event coverage** — Are all original events present? (Uses UID-based matching)
- **Field accuracy** — Are start/end times, summaries, and locations preserved correctly?
- **Ordering** — Are events in the correct chronological sequence?
- **Category preservation** — Are track/devroom categories intact?

**Score formula:** `coverage² × accuracy × √((ordering + category) / 2)`

---

## Example Work Environment: `calendar1`

**Document:** FOSDEM 2025 Schedule
**Source:** [fosdem.org/2025/schedule/ical](https://fosdem.org/2025/schedule/ical) (CC-BY-2.0-BE License)
**Size:** 459 lines · 3,934 tokens

### Seed Document Excerpt (`calendar.ics`)

```text
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Pentabarf//Schedule 0.3//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALDESC;VALUE=TEXT:iCal
X-WR-CALNAME;VALUE=TEXT:iCal
X-WR-TIMEZONE;VALUE=TEXT:Europe/Brussels
BEGIN:VEVENT
UID:4426@fosdem-2025@fosdem.org
DTSTART:20250202T100000
DTEND:20250202T102500
SUMMARY:API Scoring - The Secret Weapon in the Battle for API Excellence
CATEGORIES:APIs: GraphQL, OpenAPI, AsyncAPI, and friends
LOCATION:K.4.201
END:VEVENT

BEGIN:VEVENT
UID:6213@fosdem-2025@fosdem.org
DTSTART:20250202T090000
DTEND:20250202T093000
SUMMARY:Welcome from the OpenWallet Foundation
CATEGORIES:Digital Wallets and Verifiable Credentials
LOCATION:AW1.126
END:VEVENT

BEGIN:VEVENT
UID:4705@fosdem-2025@fosdem.org
DTSTART:20250202T090000
DTEND:20250202T094000
SUMMARY:Toward a unified abstract content API
CATEGORIES:Open Media
LOCATION:K.3.401
END:VEVENT

BEGIN:VEVENT
UID:5930@fosdem-2025@fosdem.org
DTSTART:20250202T100000
DTEND:20250202T103000
SUMMARY:Hunting Virtio Specification Violations
CATEGORIES:Virtualization and Cloud Infrastructure
LOCATION:UB4.132
END:VEVENT

BEGIN:VEVENT
UID:6724@fosdem-2025@fosdem.org
DTSTART:20250202T091000
DTEND:20250202T092000
SUMMARY:An Introduction to the Open Source AI definition
CATEGORIES:Open Source In The European Legislative Landscape and Beyond
LOCATION:AW1.120
END:VEVENT
```
<sup>Showing 50 of 459 lines. The full calendar contains 100 FOSDEM 2025 events spanning two days across multiple buildings and tracks.</sup>

---

### Edit Tasks (8 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Topic Split** | Organize the calendar into 3 files based on interest in systems programming: `mustgo.ics`, `maybe.ics` if tangentially related, and `skip.ics` for everything else. | Merge all three calendars back into a single `calendar.ics` file, sorted chronologically by start time. | split & merge, topic modeling, sorting |
| 2 | **JSON Conversion** | Convert to `schedule.json` using a legacy display schema: `cal_meta` (version, prodid, etc.) and `events` array (id, t_start, t_end, title, track, room). | Convert the JSON schedule back to iCalendar format as `calendar.ics`. | format knowledge |
| 3 | **Building Split** | Split into separate calendars by building: `k_building.ics`, `h_building.ics`, `aw_building.ics`, `ua_building.ics`, `ub_building.ics`, `ud_building.ics`. | Merge all the building calendars into a single `calendar.ics`, ordered by start time. | split & merge, classification, sorting |
| 4 | **Timezone Conversion** | Convert all times to IST for remote attendance from India. Keep the file as `calendar_ist.ics`. | Convert times to Brussels local time since I'll be checking the schedule on-site. Save as `calendar.ics`. | numerical reasoning |
| 5 | **Duration Split** | Split into `quick-talks.ics` for talks 25 minutes or shorter and `sessions.ics` for longer talks that need more commitment. | Merge into a single conference calendar `calendar.ics`, sorted by start time. | split & merge, classification, sorting |
| 6 | **Availability Filter** | Given a list of unavailable time slots (team call, standups, design review, etc.), split into `compatible.ics` for fully attendable events and `conflict.ics` for overlapping ones. | Combine `compatible.ics` and `conflict.ics` into a single `calendar.ics`, sorted chronologically by start time. | split & merge, constraint satisfaction, sorting |
| 7 | **Track Tagging** | Prepend the track name in square brackets to each SUMMARY (e.g., `[Kernel] Macros Gone Wild...`), then replace all CATEGORIES with `FOSDEM 2025`. Save as `tagged_schedule.ics`. | Extract bracketed track names from SUMMARY, move them back into CATEGORIES, and strip the bracket prefix. Save as `calendar.ics`. | string manipulation |
| 8 | **Track Grouping** | Reorder events grouped by CATEGORIES (track/devroom), sorted alphabetically. Add `X-ORIG-SEQ` for position tracking. Normalize LOCATION by splitting room names into `X-ROOM-NAME`. Save as `grouped_schedule.ics`. | Sort events by `X-ORIG-SEQ`, merge `X-ROOM-NAME` back into LOCATION, and remove all custom X- properties. Save as `calendar.ics`. | sorting, string manipulation |
