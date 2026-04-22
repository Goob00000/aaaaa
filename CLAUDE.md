# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Python web scraper template for the [morph.io](https://morph.io) platform. The platform runs `scraper.py` and expects the results written to an SQLite database named `data.sqlite` in the working directory, with at least a table called `data`.

## Runtime & Dependencies

- **Python**: 2.7.9 (pinned in `runtime.txt`)
- **Key libraries**: `scraperwiki` (custom OpenAustralia fork), `lxml`, `cssselect`
- Install dependencies: `pip install -r requirements.txt`

## Running the Scraper

```bash
python scraper.py
```

The output database `data.sqlite` is gitignored.

## Architecture

The entire scraper lives in `scraper.py`. The morph.io platform calls this file directly. The typical pattern is:

1. Fetch HTML with `scraperwiki.scrape(url)`
2. Parse with `lxml.html.fromstring(html)` and `cssselect`
3. Persist results with `scraperwiki.sqlite.save(unique_keys=[...], data={...})`
4. Optionally query existing data with `scraperwiki.sql.select(...)`

All data must end up in a table named `data` inside `data.sqlite`.
