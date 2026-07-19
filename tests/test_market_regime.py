import unittest
from pathlib import Path

import pandas as pd

from a_share_backtesting.market_regime import build_market_regime_schedule, load_market_regime_config


TRADING_DATES = pd.to_datetime(
    [
        "2026-06-01",
        "2026-06-08",
        "2026-06-15",
        "2026-06-16",
        "2026-06-18",
        "2026-06-22",
        "2026-07-02",
        "2026-07-03",
        "2026-07-07",
        "2026-07-08",
        "2026-07-13",
        "2026-07-16",
        "2026-07-17",
        "2026-07-20",
    ]
)


def same_day_config() -> dict[str, object]:
    return {
        "timing_definition": "two_day_total_4pct",
        "observation_start": "2026-06-01",
        "initial_state": "risk_off",
        "execution_mode": "same_day_1455",
        "events": [
            {"signal_date": "2026-07-17", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-06-22", "event": "up", "label": "two_day_4pct_confirmation"},
            {"signal_date": "2026-06-15", "event": "up", "label": "two_day_4pct_activation"},
            {"signal_date": "2026-07-02", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-06-08", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-07-07", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-07-08", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-07-13", "event": "down", "label": "0amv_down_3pct"},
            {"signal_date": "2026-07-16", "event": "down", "label": "0amv_down_3pct"},
        ],
    }


class SameDayMarketRegimeScheduleTests(unittest.TestCase):
    def test_same_day_events_transition_at_1455_and_keep_confirmation_auditable(self) -> None:
        schedule = build_market_regime_schedule(same_day_config(), TRADING_DATES)

        self.assertEqual(schedule.state_at(pd.Timestamp("2026-06-01 09:35")), "risk_off")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-06-15 14:50")), "risk_off")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-06-15 14:55")), "risk_on")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-07-02 14:50")), "risk_on")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-07-02 14:55")), "risk_off")

        activation = schedule.event_at(pd.Timestamp("2026-06-15 14:55"))
        self.assertIsNotNone(activation)
        self.assertEqual(activation.event, "up")
        self.assertEqual(activation.prior_state, "risk_off")
        self.assertEqual(activation.resulting_state, "risk_on")

        confirmation = schedule.event_at(pd.Timestamp("2026-06-22 14:55"))
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation.prior_state, "risk_on")
        self.assertEqual(confirmation.resulting_state, "risk_on")

    def test_timeline_is_ordered_and_repeated_events_are_idempotent(self) -> None:
        schedule = build_market_regime_schedule(same_day_config(), TRADING_DATES)

        timeline = schedule.timeline
        self.assertEqual(
            list(timeline.columns),
            [
                "signal_date",
                "effective_timestamp",
                "event",
                "label",
                "prior_state",
                "resulting_state",
                "execution_mode",
            ],
        )
        self.assertEqual(
            timeline["signal_date"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-06-08", "2026-06-15", "2026-06-22", "2026-07-02", "2026-07-07", "2026-07-08", "2026-07-13", "2026-07-16", "2026-07-17"],
        )
        self.assertEqual(
            timeline[["prior_state", "resulting_state"]].values.tolist(),
            [
                ["risk_off", "risk_off"],
                ["risk_off", "risk_on"],
                ["risk_on", "risk_on"],
                ["risk_on", "risk_off"],
                ["risk_off", "risk_off"],
                ["risk_off", "risk_off"],
                ["risk_off", "risk_off"],
                ["risk_off", "risk_off"],
                ["risk_off", "risk_off"],
            ],
        )


class NextSessionMarketRegimeScheduleTests(unittest.TestCase):
    def test_next_session_events_apply_at_next_trading_open(self) -> None:
        config = {**same_day_config(), "execution_mode": "next_session_0935"}

        schedule = build_market_regime_schedule(config, TRADING_DATES)

        self.assertEqual(schedule.state_at(pd.Timestamp("2026-06-15 14:55")), "risk_off")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-06-16 09:35")), "risk_on")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-07-02 14:55")), "risk_on")
        self.assertEqual(schedule.state_at(pd.Timestamp("2026-07-03 09:35")), "risk_off")
        self.assertIsNone(schedule.event_at(pd.Timestamp("2026-06-15 14:55")))
        self.assertIsNotNone(schedule.event_at(pd.Timestamp("2026-06-16 09:35")))

    def test_next_session_requires_a_future_trading_date(self) -> None:
        config = {
            **same_day_config(),
            "execution_mode": "next_session_0935",
            "events": [{"signal_date": "2026-07-20", "event": "down", "label": "0amv_down_3pct"}],
        }

        with self.assertRaisesRegex(ValueError, "no future trading session"):
            build_market_regime_schedule(config, TRADING_DATES)


class DatedMarketRegimeConfigTests(unittest.TestCase):
    def test_dated_configs_load_with_deterministic_effective_timestamps(self) -> None:
        root = Path(__file__).resolve().parents[1]
        trading_dates = pd.bdate_range("2026-06-01", "2026-07-20")
        paths = {
            "single_day_4pct_same_day_20260719": root / "config" / "active_market_cap_single_day_4pct_same_day_20260719.json",
            "single_day_4pct_next_session_20260719": root / "config" / "active_market_cap_single_day_4pct_next_session_20260719.json",
            "two_day_4pct_same_day_20260719": root / "config" / "active_market_cap_two_day_4pct_same_day_20260719.json",
            "two_day_4pct_next_session_20260719": root / "config" / "active_market_cap_two_day_4pct_next_session_20260719.json",
        }
        schedules = {
            name: build_market_regime_schedule(load_market_regime_config(path), trading_dates)
            for name, path in paths.items()
        }

        self.assertEqual(
            schedules["single_day_4pct_same_day_20260719"].timeline["effective_timestamp"].tolist(),
            [
                pd.Timestamp("2026-06-08 14:55"),
                pd.Timestamp("2026-06-15 14:55"),
                pd.Timestamp("2026-07-02 14:55"),
                pd.Timestamp("2026-07-07 14:55"),
                pd.Timestamp("2026-07-08 14:55"),
                pd.Timestamp("2026-07-13 14:55"),
                pd.Timestamp("2026-07-16 14:55"),
                pd.Timestamp("2026-07-17 14:55"),
            ],
        )
        self.assertEqual(
            schedules["two_day_4pct_next_session_20260719"].timeline["effective_timestamp"].tolist(),
            [
                pd.Timestamp("2026-06-09 09:35"),
                pd.Timestamp("2026-06-16 09:35"),
                pd.Timestamp("2026-06-23 09:35"),
                pd.Timestamp("2026-07-03 09:35"),
                pd.Timestamp("2026-07-08 09:35"),
                pd.Timestamp("2026-07-09 09:35"),
                pd.Timestamp("2026-07-14 09:35"),
                pd.Timestamp("2026-07-17 09:35"),
                pd.Timestamp("2026-07-20 09:35"),
            ],
        )

        for mode in ("same_day", "next_session"):
            single = schedules[f"single_day_4pct_{mode}_20260719"]
            two_day = schedules[f"two_day_4pct_{mode}_20260719"]
            self.assertEqual(single.timeline["execution_mode"].iloc[0], two_day.timeline["execution_mode"].iloc[0])
            self.assertEqual(len(single.timeline), 8)
            self.assertEqual(len(two_day.timeline), 9)
            for date in trading_dates:
                for time in ("09:35", "14:55"):
                    timestamp = pd.Timestamp(f"{date:%Y-%m-%d} {time}")
                    self.assertEqual(single.state_at(timestamp), two_day.state_at(timestamp))


if __name__ == "__main__":
    unittest.main()
