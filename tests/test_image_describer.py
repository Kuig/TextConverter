"""AI image classification and description, with every AI call mocked.

Usage: python -m unittest discover -s tests -p "test_image_describer.py"
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


class TestImageDescriber(BaseConverterTest):

    @patch("unified_ai_client.preload_model")
    @patch("unified_ai_client.call_ai")
    def test_image_description_mocked(self, mock_call, mock_preload):
        """Foto.jpg with describe mode: mocked AI calls produce description in output."""
        mock_class_resp = MagicMock()
        mock_class_resp.text = '{"category": "diagram"}'
        mock_desc_resp = MagicMock()
        mock_desc_resp.text = "This is a detailed mock description of the diagram."
        mock_call.side_effect = [mock_class_resp, mock_desc_resp]

        in_path = INPUT_DIR / "Foto.jpg"
        out_path = self._out("Foto_described.md")

        textconverter.save_to_file(str(in_path), str(out_path), image_handling="describe")
        self.assertTrue(out_path.exists())

        content = read(out_path)
        self.assertIn("This is a detailed mock description of the diagram.", content,
                      "Description text not found in output")
        # Verify both calls were made (classification + description)
        self.assertEqual(mock_call.call_count, 2, "Expected 2 AI calls (classify + describe)")
        mock_preload.assert_called()
