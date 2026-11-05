# GeoAgenticRag Frontend

React + Vite + Tailwind UI for the GeoAgenticRag API: query composer, live
query tree, JEV decision timeline, and evidence panel. Single page, no
router; dark theme; everything bundled (no runtime CDN).

## Commands

```bash
npm install        # install dependencies
npm run dev        # dev server on :5173 (proxies /api and /health to 127.0.0.1:8080)
npm run build      # production build -> dist/
npm run preview    # serve the production build locally
```

The FastAPI backend serves `frontend/dist` at `/` when it exists:

```bash
# from the repository root
jevrag serve --port 8080
```
