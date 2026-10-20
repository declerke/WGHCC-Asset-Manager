import tempfile
import unittest
from pathlib import Path

from wghcc_asset_manager import DatabaseManager, ITInventoryItem, export_items_to_excel


class ExcelRoundTripTests(unittest.TestCase):
    def test_exported_workbook_imports_into_isolated_database(self):
        item = ITInventoryItem(
            item_id="fixture-item-1",
            name="Fixture Laptop",
            category="Laptops",
            quantity=2,
            condition="Good",
            status="Available",
            brand="Example",
            model="Portable 14",
            serial_number="FIXTURE-001",
            purchase_date="2025-01-15",
            purchase_price=1250.50,
            warranty_expiry="2027-01-15",
            supplier="Fixture Supplier",
            specifications="16 GB RAM",
            location="IT Office",
            assigned_to="",
            notes="Generated test fixture",
            minimum_stock=1,
            date_added="2025-01-15 10:00:00",
            last_updated="2025-01-15 10:00:00",
        )

        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "inventory-fixture.xlsx"
            export_items_to_excel([item], str(workbook))

            # An in-memory SQLite database keeps tests away from the bundled inventory DB.
            database = DatabaseManager(":memory:")
            try:
                imported, failed, errors = database.import_excel(str(workbook), "ci-fixture")

                self.assertEqual((imported, failed), (1, 0), errors)
                self.assertEqual(errors, [])
                items = database.get_items()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].name, "Fixture Laptop")
                self.assertEqual(items[0].category, "Laptops")
                self.assertEqual(items[0].quantity, 2)
                self.assertEqual(items[0].serial_number, "FIXTURE-001")
                self.assertAlmostEqual(items[0].purchase_price, 1250.50)
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
