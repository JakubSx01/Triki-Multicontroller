"""Offline BLE error copy and retry classification. No hardware."""

from __future__ import annotations

import unittest

from triki_controller.gui.present import friendly_connection_detail
from triki_controller.transport.ble import humanize_ble_error, is_retryable_gatt_error, retry_gatt_op


class BleErrorCopyTests(unittest.TestCase):
    def test_unlikely_error_is_retryable_and_polish(self) -> None:
        exc = Exception(
            "BleakGATTProtocolError(<BleakGATTProtocolErrorCode.UNLIKELY_ERROR: 14>, "
            "'GATT Protocol Error: Unlikely Error')"
        )
        self.assertTrue(is_retryable_gatt_error(exc))
        text = humanize_ble_error(exc)
        self.assertNotIn("BleakGATTProtocolError", text)
        self.assertNotIn("UNLIKELY_ERROR", text)
        self.assertIn("przycisk", text.lower())

    def test_scan_timeout_is_not_retryable_gatt(self) -> None:
        exc = TimeoutError("scan timed out")
        self.assertFalse(is_retryable_gatt_error(exc))
        self.assertIn("przycisk", humanize_ble_error(exc).lower())

    def test_gui_hides_raw_exception_in_detail(self) -> None:
        raw = (
            "ble error: BleakGATTProtocolError(<BleakGATTProtocolErrorCode.UNLIKELY_ERROR: 14>, "
            "'GATT Protocol Error: Unlikely Error')"
        )
        detail = friendly_connection_detail("error", raw)
        self.assertNotIn("BleakGATTProtocolError", detail)
        self.assertIn("ponów", detail.lower())

    def test_scanning_asks_to_press_button(self) -> None:
        detail = friendly_connection_detail("scanning", "Scanning for Triki")
        self.assertIn("przycisk", detail.lower())


class RetryGattTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_transient_then_succeeds(self) -> None:
        calls = {"n": 0}

        async def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("GATT Protocol Error: Unlikely Error")
            return "ok"

        result = await retry_gatt_op(flaky, attempts=3, delay_s=0.0)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    async def test_gives_up_after_attempts(self) -> None:
        async def always_fail() -> None:
            raise RuntimeError("GATT Protocol Error: Unlikely Error")

        with self.assertRaises(RuntimeError):
            await retry_gatt_op(always_fail, attempts=2, delay_s=0.0)


if __name__ == "__main__":
    unittest.main()
