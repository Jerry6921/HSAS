import AppKit
import EventKit
import Foundation
import Darwin
import CoreLocation

// This helper only touches namespaced HIQS items in the configured containers.
// User completion, priority, alarms and text outside our notes block are owned
// by the user. Python supplies the deterministic, source-grounded plan.
struct BridgeError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

func string(_ value: [String: Any], _ key: String) throws -> String {
    guard let result = value[key] as? String, !result.isEmpty else { throw BridgeError("missing_" + key) }
    return result
}

func calendar(_ zone: String) throws -> Calendar {
    guard let timezone = TimeZone(identifier: zone) else { throw BridgeError("invalid_timezone") }
    var value = Calendar(identifier: .gregorian)
    value.timeZone = timezone
    return value
}

func date(_ value: String, _ zone: String) throws -> Date {
    if value.count == 10 {
        let formatter = DateFormatter()
        formatter.calendar = try calendar(zone)
        formatter.timeZone = TimeZone(identifier: zone)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        if let result = formatter.date(from: value), formatter.string(from: result) == value { return result }
    } else {
        let formatter = ISO8601DateFormatter()
        if let result = formatter.date(from: value) { return result }
        formatter.formatOptions.insert(.withFractionalSeconds)
        if let result = formatter.date(from: value) { return result }
    }
    throw BridgeError("invalid_date")
}

func identity(_ item: EKCalendarItem, namespace: String, known: [String: String]) -> String? {
    let prefix = "[HIQS \(namespace)/"
    if let begin = item.notes?.range(of: prefix),
       let end = item.notes?.range(of: "]", range: begin.upperBound..<(item.notes ?? "").endIndex),
       let notes = item.notes {
        return String(notes[notes.index(begin.lowerBound, offsetBy: 6)..<end.lowerBound])
    }
    return known.first(where: { $0.value == item.calendarItemIdentifier })?.key
}

func block(_ row: [String: Any]) throws -> String {
    "[HIQS \(try string(row, "identity"))]\n\(row["notes"] as? String ?? "")\n[/HIQS]"
}

func mergedNotes(_ old: String?, row: [String: Any]) throws -> String {
    let replacement = try block(row)
    let current = old ?? ""
    if let start = current.range(of: "[HIQS \(try string(row, "identity"))]"),
       let end = current.range(of: "[/HIQS]", range: start.upperBound..<current.endIndex) {
        return String(current[..<start.lowerBound]) + replacement + String(current[end.upperBound...])
    }
    return current.isEmpty ? replacement : current + "\n\n" + replacement
}

func reminderArchiveURL() -> URL {
    URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("filtered-reminders.json")
}

func loadReminderArchive() throws -> [String: [String: Any]] {
    let path = reminderArchiveURL()
    if !FileManager.default.fileExists(atPath: path.path) { return [:] }
    guard let result = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as? [String: [String: Any]] else {
        throw BridgeError("invalid_reminder_archive")
    }
    return result
}

func reminderPersonalState(_ item: EKReminder) -> [String: Any] {
    var result: [String: Any] = ["notes": item.notes ?? "", "completed": item.isCompleted, "priority": item.priority]
    if let date = item.completionDate { result["completion_date"] = date.timeIntervalSince1970 }
    result["alarms"] = (item.alarms ?? []).map { alarm -> [String: Any] in
        var saved: [String: Any] = ["relative_offset": alarm.relativeOffset, "proximity": alarm.proximity.rawValue]
        if let date = alarm.absoluteDate { saved["absolute_date"] = date.timeIntervalSince1970 }
        if let location = alarm.structuredLocation {
            saved["location_title"] = location.title; saved["radius"] = location.radius
            if let point = location.geoLocation {
                saved["latitude"] = point.coordinate.latitude; saved["longitude"] = point.coordinate.longitude
            }
        }
        return saved
    }
    return result
}

