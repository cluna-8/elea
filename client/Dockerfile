FROM node:20-alpine

# Install Python3, pip and text parsing libraries for DOCX, TXT, CSV, XLSX
RUN apk add --no-cache python3 py3-pip py3-docx py3-pandas || \
    (apk add --no-cache python3 py3-pip && pip install --no-cache-dir python-docx pandas openpyxl --break-system-packages)

WORKDIR /app

COPY package.json ./
RUN npm install --production

COPY . .

EXPOSE 8095

CMD ["node", "server.js"]
