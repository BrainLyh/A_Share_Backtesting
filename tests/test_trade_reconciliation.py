import unittest

import pandas as pd

try:
    from a_share_backtesting.trade_reconciliation import reconcile_trade_economics
except ModuleNotFoundError:
    reconcile_trade_economics = None


class TradeReconciliationTests(unittest.TestCase):
    def test_rebuilds_open_trade_from_fills_and_final_mark(self) -> None:
        self.assertIsNotNone(reconcile_trade_economics)
        fills = pd.DataFrame(
            [
                {
                    "position_id": "position-1",
                    "code": "000001",
                    "timestamp": "2026-06-02 14:55:00",
                    "side": "buy",
                    "reason": "entry",
                    "shares": 100,
                    "raw_price": 10.0,
                    "adjusted_price": 10.0,
                    "gross_notional": 1000.0,
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "slippage_cost": 0.0,
                    "cash_delta": -1000.0,
                },
                {
                    "position_id": "position-1",
                    "code": "000001",
                    "timestamp": "2026-06-03 14:55:00",
                    "side": "sell",
                    "reason": "take_profit_10",
                    "shares": 60,
                    "raw_price": 11.0,
                    "adjusted_price": 11.0,
                    "gross_notional": 660.0,
                    "commission": 0.0,
                    "stamp_duty": 0.0,
                    "slippage_cost": 0.0,
                    "cash_delta": 660.0,
                },
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "position_id": "position-1",
                    "code": "000001",
                    "entry_timestamp": "2026-06-02 14:55:00",
                    "exit_timestamp": pd.NaT,
                    "status": "open",
                    "exit_reason": "open_at_end",
                    "entry_cost": 1000.0,
                    "net_proceeds": 660.0,
                    "net_pnl": 140.0,
                    "net_return": 0.14,
                    "holding_days": 1,
                    "maximum_adverse_excursion": -0.02,
                }
            ]
        )
        positions = pd.DataFrame(
            [
                {
                    "timestamp": "2026-06-03 15:00:00",
                    "position_id": "position-1",
                    "code": "000001",
                    "remaining_shares": 40,
                    "market_value": 480.0,
                    "position_return": 0.14,
                    "position_return_low": 0.10,
                }
            ]
        )

        reconciled = reconcile_trade_economics(
            fills,
            trades,
            positions,
            pd.Timestamp("2026-06-03 15:00:00"),
        )

        self.assertEqual(reconciled.loc[0, "final_remainder"], 40)
        self.assertEqual(reconciled.loc[0, "net_pnl"], 140.0)
        self.assertAlmostEqual(reconciled.loc[0, "net_return"], 0.14)


if __name__ == "__main__":
    unittest.main()
