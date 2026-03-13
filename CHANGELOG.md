# Changelog

All notable changes to this project are documented in this file.

## [0.2.2] - 2026-03-13

### Added
- Company knowledge loader from local files (`knowledge/company/*.md|*.txt`) and AI-context transfer.
- Starter knowledge documents with product and implementation scope.
- New tests for 100-message history window and company knowledge transfer.

### Changed
- Context window increased to 100 latest messages per lead (`HISTORY_WINDOW_MESSAGES=100` by default).
- Booking flow switched to "when is convenient for you" format; bot asks for date and time from client.
- Booking parser now accepts numeric date/time from user text (`ДД.ММ ЧЧ:ММ`) and stores consultation time.
- Prompt contract upgraded to `v4` with explicit behavior for product context and booking dialogue.

## [0.2.1] - 2026-03-13

### Changed
- Greeting scenario rewritten to a human-style sales opener without irrelevant "implementation options" list.
- Guided funnel logic added to enforce one-step progression through qualification and prevent premature price jumps.
- Price disclosure behavior tightened: price is allowed on direct request or later funnel stages, not early in discovery.
- Qualification data handling improved with key normalization and text-based extraction for non-structured user replies.

### Fixed
- Scenario where user says "давайте" after discussing pain points no longer jumps directly to price.
- Added targeted unit tests for anti-price-jump behavior and direct price request handling.
- Follow-up worker now skips non-Telegram dialogs to avoid delivery retries with invalid chat targets.

## [0.2.0] - 2026-03-12

### Added
- Follow-up engine with reminders at +2h, +24h and +72h, including sending-window control (11:00-20:00, Moscow time).
- Consultation slot generation (11:00-17:00, 30-minute slots) and booking confirmation workflow.
- Telegram admin notifications for new bookings and handoff requests.
- Lead state fields for qualification data, follow-up status, stop mode, booking slot and handoff flag.
- Stop-phrase flow that pauses outreach and allows reactivation when client writes again.
- New unit tests for stop/reactivation, booking/admin notifications, scheduling, and follow-up worker.

### Changed
- Prompt and AI contract upgraded to `v2` with strict sales behavior rules and richer structured output.
- Message processing logic now persists richer sales context and delegates more decisions to LLM.
- Lead stage policy now keeps only `booked` as terminal to allow recovery after stop.
- Telegram polling worker now also runs follow-up dispatch.
- Project version bumped from `0.1.0` to `0.2.0`.
