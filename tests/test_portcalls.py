"""Tests for AIS port-call detection.

Detection runs on synthetic AIS points rather than a real 600 MB archive, so
the suite stays fast and the edge cases (dropouts, brief stops, calls clipped
by the file boundary) can be constructed deliberately instead of hunted for.
"""

import datetime as dt
import unittest

import pandas as pd

from portscra.ais.portcalls import (
    detect_port_calls,
    normalise_column,
    reflag_truncation,
    stitch_across_days,
    summarise_calls,
)
from portscra.ais.ports import RONNE, find_port, union_bounds

BASE = dt.datetime(2026, 3, 2, 0, 0, 0)
#: An observation window wider than any fixture below, so nothing is flagged as
#: truncated purely for being the first or last vessel in a small extract.
WINDOW = (BASE, BASE + dt.timedelta(minutes=1000))


def points(mmsi, start_min, n, *, step_min=5, sog=0.1, port="ronne",
           status="Moored", name="TEST VESSEL", ship_type="Passenger"):
    """Build a run of AIS reports for one vessel."""
    return pd.DataFrame(
        {
            "timestamp": [BASE + dt.timedelta(minutes=start_min + i * step_min)
                          for i in range(n)],
            "mmsi": [mmsi] * n,
            "latitude": [RONNE.centre[0]] * n,
            "longitude": [RONNE.centre[1]] * n,
            "sog": [sog] * n,
            "navigational_status": [status] * n,
            "name": [name] * n,
            "ship_type": [ship_type] * n,
            "cargo_type": [None] * n,
            "length": [120.0] * n,
            "width": [20.0] * n,
            "draught": [5.5] * n,
            "destination": ["DKRNN"] * n,
            "port": [port] * n,
        }
    )


class TestColumnNormalisation(unittest.TestCase):
    def test_strips_hash_from_first_column(self):
        """DMA files write the first header as '# Timestamp' in some vintages."""
        self.assertEqual(normalise_column("# Timestamp"), "timestamp")
        self.assertEqual(normalise_column("Timestamp"), "timestamp")

    def test_spaces_become_underscores(self):
        self.assertEqual(normalise_column("Navigational status"), "navigational_status")
        self.assertEqual(normalise_column("Type of mobile"), "type_of_mobile")

    def test_bare_dimension_columns_are_aliased(self):
        """Vessel dimensions appear as either 'Size A' or bare 'A'."""
        self.assertEqual(normalise_column("A"), "size_a")
        self.assertEqual(normalise_column("Size A"), "size_a")


class TestPortAreas(unittest.TestCase):
    def test_contains_its_own_centre(self):
        lat, lon = RONNE.centre
        self.assertTrue(RONNE.contains(lat, lon))

    def test_excludes_distant_points(self):
        self.assertFalse(RONNE.contains(57.0, 10.0))

    def test_union_bounds_covers_every_candidate(self):
        lat_min, lat_max, lon_min, lon_max = union_bounds()
        from portscra.ais.ports import CANDIDATE_PORTS
        for port in CANDIDATE_PORTS:
            self.assertGreaterEqual(port.lat_min, lat_min)
            self.assertLessEqual(port.lat_max, lat_max)
            self.assertGreaterEqual(port.lon_min, lon_min)
            self.assertLessEqual(port.lon_max, lon_max)

    def test_lookup(self):
        self.assertIsNotNone(find_port("ronne"))
        self.assertIsNone(find_port("rotterdam"))


