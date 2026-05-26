# Nifty 50 Signal System

AI-powered Buy/Sell signal system for Nifty 50 options trading on NSE.

## Quick Start

1. **Drop your CSVs** into `data/`:
   - `nifty50_daily.csv`
   - `nifty50_hourly.csv`
   - `nifty50_minute.csv`

2. **Configure secrets**: copy `.env.example` to `.env` and fill in your Upstox + LiteLLM keys.

3. **Train models** (Google Colab T4 recommended):
   - Upload `data/` to Google Drive at `/MyDrive/nifty_signal/data/`
   - Open `notebooks/train_colab.ipynb` in Colab
   - Run all cells (~25–35 min)
   - Download generated `.pkl` / `.h5` files into local `models/`

4. **Run backend**:
   ```bash
   cd backend
   pip install -r ../requirements.txt
   uvicorn api:app --reload --port 8000
   ```

5. **Run frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Safety
- `LIVE_TRADE=false` is the default. Paper trade for 2–3 weeks before flipping.
- Kill switch stops all orders if daily PnL ≤ ₹-2000.
- Never trade in the first 15 minutes after market open.