func restorePersonalState(_ item: EKReminder, from saved: [String: Any]) {
    item.notes = saved["notes"] as? String
    item.priority = saved["priority"] as? Int ?? 0
    item.isCompleted = saved["completed"] as? Bool ?? false
    if item.isCompleted, let timestamp = saved["completion_date"] as? Double { item.completionDate = Date(timeIntervalSince1970: timestamp) }
    item.alarms = (saved["alarms"] as? [[String: Any]] ?? []).map { value in
        let alarm: EKAlarm
        if let timestamp = value["absolute_date"] as? Double { alarm = EKAlarm(absoluteDate: Date(timeIntervalSince1970: timestamp)) }
        else { alarm = EKAlarm(relativeOffset: value["relative_offset"] as? Double ?? 0) }
        if let latitude = value["latitude"] as? Double, let longitude = value["longitude"] as? Double {
            let location = EKStructuredLocation(title: value["location_title"] as? String ?? "")
            location.geoLocation = CLLocation(latitude: latitude, longitude: longitude)
            location.radius = value["radius"] as? Double ?? 0
            alarm.structuredLocation = location
            alarm.proximity = EKAlarmProximity(rawValue: value["proximity"] as? Int ?? 0) ?? .none
        }
        return alarm
    }
}

func dueComponents(_ row: [String: Any], zone: String) throws -> DateComponents? {
    guard let value = row["due"] as? String else { return nil }
    let cal = try calendar(zone)
    let units: Set<Calendar.Component> = value.count == 10 ? [.year, .month, .day] : [.year, .month, .day, .hour, .minute, .second]
    var parts = cal.dateComponents(units, from: try date(value, zone))
    parts.calendar = cal
    parts.timeZone = value.count == 10 ? nil : cal.timeZone
    return parts
}

func sameDue(_ a: DateComponents?, _ b: DateComponents?) -> Bool {
    guard let a = a, let b = b else { return a == nil && b == nil }
    if a.hour == nil || b.hour == nil {
        return a.year == b.year && a.month == b.month && a.day == b.day && a.hour == b.hour
    }
    return a.date == b.date
}

func eventDates(_ row: [String: Any], zone: String) throws -> (Date, Date, Bool) {
    let value = try string(row, "start")
    let allDay = value.count == 10
    // EventKit returns floating all-day dates in the device's default timezone.
    let dayZone = allDay ? TimeZone.current.identifier : zone
    let start = try date(value, dayZone)
    let end: Date
    if allDay {
        // The native store includes the end date and normalizes it to 23:59:59.
        // Passing tomorrow's midnight makes a one-day deadline span TWO days.
        // This differs from ICS DTEND's exclusive-day representation.
        end = try calendar(dayZone).date(byAdding: .day, value: 1, to: start)!.addingTimeInterval(-1)
    }
    else if let value = row["end"] as? String { end = try date(value, zone) }
    else { end = start } // A point deadline has no invented duration.
    guard end >= start else { throw BridgeError("negative_event_duration") }
    return (start, end, allDay)
}

func sameEvent(_ item: EKEvent, row: [String: Any], zone: String) throws -> Bool {
    let (start, end, allDay) = try eventDates(row, zone: zone)
    let noteBlock = try block(row)
    return item.title == row["title"] as? String && item.startDate == start && item.endDate == end &&
        item.isAllDay == allDay && (item.location ?? "") == (row["location"] as? String ?? "") &&
        item.url?.absoluteString == row["url"] as? String && (item.notes ?? "").contains(noteBlock)
}

func sameReminder(_ item: EKReminder, row: [String: Any], zone: String) throws -> Bool {
    let due = try dueComponents(row, zone: zone)
    let noteBlock = try block(row)
    return item.title == row["title"] as? String && sameDue(item.dueDateComponents, due) &&
        item.url?.absoluteString == row["url"] as? String && (item.notes ?? "").contains(noteBlock)
}

@MainActor
func reminders(_ store: EKEventStore, _ list: EKCalendar) async throws -> [EKReminder] {
    let result: [EKReminder]? = await withCheckedContinuation { continuation in
        store.fetchReminders(matching: store.predicateForReminders(in: [list])) { rows in
            continuation.resume(returning: rows)
        }
    }
    guard let result = result else { throw BridgeError("reminders_read_failed") }
    return result
}

func events(_ store: EKEventStore, _ target: EKCalendar, start: Date, end: Date) -> [EKEvent] {
    var rows: [String: EKEvent] = [:]
    var cursor = start
    while cursor < end {
        // EventKit silently caps predicates at four years; use one-year chunks.
        let next = min(cursor.addingTimeInterval(366 * 86400), end)
        for row in store.events(matching: store.predicateForEvents(withStart: cursor, end: next, calendars: [target])) {
            rows[row.calendarItemIdentifier] = row
        }
        cursor = next
    }
    return Array(rows.values)
}

