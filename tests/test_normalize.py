import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import galley_normalize as gn

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return gn.parse_plist(handle.read())


class ParsePlistTest(unittest.TestCase):
    def test_parses_single_operation_output(self):
        data = load("printers-idle.plist")
        self.assertEqual(len(data["Tests"]), 1)
        self.assertEqual(data["Tests"][0]["StatusCode"], "successful-ok")

    def test_truncates_trailing_summary_footer(self):
        # ipptool appends a plain-text "Summary:" footer after </plist>
        # whenever a request file holds more than one operation.
        with open(os.path.join(FIXTURES, "printers-idle.plist"), "rb") as handle:
            raw = handle.read()
        polluted = raw + b"\nSummary: 2 tests, 2 passed, 0 failed\nScore: 100%\n"
        data = gn.parse_plist(polluted)
        self.assertEqual(len(data["Tests"]), 1)


class NoDestinationsTest(unittest.TestCase):
    def test_empty_cups_is_a_benign_no_destinations(self):
        # cupsd returns this exact shape for CUPS-Get-Printers when no
        # printers are configured -- a healthy empty state, not a fault.
        result = {
            "Successful": False,
            "StatusCode": "client-error-not-found",
            "ResponseAttributes": [
                {"attributes-charset": "utf-8",
                 "attributes-natural-language": "en",
                 "status-message": "No destinations added."},
            ],
        }
        self.assertTrue(gn.no_destinations(result))

    def test_success_is_never_no_destinations(self):
        result = {"Successful": True, "StatusCode": "successful-ok"}
        self.assertFalse(gn.no_destinations(result))

    def test_other_failures_stay_errors(self):
        result = {
            "Successful": False,
            "StatusCode": "server-error-service-unavailable",
            "ResponseAttributes": [
                {"attributes-charset": "utf-8",
                 "status-message": "Service unavailable."},
            ],
        }
        self.assertFalse(gn.no_destinations(result))

    def test_not_found_without_status_message_is_not_benign(self):
        result = {
            "Successful": False,
            "StatusCode": "client-error-not-found",
            "ResponseAttributes": [{"attributes-charset": "utf-8"}],
        }
        self.assertFalse(gn.no_destinations(result))

    def test_missing_response_attributes_is_not_benign(self):
        result = {"Successful": False, "StatusCode": "client-error-not-found"}
        self.assertFalse(gn.no_destinations(result))


class AsListTest(unittest.TestCase):
    def test_wraps_scalar(self):
        # Single-valued IPP attributes arrive as scalars, not one-element lists.
        self.assertEqual(gn.as_list("none"), ["none"])

    def test_passes_through_list(self):
        self.assertEqual(gn.as_list(["a", "b"]), ["a", "b"])

    def test_missing_becomes_empty(self):
        self.assertEqual(gn.as_list(None), [])


class SuppliesTest(unittest.TestCase):
    def test_zips_to_shortest_array(self):
        # Canon@OLP really returns 4 names against 11 levels.
        attrs = {
            "marker-names": ["Black", "Cyan", "Magenta", "Yellow"],
            "marker-levels": [41, 38, 48, 56, 40, 79, 84, 84, 84, 92, 99],
            "marker-types": ["toner", "toner", "toner", "toner"],
            "marker-colors": ["#000000", "#00FFFF", "#FF00FF", "#FFFF00"],
        }
        supplies = gn.normalize_supplies(attrs)
        self.assertEqual(len(supplies), 4)
        self.assertEqual(supplies[0], {
            "name": "Black", "type": "toner", "level": 41, "color": "#000000",
        })

    def test_drops_unknown_levels(self):
        # Brother@Home reports -1 for all four toners.
        attrs = {
            "marker-names": ["Black Toner", "Waste Toner Box"],
            "marker-levels": [-1, 83],
            "marker-types": ["toner", "waste-toner"],
            "marker-colors": ["#000000", "none"],
        }
        supplies = gn.normalize_supplies(attrs)
        self.assertEqual([s["name"] for s in supplies], ["Waste Toner Box"])

    def test_no_marker_attributes_yields_empty(self):
        self.assertEqual(gn.normalize_supplies({}), [])


class PrinterTest(unittest.TestCase):
    def test_normalizes_real_idle_fixture(self):
        groups = gn.response_groups(load("printers-idle.plist")["Tests"][0])
        printers = [gn.normalize_printer(g, "Canon@OLP") for g in groups]
        by_name = {p["name"]: p for p in printers}

        self.assertEqual(sorted(by_name), ["Brother@Home", "Canon@OLP"])
        brother = by_name["Brother@Home"]
        self.assertEqual(brother["state"], "idle")
        self.assertEqual(brother["stateReasons"], ["none"])
        self.assertEqual(brother["queuedJobCount"], 0)
        self.assertTrue(brother["accepting"])
        self.assertFalse(brother["isDefault"])
        self.assertEqual(brother["location"], "Home")
        self.assertTrue(by_name["Canon@OLP"]["isDefault"])

    def test_busy_fixture_reports_queue_counts(self):
        groups = gn.response_groups(load("printers-busy.plist")["Tests"][0])
        counts = {g["printer-name"]: gn.normalize_printer(g, "")["queuedJobCount"]
                  for g in groups}
        self.assertEqual(counts, {"Brother@Home": 1, "Canon@OLP": 2})

    def test_state_names(self):
        self.assertEqual(gn.printer_state_name(3), "idle")
        self.assertEqual(gn.printer_state_name(4), "printing")
        self.assertEqual(gn.printer_state_name(5), "stopped")
        self.assertEqual(gn.printer_state_name(99), "unknown")


