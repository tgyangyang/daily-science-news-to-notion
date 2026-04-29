# Daily Science News to Notion

This starter project creates a daily Notion child page containing recent physics, astronomy, mathematics, and AI items from RSS feeds such as Quanta, arXiv, NASA, Phys.org, TechXplore, and ScienceDaily.

It uses:

- GitHub Actions for the daily schedule
- RSS feeds for sources
- The Notion API for delivery
- No OpenAI API and no paid automation service

## Required GitHub Actions secrets

Add these in your GitHub repository:

- `NOTION_TOKEN` — your Notion internal integration token
- `NOTION_PARENT_PAGE_ID` — the Notion page ID or full URL of the parent page where reports should appear

## Files

- `.github/workflows/daily_report.yml` — daily schedule and workflow
- `daily_report.py` — Python script that gathers RSS items and writes to Notion
- `requirements.txt` — Python packages

## Default schedule

The workflow runs every day at 18:17 Japan time.

You can change the schedule in `.github/workflows/daily_report.yml`.
