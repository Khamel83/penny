from __future__ import annotations

import plistlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReliabilityContractTests(unittest.TestCase):
    def test_maya_routing_services_have_canonical_launchd_placeholders(self) -> None:
        for template_name in (
            "com.penny.watcher.plist.template",
            "com.penny.webhook.plist.template",
            "com.penny.tasks.plist.template",
        ):
            template_path = ROOT / "launchd" / template_name
            config = plistlib.loads(template_path.read_bytes())
            environment = config["EnvironmentVariables"]
            self.assertEqual(
                environment["MAYA_TRANSCRIPT_URL"],
                "YOUR_MAYA_TRANSCRIPT_URL_HERE",
                template_name,
            )
            self.assertEqual(
                environment["MAYA_INGEST_TOKEN"],
                "YOUR_MAYA_INGEST_TOKEN_HERE",
                template_name,
            )

    def test_watcher_template_pins_penny_slack_destination(self) -> None:
        template_path = ROOT / "launchd" / "com.penny.watcher.plist.template"
        config = plistlib.loads(template_path.read_bytes())
        environment = config["EnvironmentVariables"]
        self.assertEqual(environment["PENNY_SLACK_CHANNEL_ID"], "C0BKS0QT7FU")

    def test_runtime_verification_uses_copy_paste_safe_secret_predicates(self) -> None:
        reliability = (ROOT / "docs" / "reliability.md").read_text(encoding="utf-8")
        self.assertNotIn("| python3 - <<", reliability)
        self.assertIn('runtime_snapshot="$(mktemp)"', reliability)
        self.assertIn('trap "rm -f \\"$runtime_snapshot\\"" EXIT', reliability)
        self.assertIn('done < "$runtime_snapshot"', reliability)
        self.assertIn("slack_configured=True", reliability)
        self.assertIn("slack_channel_ok=True", reliability)
        self.assertIn("C0BKS0QT7FU", reliability)


if __name__ == "__main__":
    unittest.main()
