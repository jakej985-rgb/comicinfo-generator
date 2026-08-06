import unittest
import os
import tempfile
from config import load_config, init_config

class TestConfig(unittest.TestCase):

    def test_default_config(self):
        cfg = load_config()
        self.assertEqual(cfg.kapowarr.url, "http://localhost:5656")
        self.assertEqual(cfg.automation.workers, 4)
        self.assertTrue(cfg.cache.enabled)

    def test_init_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = os.path.join(tmp_dir, "config.yaml")
            created_path = init_config(cfg_path)
            self.assertTrue(os.path.exists(created_path))
            
            cfg = load_config(created_path)
            self.assertEqual(cfg.kapowarr.url, "http://localhost:5656")

    def test_cli_overrides(self):
        cfg = load_config(cli_overrides={"workers": 8, "overwrite": True})
        self.assertEqual(cfg.automation.workers, 8)
        self.assertTrue(cfg.output.overwrite)

if __name__ == "__main__":
    unittest.main()
