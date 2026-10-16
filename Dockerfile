FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM debian:bookworm-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends cmake g++ ninja-build \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY CMakeLists.txt ./
COPY cpp/ ./cpp/
RUN cmake -S . -B out -G Ninja -DCMAKE_BUILD_TYPE=Release -DSCENESEEK_BUILD_TESTS=OFF \
    && cmake --build out

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2 \
    SCENESEEK_DATA_DIR=/data \
    SCENESEEK_FRONTEND_DIR=/app/frontend \
    SCENESEEK_NATIVE_LIBRARY=/usr/local/lib/libsceneseek_core.so
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.lock ./backend/
RUN pip install --no-cache-dir --no-deps -r backend/requirements.lock
COPY --from=native /build/out/libsceneseek_core.so /usr/local/lib/libsceneseek_core.so
COPY backend/sceneseek ./sceneseek
COPY --from=frontend /build/frontend/dist ./frontend
RUN pip check \
    && python -c "import torch, cv2; from transformers import CLIPModel; from sceneseek.native import SimilarityIndex; assert SimilarityIndex().backend == 'cpp'" \
    && mkdir -p /data && useradd --create-home --uid 10001 sceneseek && chown -R sceneseek:sceneseek /app /data
USER sceneseek
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl --fail http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "sceneseek.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
