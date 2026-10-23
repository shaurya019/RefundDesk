# Stage 1: build the React app
FROM node:20-alpine AS build
WORKDIR /ui
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: serve the static files with nginx and proxy /api to FastAPI
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
