FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html
COPY admin.html /usr/share/nginx/html/admin.html

EXPOSE 80
EXPOSE 443

CMD ["nginx", "-g", "daemon off;"]
