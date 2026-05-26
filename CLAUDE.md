# Nifty Signal Project

## Stack
- Backend: Python 3.11, FastAPI, XGBoost, LightGBM, CatBoost, TensorFlow/Keras
- Frontend: React 18, Vite, Recharts for candlestick chart
- LiteLLM Proxy: running at http://localhost:4000
- Upstox SDK: upstox-python-sdk

## Key Rules
- Never hardcode API keys — always use .env file
- Models load from /models/ folder at FastAPI startup
- Kill switch must check daily PnL before every order
- Paper trade mode is default — set LIVE_TRADE=false in .env
- Always run backtest before enabling any new model version
- Never trade during first 15 minutes after market open (9:15–9:30 IST)

## .env Variables Needed
UPSTOX_API_KEY=
UPSTOX_SECRET=
UPSTOX_ACCESS_TOKEN=
LITELLM_API_KEY=
LITELLM_BASE_URL=http://localhost:4000
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
LIVE_TRADE=false
DAILY_LOSS_LIMIT=-2000

## Folder Layout
- data/        — CSVs (nifty50_daily.csv, nifty50_hourly.csv, nifty50_minute.csv)
- models/      — pickled models (xgboost.pkl, lightgbm.pkl, catboost.pkl, meta_rf.pkl, lstm_model.h5)
- backend/     — Python FastAPI service
- frontend/    — React + Vite dashboard
- notebooks/   — train_colab.ipynb (Google Colab T4 training)

## Run Commands
- Backend:  `cd backend && uvicorn api:app --reload --port 8000`
- Frontend: `cd frontend && npm install && npm run dev`
- Train:    Open notebooks/train_colab.ipynb in Google Colab (T4 GPU)