class TestDetection(unittest.TestCase):
    def test_detects_a_simple_call(self):
        df = points("111", start_min=60, n=40)  # 40 x 5 min = 195 min
        calls = detect_port_calls(df)
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls.iloc[0]["dwell_hours"], 195 / 60, places=2)
        self.assertEqual(calls.iloc[0]["mmsi"], "111")

    def test_ignores_stops_shorter_than_minimum(self):
        """A vessel pausing for twenty minutes is waiting, not calling."""
        df = points("222", start_min=60, n=5)  # 20 minutes
        self.assertTrue(detect_port_calls(df).empty)

    def test_ignores_moving_vessels(self):
        df = points("333", start_min=60, n=40, sog=8.0, status="Under way using engine")
        self.assertTrue(detect_port_calls(df).empty)

    def test_moored_status_overrides_noisy_speed(self):
        """AIS speed occasionally reports noise at a berth; status is the
        second opinion that keeps a real call from being discarded."""
        df = points("444", start_min=60, n=40, sog=1.5, status="Moored")
        self.assertEqual(len(detect_port_calls(df)), 1)

    def test_tolerates_reception_dropout_within_a_call(self):
        """A 20-minute gap is a dropout, not a departure and a new arrival."""
        first = points("555", start_min=60, n=20)
        second = points("555", start_min=60 + 20 * 5 + 20, n=20)
        calls = detect_port_calls(pd.concat([first, second], ignore_index=True))
        self.assertEqual(len(calls), 1)

    def test_splits_on_a_long_absence(self):
        """Four hours away is a genuine departure and a second call."""
        first = points("666", start_min=0, n=20)
        second = points("666", start_min=20 * 5 + 240, n=20)
        calls = detect_port_calls(pd.concat([first, second], ignore_index=True))
        self.assertEqual(len(calls), 2)

    def test_separates_vessels_and_ports(self):
        a = points("777", start_min=60, n=30, port="ronne")
        b = points("888", start_min=60, n=30, port="koge")
        calls = detect_port_calls(pd.concat([a, b], ignore_index=True))
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(calls["port"]), {"ronne", "koge"})

    def test_flags_calls_clipped_by_the_file_boundary(self):
        """Single-day extracts truncate calls at midnight. Dwell statistics
        computed over clipped calls are biased short, so they must be flagged."""
        clipped = points("999", start_min=0, n=30)
        later = points("101", start_min=400, n=30)
        calls = detect_port_calls(
            pd.concat([clipped, later], ignore_index=True), window=WINDOW
        )
        clipped_row = calls[calls["mmsi"] == "999"].iloc[0]
        later_row = calls[calls["mmsi"] == "101"].iloc[0]
        self.assertTrue(clipped_row["truncated_start"])
        self.assertFalse(later_row["truncated_start"])
        self.assertFalse(later_row["truncated_end"])

    def test_window_defaults_to_the_observed_range(self):
        """Without an explicit window the first and last calls in the extract
        look clipped, which is correct for a full day and misleading for a
        sparse one -- hence the parameter."""
        df = points("303", start_min=0, n=30)
        row = detect_port_calls(df).iloc[0]
        self.assertTrue(row["truncated_start"])
        self.assertTrue(row["truncated_end"])

    def test_carries_vessel_attributes(self):
        df = points("112", start_min=60, n=30, ship_type="Cargo")
        row = detect_port_calls(df).iloc[0]
        self.assertEqual(row["ship_type"], "Cargo")
        self.assertEqual(row["length"], 120.0)
        self.assertEqual(row["destination"], "DKRNN")

    def test_empty_input_returns_empty_frame_with_schema(self):
        empty = pd.DataFrame(columns=["timestamp", "mmsi", "port"])
        calls = detect_port_calls(empty)
        self.assertTrue(calls.empty)
        self.assertIn("dwell_hours", calls.columns)

    def test_rejects_frames_missing_required_columns(self):
        with self.assertRaises(ValueError):
            detect_port_calls(pd.DataFrame({"timestamp": [BASE]}))


class TestSummary(unittest.TestCase):
    def test_summary_excludes_truncated_calls_from_dwell(self):
        clipped = points("201", start_min=0, n=30)
        complete = points("202", start_min=200, n=24)  # 115 min
        calls = detect_port_calls(
            pd.concat([clipped, complete], ignore_index=True), window=WINDOW
        )
        summary = summarise_calls(calls)
        row = summary.iloc[0]
        self.assertEqual(row["calls"], 2)
        self.assertEqual(row["complete_calls"], 1)
        self.assertAlmostEqual(row["mean_dwell_h"], 115 / 60, places=1)

    def test_empty_summary_has_schema(self):
        summary = summarise_calls(pd.DataFrame())
        self.assertTrue(summary.empty)
        self.assertIn("calls", summary.columns)


