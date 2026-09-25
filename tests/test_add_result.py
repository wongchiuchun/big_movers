import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Big_movers_server as server


class AddResultPersistenceTests(unittest.TestCase):
    def test_add_update_and_reload_preserve_unique_symbol_year_rows(self):
        # Exercise real API writes on an isolated CSV, never the user's data.
        with tempfile.TemporaryDirectory() as directory:
            filename = str(Path(directory) / 'results.csv')
            with patch.object(server, 'RESULTS_CSV', filename):
                client = server.app.test_client()
                for symbol, year, gain in [('TWST', '2025', '100'), ('TWST', '2026', '200'),
                                           ('ILMN', '2026', '250'), ('TWST', '2026', '661.71')]:
                    row = dict(symbol=symbol, year=year, gain_pct=gain,
                               low_date='2026-01-02', high_date='2026-09-24',
                               low_price='10', high_price='30', avg_vol_b='0.01')
                    response = client.post('/api/add-result', json=row)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.get_json()['ok'])
                # A fresh client reloads from disk without frontend state.
                rows = server.app.test_client().get('/api/results').get_json()
                self.assertEqual(len(rows), 3)
                keyed = {(r['symbol'], r['year']): r for r in rows}
                self.assertEqual(keyed['TWST', '2025']['gain_pct'], '100')
                self.assertEqual(keyed['TWST', '2026']['gain_pct'], '661.71')
                self.assertEqual(keyed['ILMN', '2026']['gain_pct'], '250')
                with open(filename) as stream:
                    self.assertEqual(list(csv.DictReader(stream)), rows)


if __name__ == '__main__':
    unittest.main()
