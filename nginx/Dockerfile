FROM nginx:1.25-alpine

# Remove default config and replace with ours
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/

# WHY nginx:alpine?
#   Alpine Linux is ~5MB vs ~130MB for Debian.
#   Nginx container doesn't need Python, gcc, or any dev tools.
#   Smaller surface area = fewer vulnerabilities.

EXPOSE 80