func index<T: EKCalendarItem>(_ rows: [T], namespace: String, known: [String: String]) throws -> [String: T] {
    var result: [String: T] = [:]
    for row in rows {
        guard let key = identity(row, namespace: namespace, known: known), key.hasPrefix(namespace + "/") else { continue }
        if result[key] != nil { throw BridgeError("duplicate_managed_identity") }
        result[key] = row
    }
    return result
}

func source(_ store: EKEventStore, type: EKEntityType, mode: String, sourceID: String?) throws -> EKSource {
    if let sourceID = sourceID {
        guard let saved = store.source(withIdentifier: sourceID) else { throw BridgeError("configured_account_unavailable") }
        return saved
    }
    let defaultList = type == .event ? store.defaultCalendarForNewEvents : store.defaultCalendarForNewReminders()
    if mode == "default", let value = defaultList?.source { return value }
    func matches(_ source: EKSource) -> Bool {
        mode == "icloud" ? source.title.lowercased().contains("icloud") : source.sourceType == .local
    }
    if let value = defaultList?.source, matches(value) { return value }
    let candidates = store.sources.filter(matches)
    guard candidates.count == 1 else { throw BridgeError(candidates.isEmpty ? "requested_account_unavailable" : "account_ambiguous") }
    return candidates[0]
}

func container(_ store: EKEventStore, type: EKEntityType, source: EKSource, savedID: String?) throws -> EKCalendar {
    if let savedID = savedID {
        guard let saved = store.calendar(withIdentifier: savedID), saved.source.sourceIdentifier == source.sourceIdentifier,
              saved.allowedEntityTypes.contains(type == .event ? .event : .reminder), saved.allowsContentModifications else {
            throw BridgeError("configured_container_unavailable")
        }
        return saved
    }
    let candidates = store.calendars(for: type).filter {
        $0.title == "HIQS" && $0.source.sourceIdentifier == source.sourceIdentifier && $0.allowsContentModifications
    }
    if candidates.count > 1 { throw BridgeError("multiple_hiqs_containers") }
    if let existing = candidates.first { return existing }
    let value = EKCalendar(for: type, eventStore: store)
    value.title = "HIQS"
    value.source = source
    try store.saveCalendar(value, commit: true)
    return value
}

