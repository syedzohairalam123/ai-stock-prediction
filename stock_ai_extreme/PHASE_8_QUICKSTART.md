# Phase 8 Quick Start Guide

## Prerequisites

1. **Python 3.10+** installed
2. **Node.js 18+** installed
3. **Virtual environment** activated

## Step 1: Configure API Keys (Optional but Recommended)

For real news data, get free API keys:

1. **NewsAPI** (100 requests/day free):
   - Visit: https://newsapi.org/register
   - Copy your API key

2. **Alpha Vantage** (25 requests/day free):
   - Visit: https://www.alphavantage.co/support/#api-key
   - Copy your API key

3. **Finnhub** (already configured for quotes):
   - Uses existing FINNHUB_API_KEY if available

## Step 2: Update Backend .env File

Edit `backend/.env` and add your keys:

```bash
# Add these lines (leave blank if you don't have keys yet):
NEWSAPI_KEY=your_newsapi_key_here
ALPHA_VANTAGE_KEY=your_alpha_vantage_key_here

# Existing keys still work:
FINNHUB_API_KEY=your_finnhub_key_if_you_have_one
```

**Note**: The app works without API keys using yfinance, but adding keys gives you more news sources.

## Step 3: Start Backend

### Windows PowerShell:
```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

### Linux/Mac:
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Backend will be running at: **http://localhost:8000**

## Step 4: Start Frontend (New Terminal)

### Windows PowerShell:
```powershell
cd frontend
npm run dev
```

### Linux/Mac:
```bash
cd frontend
npm run dev
```

**Expected output:**
```
VITE v5.x.x  ready in XXX ms
➜  Local:   http://localhost:5173/
```

Frontend will be running at: **http://localhost:5173**

## Step 5: Access the Application

Open your browser and go to: **http://localhost:5173**

### Navigate to News Page:
1. Click **"News"** in the navigation menu
2. Or directly visit: http://localhost:5173/news

## Step 6: Initialize News Data

On first visit, the news database will be empty. To fetch news:

1. Click the **"Refresh"** button in the News page header
2. Wait 10-30 seconds for news to be fetched from all sources
3. Page will automatically reload with news articles

**Alternative**: Use API directly:
```bash
# Using curl (if installed):
curl -X POST http://localhost:8000/api/news/refresh?query=Pakistan+stock+market

# Using browser:
# Visit: http://localhost:8000/docs
# Find POST /api/news/refresh
# Click "Try it out" -> Execute
```

## Verify Everything Works

### Backend Health Check:
Visit: http://localhost:8000/health
Should return: `{"status":"ok"}`

### API Documentation:
Visit: http://localhost:8000/docs
Interactive API documentation with all endpoints

### Frontend Check:
Visit: http://localhost:5173
Should see the stock terminal homepage

### News Page Check:
Visit: http://localhost:5173/news
Should see:
- Hero news card (after refresh)
- News feed with articles
- Search bar
- Filters (click "Expand")
- Pagination

## Features to Test

1. **Hero News**: Large featured article with image
2. **News Feed**: Grid of news articles
3. **Search**: Type in search bar (try "dividend" or "bank")
4. **Filters**:
   - Category dropdown (PSX, Banking, etc.)
   - Publisher filter
   - Stock symbol (try "OGDC" or "HBL")
   - Date range presets
5. **Ticker Links**: Click any stock symbol to go to stock page
6. **Pagination**: Navigate between pages
7. **Responsive**: Resize browser to see mobile view

## Troubleshooting

### Port Already in Use

**Backend (8000)**:
```powershell
# Try port 8001 instead:
python -m uvicorn app.main:app --reload --port 8001

# Update frontend/.env:
VITE_API_URL=http://127.0.0.1:8001
```

**Frontend (5173)**:
```powershell
# Vite will automatically try port 5174 if 5173 is busy
```

### Database Not Created

```powershell
cd backend
python -c "from app.db import init_db; init_db()"
```

### Module Not Found Errors

```powershell
# Reinstall dependencies:
cd backend
pip install -r requirements.txt

cd ../frontend
npm install
```

### No News Showing

1. Click "Refresh" button in News page
2. Check backend logs for errors
3. Verify at least yfinance is working (no API key needed)
4. Check http://localhost:8000/api/news/latest

### CORS Errors

Verify backend `.env` has:
```bash
CORS_ORIGINS=http://localhost:5173
```

### TypeScript Errors in Frontend

```powershell
cd frontend
npm run build
# Check for any compilation errors
```

## API Endpoints Reference

### News Endpoints:
- `POST /api/news/refresh` - Fetch fresh news
- `POST /api/news/search` - Search with filters
- `GET /api/news/latest` - Latest articles
- `GET /api/news/hero` - Featured article
- `GET /api/news/by-symbol/{symbol}` - Symbol news
- `GET /api/news/categories` - Available categories
- `GET /api/news/publishers` - Available publishers
- `GET /api/news/{id}` - Article details

### Test with curl:

```bash
# Get latest news:
curl http://localhost:8000/api/news/latest?limit=5

# Get hero news:
curl http://localhost:8000/api/news/hero

# Get OGDC news:
curl http://localhost:8000/api/news/by-symbol/OGDC?limit=5

# Search news:
curl -X POST http://localhost:8000/api/news/search \
  -H "Content-Type: application/json" \
  -d '{"category":"PSX","page":1,"page_size":10}'
```

## Development Tips

### Watch Backend Logs:
```powershell
# Backend automatically reloads on code changes
# Watch terminal for logs
```

### Watch Frontend:
```powershell
# Vite has HMR (Hot Module Replacement)
# Changes appear instantly in browser
```

### Database Inspection:
```powershell
cd backend
sqlite3 neural_market.db
# SQLite commands:
# .tables
# SELECT COUNT(*) FROM news_articles;
# SELECT title, category, publisher FROM news_articles LIMIT 5;
# .exit
```

### Clear News Data:
```sql
DELETE FROM news_articles;
```

## Performance Notes

- First news fetch: 10-30 seconds (fetching from multiple APIs)
- Subsequent loads: Instant (cached in database)
- Refresh cooldown: 5 minutes (configurable)
- Search debounce: 300ms
- Image lazy loading: Only visible images load

## Next Steps

1. **Add API Keys**: Get NewsAPI and Alpha Vantage keys for more sources
2. **Customize Categories**: Edit backend/app/news_service.py
3. **Adjust Filters**: Modify frontend/src/components/NewsFilters.tsx
4. **Style Tweaks**: Edit frontend/src/index.css (search "Phase 8")
5. **Add Related News**: Integrate RelatedNews component in stock pages

## Support

For issues or questions:
1. Check backend logs for errors
2. Check browser console for frontend errors
3. Verify API keys are correct
4. Review PHASE_8_NEWS_README.md for details

## Success Indicators

✅ Backend starts without errors
✅ Frontend starts without errors
✅ News page loads
✅ Refresh button fetches news
✅ Search filters articles
✅ Filters work correctly
✅ Pagination works
✅ Images load (or show fallback)
✅ No console errors
✅ Responsive on mobile
✅ Stock detail pages still work

## Enjoy Your Professional News Desk! 🎉

Phase 8 is complete with real data integration, professional UI, and production-ready code.
