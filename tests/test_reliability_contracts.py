from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path

from config import WHISPER_MODEL_REVISION


ROOT = Path(__file__).resolve().parents[1]


class ReliabilityContractTests(unittest.TestCase):
    def test_phase_a_secret_contract_is_dedicated_and_local_first(self) -> None:
        example = (ROOT / "secrets.env.example").read_text(encoding="utf-8")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", example)
        self.assertNotIn("TELEGRAM_CHAT_ID", example)
        for key in (
            "PENNY_INGEST_TOKEN",
            "PENNY_WEBHOOK_SECRET",
            "PENNY_HERMES_WEBHOOK_SECRET",
            "PENNY_SOURCE_REVISION",
            "PENNY_ARCHIVE_OBJECT_ROOT",
            "PENNY_ARCHIVE_MIRROR_ROOT",
            "PENNY_BACKUP_ROOT",
            "PENNY_BACKUP_REMOTE",
            "PENNY_BACKUP_VERIFICATION_RECEIPT",
            "PENNY_WHISPER_MODEL_PATH",
        ):
            self.assertRegex(example, rf"(?m)^#?\s*{re.escape(key)}\s*=")
        self.assertIn("HF_HUB_OFFLINE=1", example)
        self.assertIn(WHISPER_MODEL_REVISION, example)
        self.assertIn("transitional", example.lower())
        self.assertRegex(example, r"(?m)^PENNY_WEBHOOK_HOST=127\.0\.0\.1\s*$")
        self.assertRegex(example, r"(?m)^PENNY_WEBHOOK_ALLOW_NONLOOPBACK=0\s*$")

    def test_launchd_templates_are_runtime_contracts_not_telegram_templates(self) -> None:
        for template_path in sorted((ROOT / "launchd").glob("*.plist.template")):
            text = template_path.read_text(encoding="utf-8")
            self.assertNotIn("TELEGRAM", text, template_path.name)
            values = plistlib.loads(template_path.read_bytes())["EnvironmentVariables"]
            self.assertEqual(values["PENNY_SOURCE_REVISION"], "YOUR_PENNY_SOURCE_REVISION_HERE")

        for name in ("com.penny.watcher", "com.penny.webhook"):
            values = plistlib.loads(
                (ROOT / "launchd" / f"{name}.plist.template").read_bytes()
            )["EnvironmentVariables"]
            self.assertEqual(values["HF_HUB_OFFLINE"], "1")
            self.assertIn(WHISPER_MODEL_REVISION, values["PENNY_WHISPER_MODEL_PATH"])

        webhook = plistlib.loads(
            (ROOT / "launchd" / "com.penny.webhook.plist.template").read_bytes()
        )["EnvironmentVariables"]
        self.assertEqual(webhook["PENNY_WEBHOOK_HOST"], "127.0.0.1")
        self.assertEqual(webhook["PENNY_WEBHOOK_ALLOW_NONLOOPBACK"], "0")
        self.assertEqual(webhook["PENNY_INGEST_TOKEN"], "YOUR_PENNY_INGEST_TOKEN_HERE")
        self.assertEqual(webhook["PENNY_WEBHOOK_SECRET"], "YOUR_PENNY_WEBHOOK_SECRET_HERE")
        for name in ("com.penny.watcher", "com.penny.webhook", "com.penny.tasks"):
            values = plistlib.loads(
                (ROOT / "launchd" / f"{name}.plist.template").read_bytes()
            )["EnvironmentVariables"]
            self.assertEqual(
                values["PENNY_HERMES_WEBHOOK_SECRET"],
                "YOUR_PENNY_HERMES_WEBHOOK_SECRET_HERE",
            )
            self.assertEqual(values["HERMES_WEBHOOK_URL"], "YOUR_HERMES_WEBHOOK_URL_HERE")
            self.assertNotEqual(
                values["PENNY_HERMES_WEBHOOK_SECRET"],
                values.get("PENNY_WEBHOOK_SECRET"),
            )

    def test_doctor_workflow_is_read_only_and_uses_only_bounded_projection(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "health-check.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("scripts/penny_doctor.py --json", workflow)
        self.assertNotIn("launchctl list", workflow)
        self.assertNotIn("launchctl kickstart", workflow)
        self.assertNotIn("pgrep", workflow)
        self.assertNotRegex(workflow.lower(), r"\b(?:open|reset|delete|replay|repair|tail)\b")

    def test_trust_check_enforces_the_phase_a_contract(self) -> None:
        trust_check = (ROOT / "scripts" / "trust_check.py").read_text(encoding="utf-8")
        self.assertIn("check_phase_a_contracts", trust_check)
        self.assertIn("PENNY_WEBHOOK_SECRET", trust_check)
        self.assertIn("PENNY_HERMES_WEBHOOK_SECRET", trust_check)
        self.assertIn("PENNY_SOURCE_REVISION", trust_check)
        self.assertIn("PENNY_ARCHIVE_OBJECT_ROOT", trust_check)
        self.assertIn("scripts/penny_doctor.py", trust_check)
        self.assertNotIn("check_health_check_sync", trust_check)
        self.assertIn("FORBIDDEN_WORKFLOW_TOKENS", trust_check)

    def test_phase_a_documentation_keeps_evidence_boundaries_explicit(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        handoff = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
        deployment = (ROOT / "docs" / "macmini-deployment.md").read_text(encoding="utf-8")
        self.assertIn("Penny Archive", readme)
        self.assertIn("template", readme.lower())
        self.assertIn("local routing", handoff)
        self.assertIn("independent Slack", handoff)
        self.assertIn("independent Maya v2", handoff)
        self.assertIn("watcher.system.log", deployment)

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
        self.assertIn("Penny Archive", reliability)
        self.assertIn("latest verification receipt", reliability)
        self.assertIn("metadata-only", reliability)
        self.assertIn("watcher.system.log", reliability)
        self.assertNotIn("| python3 - <<", reliability)


if __name__ == "__main__":
    unittest.main()
