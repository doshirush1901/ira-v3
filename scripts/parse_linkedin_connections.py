#!/usr/bin/env python3
"""
Parse the founder's LinkedIn connections and classify sales relevance for Hermes.
Outputs structured JSON to data/cadmus/linkedin_connections.json
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from collections import Counter

CSV_PATH = Path(__file__).parent.parent / "data/imports/16_LINKEDIN DATA/Complete_LinkedInDataExport_03-03-2026.zip/Connections.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "data/cadmus/linkedin_connections.json"
SUMMARY_PATH = Path(__file__).parent.parent / "data/cadmus/linkedin_connections_summary.json"

# ---------------------------------------------------------------------------
# Industry keyword maps — company name / position substrings → industry tags
# ---------------------------------------------------------------------------

COMPANY_INDUSTRY_MAP = {
    "automotive": [
        "auto", "motor", "vehicle", "car ", "cars ", "automotive", "oem",
        "tata motors", "tvs motor", "mahindra", "jaguar", "land rover",
        "stellantis", "tesla", "škoda", "volkswagen", "bmw", "mercedes",
        "audi", "porsche", "volvo", "scania", "daimler", "hyundai", "kia",
        "toyota", "honda", "nissan", "suzuki", "maruti", "renault", "ford",
        "gm ", "general motors", "fiat", "chrysler", "jeep", "dodge",
        "ola electric", "ather", "bajaj", "hero ", "eicher", "ashok leyland",
        "olectra", "ev ", "electric vehicle", "e-mobility",
    ],
    "automotive_interiors": [
        "antolin", "yanfeng", "faurecia", "forvia", "opmobility",
        "lear ", "adient", "grammer", "happich", "oem_partner", "samvardhana",
        "smp ", "dr. schneider", "novares", "mecaplast", "plastic omnium",
        "hella", "valeo", "continental", "magna", "brose",
        "autocomp", "oem_customer_1",
    ],
    "thermoforming": [
        "thermoform", "vacuum form", "pressure form", "frimo", "competitor_e",
        "illig", "kiefel", "gabler", "geiss", "cms ", "maac ",
        "brown machine", "sencorp", "gnk ", "formech", "belovac",
        "plastics unlimited", "thermoformer_1", "partner_1",
        "customer_g", "thermoformer_2",
    ],
    "plastics_polymers": [
        "plastic", "polymer", "polym", "resin", "acrylic", "abs ",
        "hdpe", "polycarbonate", "polypropylene", "polyethylene",
        "klöckner pentaplast", "exxonmobil", "sabic", "basf",
        "covestro", "lanxess", "evonik", "dow ", "dupont",
        "lyondellbasell", "ineos", "borealis", "rajoo",
        "lohia", "kabra", "windsor", "starlinger",
        "nefab", "nelipak", "pactiv", "sealed air",
        "extruder", "extrusion", "injection mold", "blow mold",
        "rotomold", "rotational",
    ],
    "packaging": [
        "packag", "nelipak", "nefab", "pactiv", "sealed air",
        "amcor", "berry global", "sonoco", "graphic packaging",
        "huhtamaki", "constantia", "uflex", "essel", "cosmo films",
        "blister", "clamshell", "tray ", "food packag",
    ],
    "construction_equipment": [
        "jcb", "caterpillar", "komatsu", "volvo ce", "case ",
        "cnh industrial", "john deere", "liebherr", "hitachi construction",
        "doosan", "sany", "xcmg", "zoomlion", "bobcat",
        "construction equipment", "earthmov", "excavat",
    ],
    "agriculture": [
        "tafe", "tractor", "farm equipment", "agri", "deere",
        "mahindra farm", "sonalika", "escorts", "new holland",
        "kubota", "claas", "fendt", "massey", "swaraj",
    ],
    "sanitary_bathroom": [
        "sanitar", "bathroom", "bathtub", "shower", "jacuzzi",
        "customer_f", "kohler", "grohe", "roca", "cera ",
        "hindware", "parryware", "rak ceramic", "duravit",
    ],
    "aerospace_defense": [
        "aerospace", "aviation", "aircraft", "airbus", "boeing",
        "lockheed", "raytheon", "northrop", "bae systems",
        "safran", "thales", "dassault", "embraer", "bombardier",
        "hal ", "hindustan aeronautic", "drdo", "isro",
        "defense", "defence", "military",
    ],
    "rail_transport": [
        "rail", "train", "metro", "alstom", "siemens mobility",
        "bombardier transport", "stadler", "caf ", "knorr-bremse",
        "wabtec", "indian railway",
    ],
    "energy_renewables": [
        "solar", "wind energy", "renewable", "battery", "energy storage",
        "agratas", "catl", "byd", "samsung sdi", "lg energy",
        "panasonic energy", "ev battery", "lithium",
    ],
    "marine": [
        "marine", "shipbuild", "boat", "yacht", "naval",
        "offshore", "customer_a",
    ],
    "medical_healthcare": [
        "medical", "healthcare", "hospital", "pharma", "biotech",
        "surgical", "diagnostic", "prosthe",
    ],
    "machinery_manufacturing": [
        "machin", "manufactur", "engineer", "tooling", "tool maker",
        "die ", "mold ", "mould", "cnc ", "fabricat",
        "industrial", "production", "foundry", "forge",
        "self group",
    ],
}

# Positions that indicate sales-relevant decision makers or technical contacts
RELEVANT_POSITION_KEYWORDS = [
    "managing director", "director", "ceo", "chief executive",
    "coo", "chief operating", "cto", "chief technical", "chief technology",
    "vp ", "vice president", "president", "chairman",
    "general manager", "plant manager", "plant head", "factory manager",
    "head of", "global head",
    "purchas", "procurement", "buying", "sourcing",
    "engineer", "design engineer", "process engineer", "tool engineer",
    "production manager", "operations manager", "manufacturing",
    "project manager", "program manager",
    "business develop", "sales", "key account", "commercial",
    "technical director", "technical manager", "r&d", "research",
    "owner", "founder", "partner", "geschäftsführer", "gérant",
    "directeur", "direttore", "gerente",
]

# Positions that are almost certainly NOT sales-relevant
EXCLUDE_POSITION_KEYWORDS = [
    "recruiter", "talent acqui", "staffing", "hr manager", "human resource",
    "linkedin", "social media manager", "content creator", "influencer",
    "student", "intern ", "trainee", "apprentice",
    "photographer", "graphic design", "ui/ux", "web develop",
    "data scientist", "data analyst", "software engineer", "devops",
    "financial analyst", "accountant", "auditor",
    "lawyer", "attorney", "legal counsel", "advocate",
    "professor", "lecturer", "teacher", "academic",
    "journalist", "reporter", "editor",
    "real estate", "insurance agent", "mortgage",
    "life coach", "motivational",
    "crypto", "blockchain", "nft",
]

# Companies to always exclude
EXCLUDE_COMPANIES = [
    "linkedin", "freelance", "self-employed", "unemployed",
    "looking for", "open to", "career break", "between jobs",
    "fiverr", "upwork",
]

# High-priority companies for Machinecraft (known customers, competitors, targets)
HIGH_PRIORITY_COMPANIES = {
    "frimo": 10,
    "antolin": 9,
    "yanfeng": 9,
    "faurecia": 9,
    "forvia": 9,
    "opmobility": 9,
    "tata motors": 8,
    "oem_customer_1": 8,
    "mahindra": 8,
    "jcb": 8,
    "cnh industrial": 8,
    "john deere": 8,
    "stellantis": 8,
    "tesla": 8,
    "jaguar land rover": 8,
    "škoda": 7,
    "volkswagen": 7,
    "tvs motor": 7,
    "nelipak": 7,
    "klöckner pentaplast": 7,
    "thermoformer_1": 7,
    "plastics unlimited": 7,
    "self group": 7,
    "ola electric": 7,
    "olectra": 7,
    "agratas": 7,
    "nefab": 6,
    "alstom": 6,
    "siemens": 6,
    "reliance": 6,
    "exxonmobil": 6,
    "bajaj": 6,
    "tafe": 6,
    "masco": 6,
    "rajoo": 6,
    "competitor_e": 8,
    "illig": 7,
    "kiefel": 7,
    "happich": 7,
    "oem_partner": 8,
    "samvardhana": 8,
}


def parse_date(date_str: str) -> str:
    """Convert '24 Feb 2026' → '2026-02-24'."""
    try:
        dt = datetime.strptime(date_str.strip(), "%d %b %Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return date_str.strip() if date_str else ""


def get_industry_tags(company: str, position: str) -> list[str]:
    """Return list of industry tags based on company name and position."""
    tags = set()
    text = f"{company} {position}".lower()
    for industry, keywords in COMPANY_INDUSTRY_MAP.items():
        for kw in keywords:
            if kw in text:
                tags.add(industry)
                break
    return sorted(tags)


def is_position_relevant(position: str) -> bool:
    """Check if position indicates a sales-relevant contact."""
    pos_lower = position.lower()
    for kw in EXCLUDE_POSITION_KEYWORDS:
        if kw in pos_lower:
            return False
    for kw in RELEVANT_POSITION_KEYWORDS:
        if kw in pos_lower:
            return True
    return False


def is_company_excluded(company: str) -> bool:
    comp_lower = company.lower()
    for kw in EXCLUDE_COMPANIES:
        if kw in comp_lower:
            return True
    return False


def compute_priority_score(company: str, position: str, tags: list[str]) -> int:
    """0-10 score for how important this connection is to Machinecraft."""
    score = 0
    comp_lower = company.lower()

    for key, val in HIGH_PRIORITY_COMPANIES.items():
        if key in comp_lower:
            score = max(score, val)
            break

    if not score:
        if tags:
            tag_scores = {
                "thermoforming": 8, "automotive_interiors": 7,
                "plastics_polymers": 6, "automotive": 6,
                "construction_equipment": 6, "packaging": 5,
                "agriculture": 5, "sanitary_bathroom": 5,
                "energy_renewables": 5, "marine": 5,
                "aerospace_defense": 5, "rail_transport": 4,
                "machinery_manufacturing": 4, "medical_healthcare": 4,
            }
            score = max(tag_scores.get(t, 3) for t in tags)

    pos_lower = position.lower()
    decision_maker_kws = [
        "managing director", "ceo", "chief executive", "president",
        "owner", "founder", "chairman", "geschäftsführer", "plant manager",
        "plant head", "general manager", "vp ", "vice president",
        "head of", "global head", "director",
    ]
    purchasing_kws = ["purchas", "procurement", "sourcing", "buying"]
    technical_kws = ["engineer", "technical", "r&d", "process", "design"]

    for kw in purchasing_kws:
        if kw in pos_lower:
            score = min(10, score + 2)
            break
    for kw in decision_maker_kws:
        if kw in pos_lower:
            score = min(10, score + 1)
            break
    for kw in technical_kws:
        if kw in pos_lower:
            score = min(10, score + 1)
            break

    return score


def generate_notes(company: str, position: str, tags: list[str], connected_on: str) -> str:
    """Generate contextual notes for Hermes."""
    parts = []
    if tags:
        parts.append(f"Industries: {', '.join(tags)}")
    try:
        dt = datetime.strptime(connected_on, "%Y-%m-%d")
        if dt.year >= 2025 and dt.month >= 10:
            parts.append("Recent connection (post-K2025)")
        elif dt.year >= 2025:
            parts.append(f"Connected {dt.strftime('%b %Y')}")
    except (ValueError, AttributeError):
        pass
    return "; ".join(parts) if parts else ""


def main():
    connections = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i < 4:
                continue
            if len(row) < 7:
                continue

            first_name = row[0].strip()
            last_name = row[1].strip()
            url = row[2].strip()
            email = row[3].strip()
            company = row[4].strip()
            position = row[5].strip()
            connected_on_raw = row[6].strip()

            connected_on = parse_date(connected_on_raw)
            tags = get_industry_tags(company, position)

            excluded_company = is_company_excluded(company)
            position_relevant = is_position_relevant(position)

            sales_relevant = False
            if not excluded_company:
                if tags and position_relevant:
                    sales_relevant = True
                elif tags and not position:
                    sales_relevant = True
                elif position_relevant and company:
                    # Relevant position at a real company, even without industry tags
                    sales_relevant = True

            priority = compute_priority_score(company, position, tags) if sales_relevant else 0
            notes = generate_notes(company, position, tags, connected_on) if sales_relevant else ""

            entry = {
                "first_name": first_name,
                "last_name": last_name,
                "company": company,
                "position": position,
                "connected_on": connected_on,
                "linkedin_url": url,
                "email": email if email else None,
                "sales_relevant": sales_relevant,
                "priority_score": priority,
                "industry_tags": tags,
                "notes": notes,
            }
            connections.append(entry)

    # Sort: sales-relevant first, then by priority desc, then by connected_on desc
    connections.sort(key=lambda x: (-x["sales_relevant"], -x["priority_score"], x["connected_on"]), reverse=False)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(connections, f, indent=2, ensure_ascii=False)

    # --- Summary ---
    total = len(connections)
    relevant = [c for c in connections if c["sales_relevant"]]
    not_relevant = total - len(relevant)

    company_counts = Counter(c["company"] for c in connections if c["company"])
    relevant_company_counts = Counter(c["company"] for c in relevant if c["company"])

    all_tags = Counter()
    for c in relevant:
        for t in c["industry_tags"]:
            all_tags[t] += 1

    priority_dist = Counter(c["priority_score"] for c in relevant)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_connections": total,
        "sales_relevant": len(relevant),
        "not_relevant": not_relevant,
        "relevance_rate": f"{len(relevant)/total*100:.1f}%",
        "top_20_companies_by_connections": [
            {"company": c, "count": n} for c, n in company_counts.most_common(20)
        ],
        "top_20_companies_sales_relevant": [
            {"company": c, "count": n} for c, n in relevant_company_counts.most_common(20)
        ],
        "industry_tag_distribution": {t: n for t, n in all_tags.most_common()},
        "priority_score_distribution": {str(k): v for k, v in sorted(priority_dist.items(), reverse=True)},
        "top_30_connections": [
            {
                "name": f"{c['first_name']} {c['last_name']}",
                "company": c["company"],
                "position": c["position"],
                "priority_score": c["priority_score"],
                "industry_tags": c["industry_tags"],
                "connected_on": c["connected_on"],
                "linkedin_url": c["linkedin_url"],
            }
            for c in sorted(relevant, key=lambda x: -x["priority_score"])[:30]
        ],
    }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Print summary to stdout
    print(f"Total connections: {total}")
    print(f"Sales-relevant:   {len(relevant)} ({len(relevant)/total*100:.1f}%)")
    print(f"Not relevant:     {not_relevant}")
    print()
    print("=== INDUSTRY TAG DISTRIBUTION ===")
    for tag, count in all_tags.most_common():
        print(f"  {count:4d}  {tag}")
    print()
    print("=== TOP 20 COMPANIES (ALL) ===")
    for c, n in company_counts.most_common(20):
        print(f"  {n:3d}  {c}")
    print()
    print("=== TOP 20 COMPANIES (SALES-RELEVANT) ===")
    for c, n in relevant_company_counts.most_common(20):
        print(f"  {n:3d}  {c}")
    print()
    print("=== PRIORITY SCORE DISTRIBUTION ===")
    for score in sorted(priority_dist.keys(), reverse=True):
        print(f"  Score {score:2d}: {priority_dist[score]:4d} connections")
    print()
    print("=== TOP 30 MOST VALUABLE CONNECTIONS ===")
    for i, c in enumerate(sorted(relevant, key=lambda x: -x["priority_score"])[:30], 1):
        print(f"  {i:2d}. [{c['priority_score']:2d}] {c['first_name']} {c['last_name']}")
        print(f"      {c['position']} @ {c['company']}")
        print(f"      Tags: {', '.join(c['industry_tags'])}  |  Connected: {c['connected_on']}")

    print(f"\nSaved: {OUTPUT_PATH}")
    print(f"Saved: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