@MainActor
func synchronize(_ store: EKEventStore, request: [String: Any]) async throws -> [String: Any] {
    let plan = request["plan"] as? [String: Any] ?? [:]
    let config = request["config"] as? [String: Any] ?? [:]
    let namespace = try string(plan, "namespace")
    guard UUID(uuidString: namespace) != nil else { throw BridgeError("invalid_namespace") }
    let zone = try string(plan, "timezone")
    let mode = try string(config, "account_mode")
    guard ["icloud", "local", "default"].contains(mode) else { throw BridgeError("invalid_account_mode") }
    let eventRows = plan["events"] as? [[String: Any]] ?? []
    let reminderRows = plan["reminders"] as? [[String: Any]] ?? []
    var wanted = Set<String>()
    for row in eventRows + reminderRows {
        let key = try string(row, "identity")
        guard key.hasPrefix(namespace + "/"), wanted.insert(key).inserted else { throw BridgeError("invalid_plan_identity") }
        _ = try string(row, "title")
    }
    for row in eventRows { _ = try eventDates(row, zone: zone) }
    for row in reminderRows { _ = try dueComponents(row, zone: zone) }
    let start = try date(string(plan, "query_start"), zone)
    let end = try date(string(plan, "query_end"), zone)
    guard end >= start, end.timeIntervalSince(start) <= 100 * 366 * 86400 else { throw BridgeError("invalid_query_window") }
    let eventSource = try source(store, type: .event, mode: mode, sourceID: config["calendar_source_id"] as? String)
    let reminderSource = try source(store, type: .reminder, mode: mode, sourceID: config["reminder_source_id"] as? String)
    let target = try container(store, type: .event, source: eventSource, savedID: config["calendar_id"] as? String)
    let list = try container(store, type: .reminder, source: reminderSource, savedID: config["reminder_list_id"] as? String)
    let known = config["item_ids"] as? [String: String] ?? [:]
    var reminderArchive = try loadReminderArchive()
    let removeFilteredReminders = plan["delivery_policy"] as? String == "confirmed_upcoming_brief_v1"
    var eventValues = events(store, target, start: start, end: end)
    var reminderValues = try await reminders(store, list)
    for (_, localID) in known {
        if let value = store.calendarItem(withIdentifier: localID) {
            guard value.calendar.calendarIdentifier == target.calendarIdentifier || value.calendar.calendarIdentifier == list.calendarIdentifier else {
                throw BridgeError("managed_item_moved_to_another_container")
            }
            if let event = value as? EKEvent, !eventValues.contains(where: { $0.calendarItemIdentifier == localID }) { eventValues.append(event) }
            if let reminder = value as? EKReminder, !reminderValues.contains(where: { $0.calendarItemIdentifier == localID }) { reminderValues.append(reminder) }
        }
    }
    let eventIndex = try index(eventValues, namespace: namespace, known: known)
    let reminderIndex = try index(reminderValues, namespace: namespace, known: known)
    var errors: [[String: String]] = []
    var changed = 0, unchanged = 0, removed = 0, withdrawn = 0, removedReminders = 0
    var preservedCompletion: [String: Bool] = [:]
    var ids = known
    for row in eventRows {
        let key = try string(row, "identity")
        do {
            let event = eventIndex[key] ?? EKEvent(eventStore: store)
            if eventIndex[key] != nil, try sameEvent(event, row: row, zone: zone) { unchanged += 1 }
            else {
                let (start, end, allDay) = try eventDates(row, zone: zone)
                event.calendar = target
                event.title = try string(row, "title")
                event.timeZone = allDay ? nil : TimeZone(identifier: zone)
                event.isAllDay = allDay
                event.startDate = start; event.endDate = end
                event.location = row["location"] as? String
                event.url = (row["url"] as? String).flatMap(URL.init(string:))
                event.notes = try mergedNotes(event.notes, row: row)
                try store.save(event, span: .thisEvent, commit: true)
                changed += 1
            }
            ids[key] = event.calendarItemIdentifier
        } catch { errors.append(["identity": key, "reason": "event_write_failed", "error_domain": (error as NSError).domain,
                                  "error_code": String((error as NSError).code)]) }
    }
    for row in reminderRows {
        let key = try string(row, "identity")
        do {
            let reminder = reminderIndex[key] ?? EKReminder(eventStore: store)
            if reminderIndex[key] == nil, let saved = reminderArchive[key] { restorePersonalState(reminder, from: saved) }
            preservedCompletion[key] = reminder.isCompleted
            if reminderIndex[key] != nil, try sameReminder(reminder, row: row, zone: zone) { unchanged += 1 }
            else {
                reminder.calendar = list
                reminder.title = try string(row, "title")
                reminder.dueDateComponents = try dueComponents(row, zone: zone)
                reminder.url = (row["url"] as? String).flatMap(URL.init(string:))
                reminder.notes = try mergedNotes(reminder.notes, row: row)
                try store.save(reminder, commit: true)
                changed += 1
            }
            ids[key] = reminder.calendarItemIdentifier
        } catch { errors.append(["identity": key, "reason": "reminder_write_failed", "error_domain": (error as NSError).domain,
                                  "error_code": String((error as NSError).code)]) }
    }
    if errors.isEmpty {
        for (key, event) in eventIndex where !wanted.contains(key) {
            do { try store.remove(event, span: .thisEvent, commit: true); ids.removeValue(forKey: key); removed += 1 }
            catch { errors.append(["identity": key, "reason": "event_removal_failed"]) }
        }
        for (key, reminder) in reminderIndex where !wanted.contains(key) {
            do {
                if removeFilteredReminders {
                    // Cache personal state BEFORE deletion, so a corrected future
                    // deadline can restore this task without losing its completion.
                    reminderArchive[key] = reminderPersonalState(reminder)
                    try JSONSerialization.data(withJSONObject: reminderArchive, options: [.sortedKeys])
                        .write(to: reminderArchiveURL(), options: .atomic)
                    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: reminderArchiveURL().path)
                    try store.remove(reminder, commit: true)
                    ids.removeValue(forKey: key); removedReminders += 1
                    continue
                }
                preservedCompletion[key] = reminder.isCompleted
                let title = reminder.title ?? ""
                let row: [String: Any] = ["identity": key, "notes": "来源已从 HIQS 撤回；此条保留你的完成状态及个人备注，待你核实。"]
                if !title.hasPrefix("[已撤回] ") || reminder.dueDateComponents != nil {
                    reminder.title = title.hasPrefix("[已撤回] ") ? title : "[已撤回] " + title
                    reminder.dueDateComponents = nil
                    reminder.notes = try mergedNotes(reminder.notes, row: row)
                    try store.save(reminder, commit: true); withdrawn += 1
                }
            } catch { errors.append(["identity": key, "reason": "reminder_withdrawal_failed"]) }
        }
    }
    // A fresh store ensures verification observes persisted data, not our objects.
    let verify = EKEventStore()
    guard let verifyTarget = verify.calendar(withIdentifier: target.calendarIdentifier),
          let verifyList = verify.calendar(withIdentifier: list.calendarIdentifier) else { throw BridgeError("readback_container_missing") }
    let observedEvents = try index(events(verify, verifyTarget, start: start, end: end), namespace: namespace, known: ids)
    let observedReminders = try index(await reminders(verify, verifyList), namespace: namespace, known: ids)
    var matched = 0
    for row in eventRows {
        let key = try string(row, "identity")
        if let actual = observedEvents[key], try sameEvent(actual, row: row, zone: zone) { matched += 1 }
        else { errors.append(["identity": key, "reason": "event_readback_mismatch"]) }
    }
    for row in reminderRows {
        let key = try string(row, "identity")
        if let actual = observedReminders[key], try sameReminder(actual, row: row, zone: zone),
           actual.isCompleted == preservedCompletion[key] { matched += 1 }
        else { errors.append(["identity": key, "reason": "reminder_readback_mismatch"]) }
    }
    for (key, _) in observedEvents where !wanted.contains(key) { errors.append(["identity": key, "reason": "stale_event_remaining"]) }
    for (key, _) in reminderIndex where !wanted.contains(key) {
        if removeFilteredReminders {
            if observedReminders[key] != nil { errors.append(["identity": key, "reason": "filtered_reminder_remaining"]) }
            continue
        }
        if let actual = observedReminders[key], (actual.title ?? "").hasPrefix("[已撤回] "),
           actual.dueDateComponents == nil, actual.isCompleted == preservedCompletion[key] { continue }
        errors.append(["identity": key, "reason": "withdrawal_readback_mismatch"])
    }
    var saved = config
    saved["calendar_id"] = target.calendarIdentifier; saved["reminder_list_id"] = list.calendarIdentifier
    saved["calendar_source_id"] = eventSource.sourceIdentifier; saved["reminder_source_id"] = reminderSource.sourceIdentifier
    saved["item_ids"] = ids
    return ["status": errors.isEmpty ? "complete" : "partial", "config": saved,
            "changed": changed, "unchanged": unchanged, "removed_events": removed, "withdrawn_reminders": withdrawn,
            "removed_reminders": removedReminders,
            "counts": plan["counts"] ?? [:], "errors": errors,
            "verification": ["status": errors.isEmpty ? "verified" : "failed", "expected": wanted.count, "matched": matched],
            "account": ["calendar": eventSource.title, "reminders": reminderSource.title]]
}

