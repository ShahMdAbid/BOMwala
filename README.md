# BOMwala
A local parts aggregator and search tool for electronics hobbyists and engineers in Bangladesh, live at [bomwala.web.app](https://bomwala.web.app).

<blockquote>
<p>Designing around unavailable hardware kills momentum. You finalize a schematic, then find some parts don't exist in the local BD market—or went out of stock last week. Back to the drawing board. Checking ten fragmented store websites just to compare prices and stock wastes hours that belong in the lab.</p>

<p>Sometimes the problem is the opposite: you spend days building a custom driver circuit, then notice a ৳90 module on some random BD shop that does the exact same thing. <strong>Why reinvent the wheel?</strong></p>

<p>And sometimes you're just stuck—no idea where to start, no sense of what's even buildable with what's locally available. <strong>Hard to design around parts you don't know exist.</strong></p>

<p><strong>BOMwala</strong> unifies mainstream BD electronics retailers into a single catalog and pairs it with Gemini Notebook—giving you a free AI project planner based on live, verified local stock.</p>
</blockquote>

**Last scraped:** October 22, 2026. Catalogs are re-scraped weekly.

---



## AI Hardware Planner

The catalog of ~17,800 in-stock components is loaded into Google NotebookLM:

**[BOMwala on Google NotebookLM](https://notebook.google.com/notebook/d41b8307-f082-48b7-936f-6663286d4853)**

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
