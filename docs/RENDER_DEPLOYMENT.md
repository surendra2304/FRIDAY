# Deploying FRIDAY to Render

This guide walks you through deploying **FRIDAY** as a 24/7 cloud service on [Render](https://render.com).

---

## 1. Overview & Architecture

When deployed on Render, FRIDAY runs as a **Headless Cloud AI Service**:
- **FastAPI / WebSocket Server**: Real-time event streams, REST endpoints, and task execution.
- **FastMCP Protocol**: Standardized Model Context Protocol server (`/messages`, `/sse`) for external tool integration.
- **Task Engine & Background Workers**: Asynchronous task queue and auto-recovery.
- **Conversation Memory**: SQLite storage for state and history.
- **Health Checks**: Automated `/health` and `/api/health` monitoring endpoints.

---

## 2. Deployment Methods

### Method A: One-Click Blueprint (`render.yaml`) — Recommended

Render supports Infrastructure-as-Code via the included `render.yaml`:

1. **Push your code to GitHub**:
   Ensure your latest commits are pushed to your GitHub repository:
   ```bash
   git push origin main
   ```
2. **Log in to Render**:
   Open [dashboard.render.com](https://dashboard.render.com) and log in.
3. **Create New Blueprint Instance**:
   - Click **New +** in the top-right corner.
   - Select **Blueprint**.
   - Connect your GitHub repository: `surendra2304/FRIDAY`.
   - Render will detect `render.yaml` automatically.
4. **Set Secrets**:
   Render will prompt you for:
   - `GEMINI_API_KEY`: Your Google Gemini API Key.
   - (Optional) `SERPAPI_API_KEY`: For Google Search tools.
5. **Click Apply**:
   Render will build the Docker container and deploy your service automatically.

---

### Method B: Manual Docker Web Service

If you prefer setting up the Web Service manually:

1. In Render Dashboard, click **New +** -> **Web Service**.
2. Connect your GitHub repository: `surendra2304/FRIDAY`.
3. Configure the service:
   - **Name**: `friday-core`
   - **Language / Environment**: `Docker`
   - **Dockerfile Path**: `./Dockerfile`
   - **Docker Context**: `.`
   - **Branch**: `main`
   - **Region**: Oregon (or your preferred region)
   - **Instance Type**: `Free` (or `Starter`)
4. In **Advanced**:
   - **Health Check Path**: `/health`
5. Add **Environment Variables**:
   - `PORT`: `10000`
   - `HOST`: `0.0.0.0`
   - `GEMINI_API_KEY`: `<your_gemini_api_key>`
   - `ENVIRONMENT`: `production`
6. Click **Create Web Service**.

---

### Method C: Manual Native Python Web Service

If you do not want to use Docker:

1. Click **New +** -> **Web Service**.
2. Select **Python 3**.
3. Set the commands:
   - **Build Command**: `./render-build.sh` (or `pip install -e .`)
   - **Start Command**: `uvicorn friday.api.server:app --host 0.0.0.0 --port $PORT`
4. Set **Health Check Path**: `/health`.
5. Add your `GEMINI_API_KEY` under Environment Variables.

---

## 3. Verifying Your Deployment

Once Render displays **`Live`**, verify the deployment by visiting:

```
https://<your-service-name>.onrender.com/health
```

You should receive a JSON response:
```json
{
  "status": "ok",
  "subsystems": {
    "configuration": "healthy",
    "llm_provider": "healthy",
    "memory_database": "healthy",
    "task_manager": "healthy"
  }
}
```

You can also check system metrics:
```
https://<your-service-name>.onrender.com/api/telemetry
```

---

## 4. Free vs. Starter Tier Considerations

| Feature | Free Tier | Starter Plan ($7/mo) |
|---|---|---|
| **Cost** | $0 / month | $7 / month |
| **Inactivity Sleep** | Spun down after 15 min of no traffic; takes ~50s to wake up on next request | Always on (no sleep) |
| **Persistent Disk** | Ephemeral (DB resets on redeploy) | 1 GB persistent disk ($0.25/mo) mounted at `/app/data` |
| **RAM / CPU** | 512 MB / 0.1 CPU | 512 MB to 2 GB / 0.5+ CPU |

> [!TIP]
> To keep the Free Tier service awake, you can set up a free monitoring ping (e.g. via UptimeRobot or Cron-Job.org) targeting `https://<your-service-name>.onrender.com/health` every 10 minutes.

---

## 5. Connecting External Clients

- **REST API Base URL**: `https://<your-service-name>.onrender.com`
- **FastMCP Protocol**:
  - `POST https://<your-service-name>.onrender.com/messages`
  - `GET https://<your-service-name>.onrender.com/sse`
- **WebSockets**: `wss://<your-service-name>.onrender.com/ws`
