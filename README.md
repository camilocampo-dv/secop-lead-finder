# SECOP Lead Finder

Python tooling to identify prospective consulting clients from Colombia's
public procurement data (SECOP II, via the Socrata Open Data API).

## Why I built it

I run an independent delivery-consulting practice and needed a repeatable
way to find companies that have just won several public contracts in a
short window — the point at which a mid-size firm typically outgrows its
delivery capacity — instead of prospecting by hand.

Built with AI assistance, then debugged, rebalanced and validated against
live data.

## What it does

- Queries the SECOP II Electronic Contracts dataset (`jbjy-vk9h`) for
  awards in a configurable window, value range and set of departments
- Excludes public entities, which also appear as contract awardees in
  interadministrative agreements
- Aggregates by supplier and scores each one on five independent signals:
  award volume, organisation size, client diversity, subject-matter
  relevance and recency
- Exports a ranked shortlist to CSV

## Scoring

The score deliberately does **not** reward total contract value
monotonically. The thesis is to find mid-size firms that just absorbed a
volume shock, not the largest players — those already have delivery
governance in place. Value is scored on a sweet-spot curve that peaks
between roughly COP 3bn and 10bn and decays above that.

| Signal | Range | Rationale |
|---|---|---|
| Award volume | 0–24 | Volume shock is the strongest stress indicator |
| Size (sweet spot) | 0–20 | Penalises organisations large enough to already have a PMO |
| Client diversity | 0–10 | More contracting entities means more coordination load |
| Subject relevance | 0–5 | Keyword match against the target niche |
| Recency | 1–5 | Earlier contact window |

## Usage

```bash
pip3 install requests pandas
python3 secop_radar_pmo.py
```

An app token is optional; without one the API throttles requests. Create
one free at datos.gov.co and set it via environment variable.

## Known limitations

Public-entity exclusion works by matching patterns in the registered
company name. This is an approximation — mixed-economy and decentralised
state companies trading under a commercial name can still pass the
filter. The definitive fix is cross-referencing supplier tax IDs against
a public-entity registry, which is not yet implemented.

Field names in the source dataset change occasionally; the script prints
the API error detail and a link to the current field documentation if the
query fails.

## Notes

Reads only publicly published procurement records. Output data is not
committed to this repository.
