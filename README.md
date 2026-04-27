# easeMyDeal — Review Intelligence System

## Folder Structure
```
REVIEW/
├── .env               ← API keys + DB config
├── requirements.txt   ← Python dependencies
├── db.py              ← MySQL connection pool
├── gemini_client.py   ← Gemini AI logic
├── worker.py          ← Background polling engine
├── api.py             ← Flask REST API
└── index.html         ← Frontend UI
```

---

## Step 1 — Install Dependencies
```bash
cd REVIEW
pip install -r requirements.txt
```

---

## Step 2 — Add Gemini API Key
Edit `.env` file:
```
GEMINI_API_KEY=your_actual_key_here
```
Get key from: https://aistudio.google.com/app/apikey

---

## Step 3 — Start Flask API (Terminal 1)
```bash
python api.py
```
Runs on: http://localhost:5000

---

## Step 4 — Start AI Worker (Terminal 2)
```bash
python worker.py
```
Polls DB every 30 seconds. Processes unprocessed tbl_seller_review via Gemini.

---

## Step 5 — Open UI
Open `index.html` in browser directly, or serve it:
```bash
python -m http.server 8080
```
Then visit: http://localhost:8080

---

## How Multi-Category Star Works

User review: "Battery is not good but phone is fast" | Overall: 4 stars

Gemini analyzes sentiment per topic:
- Battery Performance → 2 stars (negative)
- Device Performance  → 5 stars (positive)
- Weighted avg ≈ 3.5 (close to user's 4 ★)


---

## API Endpoints
| Method | URL | Description |
|--------|-----|-------------|
| GET | /api/aggregates | Category stats for UI |
| GET | /api/tbl_seller_review | All tbl_seller_review with categories |
| POST | /api/tbl_seller_review | Submit new review |
| GET | /api/stats | Pending count |
