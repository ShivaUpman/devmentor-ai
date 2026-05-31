FROM node:20-alpine

WORKDIR /app

# Copy package.json first (layer cache trick)
COPY package.json ./

# WHY npm install and not npm ci?
#   npm ci requires a pre-existing package-lock.json.
#   Since this repo doesn't include one (it's gitignored),
#   npm install correctly generates it and installs dependencies.
#   In CI/CD with a committed lockfile, switch back to npm ci.
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
