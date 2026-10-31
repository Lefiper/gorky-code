# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY miniapp/package.json miniapp/package-lock.json ./
RUN npm ci
COPY miniapp/index.html miniapp/vite.config.js ./
COPY miniapp/src ./src
# VITE_* читаются на этапе сборки и попадают в JS-бандл: только публичные значения.
ARG VITE_API_BASE=""
ARG VITE_BOT_LINK=""
ARG VITE_DEV_USER_ID=""
ENV VITE_API_BASE=$VITE_API_BASE VITE_BOT_LINK=$VITE_BOT_LINK VITE_DEV_USER_ID=$VITE_DEV_USER_ID
RUN npm run build

FROM nginx:1.27-alpine
COPY miniapp/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --retries=6 CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