if __name__ == "__main__":
    unittest.main()


class TestStitchAcrossDays(unittest.TestCase):
    """Daily files split long stays; stitching rejoins them."""

    @staticmethod
    def call(mmsi, arrival, departure, *, tstart, tend, port="ronne",
             ship_type="Cargo", n=100):
        return {
            "port": port, "mmsi": mmsi, "name": "TEST", "ship_type": ship_type,
            "cargo_type": None, "arrival": arrival, "departure": departure,
            "dwell_hours": (departure - arrival).total_seconds() / 3600,
            "n_messages": n, "length": 120.0, "width": 20.0, "draught": 5.5,
            "destination": "DKRNN", "truncated_start": tstart, "truncated_end": tend,
        }

    def frame(self, *rows):
        return pd.DataFrame.from_records(list(rows))

    def test_joins_a_stay_split_over_two_days(self):
        d1 = dt.datetime(2026, 3, 2)
        d2 = dt.datetime(2026, 3, 3)
        df = self.frame(
            self.call("1", d1 + dt.timedelta(hours=6), d1 + dt.timedelta(hours=23, minutes=59),
                      tstart=False, tend=True),
            self.call("1", d2, d2 + dt.timedelta(hours=10), tstart=True, tend=False),
        )
        out = stitch_across_days(df)
        self.assertEqual(len(out), 1)
        row = out.iloc[0]
        # 06:00 day 1 to 10:00 day 2 = 28 hours, well past the 24 h ceiling
        self.assertAlmostEqual(row["dwell_hours"], 28.0, delta=0.02)
        self.assertFalse(row["truncated_start"])
        self.assertFalse(row["truncated_end"])
        self.assertEqual(row["days_spanned"], 2)
        self.assertEqual(row["n_messages"], 200)

    def test_collapses_a_chain_of_three_days(self):
        days = [dt.datetime(2026, 3, d) for d in (2, 3, 4)]
        df = self.frame(
            self.call("1", days[0] + dt.timedelta(hours=8),
                      days[0] + dt.timedelta(hours=23, minutes=59), tstart=False, tend=True),
            self.call("1", days[1], days[1] + dt.timedelta(hours=23, minutes=59),
                      tstart=True, tend=True),
            self.call("1", days[2], days[2] + dt.timedelta(hours=4), tstart=True, tend=False),
        )
        out = stitch_across_days(df)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.iloc[0]["dwell_hours"], 44.0, delta=0.02)
        self.assertEqual(out.iloc[0]["days_spanned"], 3)

    def test_does_not_join_non_adjacent_days(self):
        """Our seasonal weeks are months apart -- a vessel clipped at the end of
        one week must not be joined to one clipped at the start of the next."""
        a = dt.datetime(2025, 10, 19)
        b = dt.datetime(2026, 1, 19)
        df = self.frame(
            self.call("1", a + dt.timedelta(hours=6), a + dt.timedelta(hours=23, minutes=59),
                      tstart=False, tend=True),
            self.call("1", b, b + dt.timedelta(hours=10), tstart=True, tend=False),
        )
        self.assertEqual(len(stitch_across_days(df)), 2)

    def test_does_not_join_different_vessels(self):
        d1 = dt.datetime(2026, 3, 2)
        d2 = dt.datetime(2026, 3, 3)
        df = self.frame(
            self.call("1", d1 + dt.timedelta(hours=6), d1 + dt.timedelta(hours=23, minutes=59),
                      tstart=False, tend=True),
            self.call("2", d2, d2 + dt.timedelta(hours=10), tstart=True, tend=False),
        )
        self.assertEqual(len(stitch_across_days(df)), 2)

    def test_does_not_join_when_the_boundary_is_clean(self):
        """A vessel that genuinely sailed before midnight stays separate."""
        d1 = dt.datetime(2026, 3, 2)
        d2 = dt.datetime(2026, 3, 3)
        df = self.frame(
            self.call("1", d1 + dt.timedelta(hours=6), d1 + dt.timedelta(hours=18),
                      tstart=False, tend=False),
            self.call("1", d2 + dt.timedelta(hours=2), d2 + dt.timedelta(hours=10),
                      tstart=False, tend=False),
        )
        self.assertEqual(len(stitch_across_days(df)), 2)

    def test_does_not_join_across_ports(self):
        d1 = dt.datetime(2026, 3, 2)
        d2 = dt.datetime(2026, 3, 3)
        df = self.frame(
            self.call("1", d1 + dt.timedelta(hours=6), d1 + dt.timedelta(hours=23, minutes=59),
                      tstart=False, tend=True, port="ronne"),
            self.call("1", d2, d2 + dt.timedelta(hours=10), tstart=True, tend=False, port="koge"),
        )
        self.assertEqual(len(stitch_across_days(df)), 2)

    def test_untouched_frame_when_nothing_to_join(self):
        d1 = dt.datetime(2026, 3, 2)
        df = self.frame(
            self.call("1", d1 + dt.timedelta(hours=6), d1 + dt.timedelta(hours=12),
                      tstart=False, tend=False),
        )
        self.assertEqual(len(stitch_across_days(df)), 1)

    def test_empty_frame(self):
        empty = pd.DataFrame(columns=["port", "mmsi", "arrival", "departure",
                                      "truncated_start", "truncated_end"])
        self.assertTrue(stitch_across_days(empty).empty)

    def test_rejects_missing_columns(self):
        with self.assertRaises(ValueError):
            stitch_across_days(pd.DataFrame({"port": ["ronne"]}))


