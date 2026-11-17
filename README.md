# M2L - Map to Learn (YouTube Playlist Roadmap Tracker)

An intelligent, interactive roadmap tracker that turns any public YouTube playlist into an actionable, day-by-day curriculum calibrated by completion timeline or daily study hours.

## Features
- **YouTube InnerTube API Engine**: Fetches playlists of any size (even 80+, 100+, 200+ videos) with continuation token pagination.
- **Dual-Mode Calibration**:
  - **By Target Days**: Evenly distributes modules across a chosen number of days (up to 180 days).
  - **By Daily Study Hours**: Balances daily study sessions to match your exact daily availability (e.g. 1.5 hrs/day, 2 hrs/day).
- **Interactive Command Hub**: Focus mode for the active sprint, module check-off, duration metrics, and daily quota tracking.
- **Full Roadmap & Quick Pass Drawer**: Overview of all curriculum days with zero-scroll quick navigation.
- **Backlog Engine**: Tracks overdue modules with rebalancing recommendations.

## Getting Started
1. Run the local backend:
   ```bash
   python server.py
   ```
2. Open `index.html` in your browser (or visit `http://localhost:8000`).
3. Paste any YouTube playlist link and click **Generate Calibrated Roadmap**.
