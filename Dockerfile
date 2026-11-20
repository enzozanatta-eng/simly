# Simly: one container with the solver, the API and the built web app.
# Works on Hugging Face Spaces (port 7860, user 1000), Google Cloud Run, Fly.io, Render.

FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# CalculiX solver + the X/GL libraries the Gmsh wheel links against
RUN apt-get update && apt-get install -y --no-install-recommends \
        calculix-ccx libglu1-mesa libxcursor1 libxinerama1 libxft2 libxrender1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 simly
WORKDIR /app
COPY backend/ backend/
RUN pip install --no-cache-dir "./backend[ai]"
COPY --from=web /web/dist /app/frontend/dist

ENV SIMLY_FRONTEND=/app/frontend/dist \
    SIMLY_RUNS=/tmp/simly-runs \
    OMP_NUM_THREADS=2 \
    PORT=7860
USER simly
EXPOSE 7860
CMD ["sh", "-c", "uvicorn simly.api:app --host 0.0.0.0 --port ${PORT}"]