class TestReflagTruncation(unittest.TestCase):
    """Truncation flags are derivable from timestamps, so a tolerance change is
    repairable in place rather than requiring a re-download."""

    def frame(self, arrival, departure, date):
        return pd.DataFrame([{
            "port": "ronne", "mmsi": "1", "date": pd.Timestamp(date),
            "arrival": pd.Timestamp(arrival), "departure": pd.Timestamp(departure),
            "truncated_start": False, "truncated_end": False,
        }])

    def test_flags_a_vessel_present_at_midnight(self):
        """A moored Class A vessel reports every 3 minutes, so its first message
        of the day can be at 00:02:59 -- that is a truncated call, not one that
        happened to arrive just after midnight."""
        df = self.frame("2026-03-02 00:02:30", "2026-03-02 14:00:00", "2026-03-02")
        out = reflag_truncation(df)
        self.assertTrue(out.iloc[0]["truncated_start"])
        self.assertFalse(out.iloc[0]["truncated_end"])

    def test_a_genuine_early_arrival_is_not_flagged(self):
        df = self.frame("2026-03-02 00:30:00", "2026-03-02 14:00:00", "2026-03-02")
        self.assertFalse(reflag_truncation(df).iloc[0]["truncated_start"])

    def test_flags_a_vessel_still_alongside_at_end_of_day(self):
        df = self.frame("2026-03-02 08:00:00", "2026-03-02 23:57:00", "2026-03-02")
        self.assertTrue(reflag_truncation(df).iloc[0]["truncated_end"])

    def test_tolerance_is_configurable(self):
        df = self.frame("2026-03-02 00:02:30", "2026-03-02 14:00:00", "2026-03-02")
        self.assertFalse(
            reflag_truncation(df, boundary_tolerance_minutes=1).iloc[0]["truncated_start"]
        )

    def test_rejects_missing_columns(self):
        with self.assertRaises(ValueError):
            reflag_truncation(pd.DataFrame({"arrival": [pd.Timestamp("2026-03-02")]}))
