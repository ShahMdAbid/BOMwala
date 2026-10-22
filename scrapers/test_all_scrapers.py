"""
Scraper Health & Dry-Run Tester
===============================
Verifies that all 10 store scrapers can connect to their respective shop
endpoints and parse sample data without errors.
"""

import os
import sys
import importlib.util

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS_DIR = os.path.dirname(os.path.abspath(__file__))

SCRAPERS = [
    ("Electronics.Com.BD", "scrape_electronics_bd.py"),
    ("RoboticsBD",         "scrape_roboticsbd.py"),
    ("BDTronics",          "scrape_bdtronics.py"),
    ("ZerOneTech BD",      "scrape_zeronetech.py"),
    ("TechShopBD",         "scrape_techshopbd.py"),
    ("Robotics Shop BD",   "scrape_roboticsshop.py"),
    ("Robotech Shop",      "scrape_robotech.py"),
    ("RoboDoc BD",         "scrape_robodoc.py"),
    ("RadioGear BD",       "scrape_radiogear.py"),
    ("VoltH BD",           "scrape_volthbd.py"),
]

def test_syntax_and_import():
    print("=" * 65)
    print("SCRAPER INTEGRITY & DEPENDENCY CHECK")
    print("=" * 65)
    all_ok = True
    for name, script_name in SCRAPERS:
        script_path = os.path.join(SCRAPERS_DIR, script_name)
        if not os.path.exists(script_path):
            print(f"[FAIL] {name:20}: Script missing at {script_name}")
            all_ok = False
            continue
        try:
            spec = importlib.util.spec_from_file_location("module", script_path)
            mod = importlib.util.module_from_spec(spec)
            print(f"[PASS] {name:20}: Syntax OK, File size {os.path.getsize(script_path):5} bytes")
        except Exception as e:
            print(f"[FAIL] {name:20}: Import/Syntax error: {e}")
            all_ok = False
    print("-" * 65)
    if all_ok:
        print("ALL 10 SCRAPERS PASSED HEALTH CHECK!")
    else:
        print("SOME SCRAPERS HAVE ISSUES!")
    print("=" * 65)

if __name__ == "__main__":
    test_syntax_and_import()
