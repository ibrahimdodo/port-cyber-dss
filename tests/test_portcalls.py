"""Tests for AIS port-call detection.

Detection runs on synthetic AIS points rather than a real 600 MB archive, so
the suite stays fast and the edge cases (dropouts, brief stops, calls clipped
by the file boundary) can be constructed deliberately instead of hunted for.
"""

import datetime as dt
import unittest

import pandas as pd

from portscra.ais.portcalls import detect_port_calls, normalise_column, summarise_calls
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
