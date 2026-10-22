"""
Universal Scraper Launcher & Manager
====================================
Interactive and command-line runner for all Bangladeshi electronics & robotics store scrapers.

Usage:
    python scrapers/runner.py               # Interactive menu
    python scrapers/runner.py --list        # List all shops and status
    python scrapers/runner.py --run 2       # Run shop #2 (RoboticsBD)
    python scrapers/runner.py --merge       # Run master merger
"""

import os
import sys
import subprocess
import sqlite3
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS_DIR = os.path.dirname(os.path.abspath(__file__))

SHOPS = [
    {
        "id": 1,
        "name": "Electronics.Com.BD",
        "script": "scrape_electronics_bd.py",
        "db": "electronics_bd.db",
        "csv": "electronics_bd_components.csv",
        "domain": "electronics.com.bd",
    },
    {
        "id": 2,
        "name": "RoboticsBD",
        "script": "scrape_roboticsbd.py",
        "db": "roboticsbd.db",
        "csv": "roboticsbd_components.csv",
        "domain": "roboticsbd.com",
    },
    {
        "id": 3,
        "name": "BDTronics",
        "script": "scrape_bdtronics.py",
        "db": "bdtronics.db",
        "csv": "bdtronics_components.csv",
        "domain": "bdtronics.com",
    },
    {
        "id": 4,
        "name": "ZerOneTech BD",
        "script": "scrape_zeronetech.py",
        "db": "zeronetech.db",
        "csv": "zeronetech_components.csv",
        "domain": "zeronetechbd.com",
    },
    {
        "id": 5,
        "name": "TechShopBD",
        "script": "scrape_techshopbd.py",
        "db": "techshopbd.db",
        "csv": "techshopbd_components.csv",
        "domain": "techshopbd.com",
    },
    {
        "id": 6,
        "name": "Robotics Shop BD",
        "script": "scrape_roboticsshop.py",
        "db": "roboticsshop.db",
        "csv": "roboticsshop_components.csv",
        "domain": "roboticsshop.com.bd",
    },
    {
        "id": 7,
        "name": "Robotech Shop",
        "script": "scrape_robotech.py",
        "db": "robotechshop.db",
        "csv": "robotechshop_components.csv",
        "domain": "robotechshop.com",
    },
    {
        "id": 8,
        "name": "RoboDoc BD",
        "script": "scrape_robodoc.py",
        "db": "robodoc.db",
        "csv": "robodoc_components.csv",
        "domain": "robodocbd.com",
    },
    {
        "id": 9,
        "name": "RadioGear BD",
        "script": "scrape_radiogear.py",
        "db": "radiogear.db",
        "csv": "radiogear_components.csv",
        "domain": "radiogearbd.com",
    },
    {
        "id": 10,
        "name": "VoltH BD",
        "script": "scrape_volthbd.py",
        "db": "volthbd.db",
        "csv": "volthbd_components.csv",
        "domain": "volthbd.com",
    },
]


def get_db_count(db_filename):
    path = os.path.join(BASE_DIR, db_filename)
    if not os.path.exists(path):
        return 0
    try:
        conn = sqlite3.connect(path)
        cnt = conn.execute("SELECT COUNT(*) FROM components").fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return 0


def show_list():
    print("\n" + "=" * 75)
    print(f"{'#':<3} {'Shop Name':<22} {'Domain':<20} {'DB Items':<10} {'Script':<20}")
    print("=" * 75)
    total = 0
    for s in SHOPS:
        cnt = get_db_count(s["db"])
        total += cnt
        print(f"[{s['id']:>2}] {s['name']:<22} {s['domain']:<20} {cnt:>8}   {s['script']:<20}")
    print("-" * 75)
    print(f"{'TOTAL STORE COMPONENTS:':<46} {total:>8} items")
    
    master_db = os.path.join(BASE_DIR, "bangladesh_components_master.db")
    if os.path.exists(master_db):
        try:
            conn = sqlite3.connect(master_db)
            mcnt = conn.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
            conn.close()
            print(f"{'CENTRAL MASTER DB:':<46} {mcnt:>8} items")
        except Exception:
            pass
    print("=" * 75 + "\n")


def run_shop_scraper(shop_id):
    target = next((s for s in SHOPS if s["id"] == shop_id), None)
    if not target:
        print(f"Error: Invalid Shop ID {shop_id}. Valid range is 1-10.")
        return

    script_path = os.path.join(SCRAPERS_DIR, target["script"])
    print(f"\n>>> Running Scraper for: {target['name']} ({target['domain']})")
    print(f">>> Executing: python {script_path}\n")

    subprocess.run([sys.executable, script_path], cwd=BASE_DIR)


def run_merge():
    merge_script = os.path.join(SCRAPERS_DIR, "merge_master.py")
    print(f"\n>>> Running Master Merger: python {merge_script}\n")
    subprocess.run([sys.executable, merge_script], cwd=BASE_DIR)


def interactive_menu():
    while True:
        show_list()
        print("OPTIONS:")
        print("  [1-10] Run scraper for specific shop")
        print("  [M]    Run master merger (merge all *.db into master DB & CSV)")
        print("  [T]    Run health & syntax tests on all scrapers")
        print("  [Q]    Quit\n")
        
        try:
            choice = input("Select an option: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not choice:
            continue
        if choice.lower() == "q":
            print("Exiting.")
            break
        elif choice.lower() == "m":
            run_merge()
        elif choice.lower() == "t":
            test_script = os.path.join(SCRAPERS_DIR, "test_all_scrapers.py")
            subprocess.run([sys.executable, test_script], cwd=BASE_DIR)
        elif choice.isdigit():
            val = int(choice)
            if 1 <= val <= 10:
                run_shop_scraper(val)
            else:
                print("Invalid number. Choose between 1 and 10.")
        else:
            print("Invalid input.")


def main():
    parser = argparse.ArgumentParser(description="Launcher for Bangladesh Electronics & Robotics Store Scrapers")
    parser.add_argument("--list", action="store_true", help="List all scrapers and their item counts")
    parser.add_argument("--run", type=int, help="Run specific scraper by Shop ID (1-10)")
    parser.add_argument("--merge", action="store_true", help="Run master merger")
    parser.add_argument("--test", action="store_true", help="Run health check on all scrapers")

    args = parser.parse_args()

    if args.list:
        show_list()
    elif args.run:
        run_shop_scraper(args.run)
    elif args.merge:
        run_merge()
    elif args.test:
        test_script = os.path.join(SCRAPERS_DIR, "test_all_scrapers.py")
        subprocess.run([sys.executable, test_script], cwd=BASE_DIR)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
