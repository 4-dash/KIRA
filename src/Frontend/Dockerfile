FROM node:20-bookworm-slim

WORKDIR /app

COPY package*.json ./

# IMPORTANT: rollup native is an OPTIONAL dependency
RUN npm ci --include=optional || npm install --include=optional

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]