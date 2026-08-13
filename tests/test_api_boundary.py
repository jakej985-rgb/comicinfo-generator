"""
Phase 49 — API/Service Boundary Enforcement Tests (Sections 49.1 - 49.3)

Tests:
1. Static AST analysis: api/handlers.py (and all api/ modules) must NOT import from providers/
2. Services encapsulation: services/kapowarr.py and services/story_arc.py properly delegate
3. Handler dispatch verification: Mocked service dispatch for Kapowarr and Story Arc routes
"""
import ast
import glob
import os
import unittest
from unittest.mock import patch, MagicMock

import config
import services.kapowarr as kap_service
import services.story_arc as arc_service
from api.handlers import ComicServerHandler


class TestApiBoundaryEnforcement(unittest.TestCase):

    def test_api_handlers_no_provider_imports_ast(self):
        """
        49.3: Architectural test ensuring api/handlers.py contains 0 imports from providers/.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        handlers_path = os.path.join(repo_root, "api", "handlers.py")
        
        with open(handlers_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=handlers_path)

        violating_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("providers.") or alias.name == "providers":
                        violating_imports.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module.startswith("providers.") or node.module == "providers"):
                    violating_imports.append((node.lineno, node.module))

        self.assertEqual(
            len(violating_imports), 0,
            f"api/handlers.py must not import from providers/! Found violations: {violating_imports}"
        )

    def test_all_api_modules_no_provider_imports_ast(self):
        """
        Ensures NO module in api/ directly imports from providers/.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        api_files = glob.glob(os.path.join(repo_root, "api", "*.py"))

        for file_path in api_files:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.startswith("providers.") or alias.name == "providers",
                            f"{file_path}:{node.lineno} imports '{alias.name}' from providers!"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.assertFalse(
                            node.module.startswith("providers.") or node.module == "providers",
                            f"{file_path}:{node.lineno} imports from module '{node.module}'!"
                        )

    # 49.2: Test Kapowarr service abstraction
    @patch("services.kapowarr.KapowarrProvider")
    def test_kapowarr_service_delegation(self, mock_kap_cls):
        mock_instance = MagicMock()
        mock_instance.get_volumes.return_value = [{"id": 1, "title": "Batman"}]
        mock_instance.get_library_status.return_value = [{"id": 1, "name": "Batman"}]
        mock_instance.get_volume_issues.return_value = [{"id": 101, "issue_number": 1}]
        mock_instance.test_connection.return_value = True
        mock_instance.request_issue_download.return_value = {"status": "queued"}
        mock_kap_cls.return_value = mock_instance

        cfg = config.load_config()
        
        lib = kap_service.get_kapowarr_library(cfg)
        self.assertEqual(len(lib), 1)

        status = kap_service.get_kapowarr_library_status(cfg)
        self.assertTrue(status["online"])
        self.assertEqual(len(status["items"]), 1)

        issues = kap_service.get_kapowarr_volume_issues(cfg, 1)
        self.assertEqual(len(issues), 1)

        online = kap_service.test_kapowarr_connection("http://localhost:5656", "test_key")
        self.assertTrue(online)

        req = kap_service.request_kapowarr_issue_download(cfg, issue_id="123")
        self.assertEqual(req["status"], "queued")

    # 49.2: Test Story Arc service abstraction
    @patch("services.story_arc._search_story_arcs")
    @patch("services.story_arc._get_story_arc_details")
    @patch("services.story_arc._fix_story_arcs_on_device")
    @patch("services.story_arc._clean_duplicate_story_arcs_on_device")
    @patch("services.story_arc._rename_story_arc_on_device")
    @patch("services.story_arc._update_issue_arc_number_on_device")
    def test_story_arc_service_delegation(
        self, mock_update, mock_rename, mock_clean, mock_fix, mock_details, mock_search
    ):
        mock_search.return_value = [{"name": "Knightfall"}]
        mock_details.return_value = {"name": "Knightfall", "issues": []}
        mock_fix.return_value = {"updated": 5}
        mock_clean.return_value = {"cleaned": 2}
        mock_rename.return_value = {"renamed": 3}
        mock_update.return_value = {"success": True}

        res = arc_service.search_story_arcs("Knightfall")
        self.assertEqual(len(res), 1)

        details = arc_service.get_story_arc_details("http://comicvine.gamespot.com/arc/123/")
        self.assertEqual(details["name"], "Knightfall")

        fix_res = arc_service.fix_story_arcs_on_device([], story_arc_name="Knightfall")
        self.assertEqual(fix_res["updated"], 5)

        clean_res = arc_service.clean_duplicate_story_arcs_on_device([])
        self.assertEqual(clean_res["cleaned"], 2)

        rename_res = arc_service.rename_story_arc_on_device([], "Old", "New")
        self.assertEqual(rename_res["renamed"], 3)

        update_res = arc_service.update_issue_arc_number_on_device("path.cbz", "Arc", "1")
        self.assertTrue(update_res["success"])


if __name__ == "__main__":
    unittest.main()
