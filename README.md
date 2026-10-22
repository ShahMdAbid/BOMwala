# BOMwala (not ভম্বোলা )

A local parts aggregator and search tool for electronics hobbyists and engineers in Bangladesh.

- **Web App:** https://bomwala.netlify.app
- **AI Hardware Planner:** https://notebook.google.com/notebook/d41b8307-f082-48b7-936f-6663286d4853

BOMwala indexes inventory across mainstream BD electronics retailers into a unified catalog and pairs it with Google NotebookLM for planning circuits against live, verified local stock.

**Last scraped:** October 22, 2026. Catalogs are re-scraped roughly every পবিত্র বিশ্যুতবার রাত।

---

## AI Hardware Planner

The catalog of ~17,800 in-stock components is loaded into Google NotebookLM:

👉 **[BOMwala on Google NotebookLM](https://notebook.google.com/notebook/d41b8307-f082-48b7-936f-6663286d4853)**

You can ask it to:
- Draft a BOM for a project idea using only parts available in BD.
- Find the cheapest shop for a specific board or sensor.
- Suggest alternative parts if your first choice is unavailable.

---

## Stores Indexed

| Store | Website | Total Items | In-Stock |
| :--- | :--- | :---: | :---: |
| **ElectronicsBD** | [electronics.com.bd](https://electronics.com.bd) | 4,625 | 4,181 |
| **RoboticsBD** | [roboticsbd.com](https://roboticsbd.com) | 4,470 | 3,586 |
| **BDTronics** | [bdtronics.com](https://www.bdtronics.com) | 2,697 | 1,750 |
| **ZerOneTechBD** | [zeronetechbd.com](https://zeronetechbd.com) | 2,454 | 2,454 |
| **TechShopBD** | [techshopbd.com](https://techshopbd.com) | 2,391 | 2,391 |
| **RoboticsShopBD** | [roboticsshop.com.bd](https://roboticsshop.com.bd) | 971 | 971 |
| **RobotechShop** | [robotechshop.com](https://robotechshop.com) | 933 | 685 |
| **RoboDocBD** | [robodocbd.com](https://robodocbd.com) | 872 | 593 |
| **RadioGearBD** | [radiogearbd.com](https://radiogearbd.com) | 856 | 589 |
| **VoltHBD** | [volthbd.com](https://www.volthbd.com) | 752 | 663 |
| **Total** | | **21,021** | **17,863** |

---

## Local Setup

```bash
git clone https://github.com/ShahMdAbid/BOMwala.git
cd BOMwala
pip install -r requirements.txt
python -m uvicorn web.server:app --reload --port 8000
```
Open `http://127.0.0.1:8000` in your browser.
