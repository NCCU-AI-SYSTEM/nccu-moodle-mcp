# Independent OAuth login/consent + gateway-verify service (Node/TypeScript).
# Multi-stage: compile TS in a builder, run only prod deps + dist in the runtime.
# Node base pinned to an exact digest-free tag; deps installed with `npm ci`
# (reproducible, lockfile-exact — fails if package.json and the lock disagree).

FROM node:22.11.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:22.11.0-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
EXPOSE 3000
USER node
CMD ["node", "dist/server.js"]
