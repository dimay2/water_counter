import unittest
from unittest.mock import MagicMock, patch
from gsheet_uploader import get_last_readings

class TestGetLastReadings(unittest.TestCase):
    @patch('gsheet_uploader.gspread.authorize')
    @patch('gsheet_uploader.google.auth.default')
    def test_get_last_readings_returns_data(self, mock_auth, mock_authorize):
        # Setup mock
        mock_auth.return_value = (MagicMock(), None)
        mock_spreadsheet = MagicMock()
        mock_sheet = MagicMock()
        mock_authorize.return_value.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id.return_value = mock_sheet
        
        # Return some data
        mock_sheet.get_all_values.return_value = [
            ["Date", "Meter1", "Meter2"],
            ["01/01/2026", "100", "200"],
            ["02/01/2026", "150", "250"]
        ]
        
        result = get_last_readings("test_id", "test_sheet")
        
        self.assertEqual(result, ["02/01/2026", "150", "250"])

    @patch('gsheet_uploader.gspread.authorize')
    @patch('gsheet_uploader.google.auth.default')
    def test_get_last_readings_empty_sheet(self, mock_auth, mock_authorize):
        # Setup mock
        mock_auth.return_value = (MagicMock(), None)
        mock_spreadsheet = MagicMock()
        mock_sheet = MagicMock()
        mock_authorize.return_value.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id.return_value = mock_sheet
        
        mock_sheet.get_all_values.return_value = []
        
        result = get_last_readings("test_id", "test_sheet")
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