@MainActor
func execute(_ request: [String: Any]) async throws -> [String: Any] {
    let operation = try string(request, "operation")
    if operation == "self-test" {
        let zone = "Asia/Hong_Kong"
        let row: [String: Any] = ["identity": "test/reminder/one", "notes": "Source", "due": "2026-11-01"]
        let first = try mergedNotes("My notes", row: row)
        let second = try mergedNotes(first, row: ["identity": "test/reminder/one", "notes": "Changed source"])
        let due = try dueComponents(row, zone: zone)
        let (start, end, allDay) = try eventDates(["start": "2026-11-01"], zone: zone)
        let nextMorning = try calendar(TimeZone.current.identifier).date(byAdding: .day, value: 1, to: start)!
        guard second == "My notes\n\n[HIQS test/reminder/one]\nChanged source\n[/HIQS]",
              due?.hour == nil, due?.day == 1, allDay, end.addingTimeInterval(1) == nextMorning else { throw BridgeError("self_test_failed") }
        let (point, pointEnd, _) = try eventDates(["start": "2026-11-01T10:00:00+08:00"], zone: zone)
        guard point == pointEnd else { throw BridgeError("point_duration_invented") }
        let memoryStore = EKEventStore()
        let original = EKReminder(eventStore: memoryStore)
        original.notes = "Personal note"; original.priority = 5; original.isCompleted = true
        original.alarms = [EKAlarm(relativeOffset: -1800)]
        let restored = EKReminder(eventStore: memoryStore)
        restorePersonalState(restored, from: reminderPersonalState(original))
        guard restored.isCompleted, restored.notes == "Personal note", restored.priority == 5,
              restored.alarms?.first?.relativeOffset == -1800 else { throw BridgeError("reminder_archive_restore_failed") }
        return ["status": "passed", "checks": ["personal_notes", "date_only_reminder", "all_day_boundary", "point_event_duration", "filtered_task_personal_state"]]
    }
    let store = EKEventStore()
    if operation == "authorize" {
        if EKEventStore.authorizationStatus(for: .event) == .notDetermined { _ = try await store.requestFullAccessToEvents() }
        if EKEventStore.authorizationStatus(for: .reminder) == .notDetermined { _ = try await store.requestFullAccessToReminders() }
    }
    let allowed = EKEventStore.authorizationStatus(for: .event) == .fullAccess &&
                  EKEventStore.authorizationStatus(for: .reminder) == .fullAccess
    var result: [String: Any] = ["status": allowed ? "ready" : "permission_required",
        "calendar_authorization": EKEventStore.authorizationStatus(for: .event).rawValue,
        "reminder_authorization": EKEventStore.authorizationStatus(for: .reminder).rawValue]
    if !allowed || operation == "status" { return result }
    if operation == "sync" { return try await synchronize(store, request: request) }
    if operation == "inspect" {
        let config = request["config"] as? [String: Any] ?? [:]
        let plan = request["plan"] as? [String: Any] ?? [:]
        let namespace = try string(plan, "namespace"), zone = try string(plan, "timezone")
        guard let target = store.calendar(withIdentifier: try string(config, "calendar_id")) else { throw BridgeError("calendar_missing") }
        let found = try index(events(store, target, start: date(string(plan, "query_start"), zone),
                                     end: date(string(plan, "query_end"), zone)), namespace: namespace,
                              known: config["item_ids"] as? [String: String] ?? [:])
        var differences: [[String: Any]] = []
        for row in plan["events"] as? [[String: Any]] ?? [] {
            let key = try string(row, "identity")
            guard let item = found[key] else { differences.append(["identity": key, "missing": true]); continue }
            if try sameEvent(item, row: row, zone: zone) { continue }
            let (start, end, allDay) = try eventDates(row, zone: zone)
            let noteBlock = try block(row)
            differences.append(["identity": key, "start_delta": item.startDate.timeIntervalSince(start),
                "end_delta": item.endDate.timeIntervalSince(end), "all_day_match": item.isAllDay == allDay,
                "title_match": item.title == row["title"] as? String,
                "location_match": (item.location ?? "") == (row["location"] as? String ?? ""),
                "url_match": item.url?.absoluteString == row["url"] as? String,
                "source_notes_match": (item.notes ?? "").contains(noteBlock),
                "expected_note_characters": noteBlock.count, "actual_note_characters": item.notes?.count ?? 0])
        }
        return ["status": "inspected", "differences": differences]
    }
    guard operation == "inventory" || operation == "authorize" else { throw BridgeError("unknown_operation") }
    result["calendars"] = store.calendars(for: .event).map { ["id": $0.calendarIdentifier, "title": $0.title, "source": $0.source.title] }
    result["reminder_lists"] = store.calendars(for: .reminder).map { ["id": $0.calendarIdentifier, "title": $0.title, "source": $0.source.title] }
    return result
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
Task { @MainActor in
    guard CommandLine.arguments.count == 3 else { app.terminate(nil); return }
    let output = URL(fileURLWithPath: CommandLine.arguments[2])
    let result: [String: Any]
    do {
        let input = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        guard let request = try JSONSerialization.jsonObject(with: input) as? [String: Any] else { throw BridgeError("invalid_request") }
        let root = URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().deletingLastPathComponent()
        let descriptor = Darwin.open(root.appendingPathComponent("native.lock").path, O_CREAT | O_RDWR, 0o600)
        guard descriptor >= 0 else { throw BridgeError("native_lock_unavailable") }
        defer { flock(descriptor, LOCK_UN); Darwin.close(descriptor) }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else { throw BridgeError("native_operation_still_running") }
        result = try await execute(request)
    } catch {
        result = ["status": "failed", "reason": (error as? BridgeError)?.description ?? "eventkit_operation_failed",
                  "error_type": String(describing: type(of: error))]
    }
    if let data = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]) {
        try? data.write(to: output, options: .atomic)
    }
    app.terminate(nil)
}
app.run()
