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


if __name__ == "__main__":
    unittest.main()
