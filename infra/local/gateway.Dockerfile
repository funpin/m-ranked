FROM nginx:1.28-alpine
COPY infra/local/nginx.conf /etc/nginx/conf.d/default.conf
COPY infra/local/waiting.html /usr/share/nginx/html/waiting.html
