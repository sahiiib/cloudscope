# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM node:20 AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY index.html vite.config.ts tsconfig*.json ./
COPY src ./src
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime
ENV API_UPSTREAM=cloudscope-api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