class PrinterFromUriTest(unittest.TestCase):
    def test_extracts_trailing_segment(self):
        uri = "ipp://localhost:631/printers/Canon@OLP"
        self.assertEqual(gn.printer_from_uri(uri), "Canon@OLP")

    def test_tolerates_trailing_slash(self):
        uri = "ipp://localhost:631/printers/Brother@Home/"
        self.assertEqual(gn.printer_from_uri(uri), "Brother@Home")

    def test_empty_uri_is_empty_string(self):
        self.assertEqual(gn.printer_from_uri(None), "")


class JobTest(unittest.TestCase):
    def test_normalizes_real_held_jobs(self):
        groups = gn.response_groups(load("jobs-held.plist")["Tests"][0])
        jobs = [gn.normalize_job(g, "sean") for g in groups]

        self.assertEqual(len(jobs), 3)
        first = jobs[0]
        self.assertEqual(first["id"], 53)
        self.assertEqual(first["name"], "report.pdf")
        self.assertEqual(first["printer"], "Canon@OLP")
        self.assertEqual(first["user"], "sean")
        self.assertEqual(first["state"], "held")
        self.assertEqual(first["stateReasons"], ["job-hold-until-specified"])
        self.assertEqual(first["sizeKb"], 1)
        self.assertTrue(first["mine"])
        self.assertEqual([j["printer"] for j in jobs],
                         ["Canon@OLP", "Canon@OLP", "Brother@Home"])

    def test_pages_none_until_printing(self):
        # job-media-sheets is not returned by either printer and
        # job-impressions-completed is 0 until the job actually prints.
        groups = gn.response_groups(load("jobs-held.plist")["Tests"][0])
        self.assertIsNone(gn.normalize_job(groups[0], "sean")["pages"])

    def test_pages_reported_once_known(self):
        attrs = {"job-id": 1, "job-impressions-completed": 4}
        self.assertEqual(gn.normalize_job(attrs, "sean")["pages"], 4)

    def test_media_sheets_preferred_when_present(self):
        attrs = {"job-id": 1, "job-media-sheets": 9,
                 "job-impressions-completed": 4}
        self.assertEqual(gn.normalize_job(attrs, "sean")["pages"], 9)

    def test_zero_media_sheets_is_unknown(self):
        # A zero page count means "not known yet", not "zero pages".
        # Both page sources must agree on that; job-impressions-completed
        # is already 0 for every pending job on real hardware.
        attrs = {"job-id": 1, "job-media-sheets": 0}
        self.assertIsNone(gn.normalize_job(attrs, "sean")["pages"])

    def test_zero_media_sheets_falls_through_to_impressions(self):
        attrs = {"job-id": 1, "job-media-sheets": 0,
                 "job-impressions-completed": 4}
        self.assertEqual(gn.normalize_job(attrs, "sean")["pages"], 4)

    def test_foreign_job_is_not_mine(self):
        attrs = {"job-id": 7, "job-originating-user-name": "someone-else"}
        self.assertFalse(gn.normalize_job(attrs, "sean")["mine"])

    def test_redacted_job_name_falls_back(self):
        # Without requesting-user-name cupsd omits job-name entirely.
        attrs = {"job-id": 42}
        job = gn.normalize_job(attrs, "sean")
        self.assertEqual(job["name"], "Job 42")
        self.assertEqual(job["user"], "")

    def test_empty_queue_yields_no_jobs(self):
        groups = gn.response_groups(load("jobs-empty.plist")["Tests"][0])
        self.assertEqual(groups, [])

    def test_state_names(self):
        self.assertEqual(gn.job_state_name(3), "pending")
        self.assertEqual(gn.job_state_name(4), "held")
        self.assertEqual(gn.job_state_name(5), "processing")
        self.assertEqual(gn.job_state_name(9), "completed")


