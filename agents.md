# AntiGravity Multi-Agent Config — Nifty Signal Project

## Agents

### feature-engineer
Role: Transform raw CSV OHLCV data into ML-ready feature matrices.
Files: backend/feature_engineering.py
Tasks: RSI, MACD, EMA, ATR, Bollinger, PCR, OI change, DTE, label generation.

### model-trainer
Role: Train and persist base learners + meta-learner.
Files: backend/train_model.py, notebooks/train_colab.ipynb
Tasks: XGBoost / LightGBM / CatBoost / LSTM training, RF stacking, backtest.

### signal-engine
Role: Load all models, run ensemble inference on live features.
Files: backend/signal_engine.py
Tasks: Stacking prediction, confidence score, BUY/SELL/HOLD decision.

### upstox-integrator
Role: Live data feed + order placement + kill switch.
Files: backend/upstox_feed.py, backend/upstox_orders.py
Tasks: WebSocket subscription, OHLCV+Greeks parsing, order place/modify/cancel,
       enforce DAILY_LOSS_LIMIT and LIVE_TRADE flag.

### llm-explainer
Role: Generate plain-English signal explanations via LiteLLM proxy.
Files: backend/llm_explainer.py

### api-server
Role: Expose /predict, /signal/latest, /order/place, /health endpoints.
Files: backend/api.py

### dashboard
Role: React UI — signal card, confidence, live chart, place/skip buttons.
Files: frontend/src/*

## Terminal Policy
AntiGravity Settings → Agent → Terminal Command Auto Execution → AUTO
