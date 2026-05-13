FROM node:22-slim AS build
WORKDIR /app
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY config.template.js /usr/share/nginx/html/config.template.js
COPY docker-entrypoint.d/10-config.sh /docker-entrypoint.d/10-config.sh
RUN chmod +x /docker-entrypoint.d/10-config.sh
EXPOSE 8080