class SummaryTest(unittest.TestCase):
    def test_counts_printers_jobs_and_errors(self):
        printers = [
            {"name": "a", "state": "idle", "stateReasons": ["none"], "supplies": []},
            {"name": "b", "state": "stopped", "stateReasons": ["media-jam"],
             "supplies": [{"name": "K", "type": "toner", "level": 4}]},
        ]
        jobs = [{"id": 1}, {"id": 2}, {"id": 3}]
        summary = gn.summarize(printers, jobs, 15)
        self.assertEqual(summary, {
            "printers": 2, "activeJobs": 3, "errorPrinters": 1, "lowSupplies": 1,
        })

    def test_waste_toner_never_counts_as_low(self):
        # IPP does not define whether a waste level means full or remaining,
        # and vendors disagree, so it is displayed but never alerted on.
        printers = [{
            "name": "a", "state": "idle", "stateReasons": ["none"],
            "supplies": [{"name": "Waste", "type": "waste-toner", "level": 2}],
        }]
        self.assertEqual(gn.summarize(printers, [], 15)["lowSupplies"], 0)

    def test_stopped_printer_counts_as_error_even_without_reason(self):
        printers = [{"name": "a", "state": "stopped",
                     "stateReasons": ["none"], "supplies": []}]
        self.assertEqual(gn.summarize(printers, [], 15)["errorPrinters"], 1)

    def test_idle_printer_with_error_reason_counts(self):
        printers = [{"name": "a", "state": "idle",
                     "stateReasons": ["media-empty"], "supplies": []}]
        self.assertEqual(gn.summarize(printers, [], 15)["errorPrinters"], 1)

    def test_error_reasons_match_across_severity_suffixes(self):
        # IPP appends severity suffixes to state reasons. Entries in
        # ERROR_REASONS are base reasons; the suffix is stripped before
        # matching, so every severity of the same condition must classify
        # identically.
        for reason in ("media-jam", "media-empty-warning", "cover-open-report",
                       "offline", "offline-report", "offline-warning"):
            printer = {"name": "p", "state": "idle",
                       "stateReasons": [reason], "supplies": []}
            self.assertTrue(gn.has_error(printer), reason)

    def test_benign_reasons_are_not_errors(self):
        for reason in ("none", "", "toner-low-warning", "media-needed-report-ok"):
            printer = {"name": "p", "state": "idle",
                       "stateReasons": [reason], "supplies": []}
            self.assertFalse(gn.has_error(printer), reason)


class BuildSnapshotTest(unittest.TestCase):
    def test_assembles_full_snapshot_from_fixtures(self):
        printers = gn.response_groups(load("printers-busy.plist")["Tests"][0])
        jobs = gn.response_groups(load("jobs-held.plist")["Tests"][0])

        snapshot = gn.build_snapshot(
            printers=printers, jobs=jobs, default_printer="Canon@OLP",
            current_user="sean", cupsd="running", threshold=15,
        )

        self.assertEqual(snapshot["schema"], 1)
        self.assertEqual(snapshot["cupsd"], "running")
        self.assertIsNone(snapshot["error"])
        self.assertEqual(snapshot["defaultPrinter"], "Canon@OLP")
        self.assertEqual(len(snapshot["printers"]), 2)
        self.assertEqual(len(snapshot["jobs"]), 3)
        self.assertEqual(snapshot["summary"]["activeJobs"], 3)
        self.assertEqual(snapshot["summary"]["printers"], 2)

    def test_asleep_snapshot_has_no_printers_and_no_error(self):
        snapshot = gn.build_snapshot(cupsd="asleep")
        self.assertEqual(snapshot["cupsd"], "asleep")
        self.assertEqual(snapshot["printers"], [])
        self.assertEqual(snapshot["jobs"], [])
        self.assertIsNone(snapshot["error"])
        self.assertEqual(snapshot["summary"]["activeJobs"], 0)

    def test_error_snapshot_carries_message(self):
        snapshot = gn.build_snapshot(cupsd="error", error="ipptool timed out")
        self.assertEqual(snapshot["cupsd"], "error")
        self.assertEqual(snapshot["error"], "ipptool timed out")

    def test_snapshot_is_json_serializable(self):
        import json
        printers = gn.response_groups(load("printers-idle.plist")["Tests"][0])
        snapshot = gn.build_snapshot(printers=printers, default_printer="Canon@OLP")
        json.loads(json.dumps(snapshot))


class PrinterOrderTest(unittest.TestCase):
    def test_default_printer_sorts_first(self):
        printers = [{"printer-name": "Zebra"}, {"printer-name": "Alpha"},
                    {"printer-name": "Mid"}]
        snapshot = gn.build_snapshot(printers=printers, default_printer="Mid")
        self.assertEqual([p["name"] for p in snapshot["printers"]],
                         ["Mid", "Alpha", "Zebra"])

    def test_without_a_default_order_is_alphabetical(self):
        printers = [{"printer-name": "Zebra"}, {"printer-name": "Alpha"}]
        snapshot = gn.build_snapshot(printers=printers, default_printer="")
        self.assertEqual([p["name"] for p in snapshot["printers"]],
                         ["Alpha", "Zebra"])

    def test_sort_is_case_insensitive(self):
        printers = [{"printer-name": "beta"}, {"printer-name": "Alpha"}]
        snapshot = gn.build_snapshot(printers=printers, default_printer="")
        self.assertEqual([p["name"] for p in snapshot["printers"]],
                         ["Alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
