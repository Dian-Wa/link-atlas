FROM node:22-alpine AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY server ./server
COPY --from=frontend /build/dist ./dist
RUN useradd --uid 10001 --create-home atlas
USER atlas
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn server.service:app --host 0.0.0.0 --port ${PORT:-10000} --no-access-log"]
