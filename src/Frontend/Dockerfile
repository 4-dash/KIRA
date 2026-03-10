# STAGE 1: Build
FROM node:20-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# STAGE 2: Production
FROM nginx:stable-alpine
# Copy the build output (dist folder) to Nginx's serving directory
COPY --from=build /app/dist /usr/share/nginx/html
# Copy your internal nginx config from step 1
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]